#!/usr/bin/env bash
# ============ deploy.sh ============
# 把 XGEO 看板部署到一台 Linux 服务器（systemd + nginx）。
#
# 与 service.sh 的分工：那个管本机常驻（macOS LaunchAgent），这个管远程部署。
# 存在的理由是可替换性——部署在一台按天烧额度的机器上时，「换一台重新上线」
# 必须是一条命令，而不是把上次的手工步骤再走一遍。
#
# 用法：
#   scripts/deploy.sh deploy --host ubuntu@1.2.3.4 --domain xgeo.example.com [--key ~/.ssh/x.pem]
#                            [--project freemodel] [--port 8765] [--dir /home/ubuntu/xgeo]
#   scripts/deploy.sh status --host ubuntu@1.2.3.4 [--key ...]
#   scripts/deploy.sh logs   --host ubuntu@1.2.3.4 [--key ...]
#
# 刻意不做的事：
#   - 不碰令牌。.env 由你或 vault 注入；脚本既不生成也不传输凭据，
#     所以它跑起来的部署是「装好了但进不去」的状态，这是对的。
#   - 不申请证书。certbot 要域名解析和安全组都就绪，那是环境前提不是脚本职责，
#     跑完会提示下一步。
#   - 不动远端已有的 nginx server 块，只新增本域名那一个。
set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CMD="${1:-}"; shift || true

HOST=""; DOMAIN=""; KEY=""; PROJECT="freemodel"; PORT="8765"; RDIR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --domain) DOMAIN="$2"; shift 2 ;;
    --key) KEY="$2"; shift 2 ;;
    --project) PROJECT="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --dir) RDIR="$2"; shift 2 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

[ -n "$HOST" ] || { echo "缺 --host（如 ubuntu@1.2.3.4）" >&2; exit 2; }
USER_AT="${HOST%%@*}"
[ "$USER_AT" = "$HOST" ] && USER_AT="ubuntu"          # 没写用户名时按 Ubuntu AMI 惯例
RDIR="${RDIR:-/home/$USER_AT/xgeo}"

SSH_OPTS=(-o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new)
SCP_OPTS=(-o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new)
[ -n "$KEY" ] && { SSH_OPTS+=(-i "$KEY"); SCP_OPTS+=(-i "$KEY"); }
R() { ssh "${SSH_OPTS[@]}" "$HOST" "$@"; }

case "$CMD" in
  deploy)
    [ -n "$DOMAIN" ] || { echo "缺 --domain（如 xgeo.example.com）" >&2; exit 2; }
    command -v tar >/dev/null || { echo "✗ 需要 tar" >&2; exit 1; }

    echo "=== 1/5 打包（只带脚本与一个项目，排除凭据与 node_modules）==="
    # 显式只打包这两个路径，不用 `tar .`——整树打包会把 .env、.git、
    # 以及 work/ 下别的项目一起带上，那是往外部主机泄露凭据和客户数据。
    TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
    tar czf "$TMP/pkg.tgz" -C "$SELF_DIR" \
      --exclude='__pycache__' --exclude='*.pyc' \
      scripts "work/$PROJECT"
    # 兜底检查：包里出现凭据文件就直接中止，不靠人记得
    if tar tzf "$TMP/pkg.tgz" | grep -qiE '(^|/)\.env$|\.pem$|\.key$|secrets?\.json$'; then
      echo "✗ 包里出现疑似凭据文件，已中止。先检查 scripts/ 与 work/$PROJECT/ 下的内容。" >&2
      exit 1
    fi
    echo "  包大小 $(du -h "$TMP/pkg.tgz" | cut -f1)，文件数 $(tar tzf "$TMP/pkg.tgz" | wc -l)"

    echo "=== 2/5 上传解包到 $RDIR ==="
    R "mkdir -p '$RDIR'"
    scp "${SCP_OPTS[@]}" "$TMP/pkg.tgz" "$HOST:/tmp/xgeo-pkg.tgz"
    R "tar xzf /tmp/xgeo-pkg.tgz -C '$RDIR' && rm -f /tmp/xgeo-pkg.tgz && find '$RDIR' -type f | wc -l"

    echo "=== 3/5 运行环境（venv，不污染系统 Python）==="
    # Ubuntu 24+ 的系统 Python 受 PEP 668 保护，pip3 install 会直接失败；
    # 常驻服务也不该往系统环境塞包。
    R "cd '$RDIR' && [ -d .venv ] || python3 -m venv .venv"
    R "cd '$RDIR' && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q requests beautifulsoup4 lxml && .venv/bin/python -c 'import bs4,lxml,requests;print(\"deps ok\")'"

    echo "=== 4/5 systemd 服务 ==="
    R "sudo tee /etc/systemd/system/xgeo.service >/dev/null <<'UNIT'
[Unit]
Description=XGEO dashboard
After=network.target

[Service]
Type=simple
User=$USER_AT
WorkingDirectory=$RDIR
EnvironmentFile=$RDIR/.env
ExecStart=$RDIR/.venv/bin/python $RDIR/scripts/geo.py ui --port $PORT --no-open
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload && sudo systemctl enable xgeo >/dev/null 2>&1 || true
# 必须 restart：重新部署时单元文件被重写了，但 enable --now 对已经在跑的服务是
# 空操作 —— 不 restart 的话新代码躺在磁盘上、进程里跑的还是旧的，而下面的存活检查
# （401）照样通过。这正是「部署了但没生效」最容易发生的地方。
# （这一行在双引号字符串里，注释里**不能出现反引号** —— 那会被远端 shell 当成
#   命令替换去执行，实测踩过一次。）
sudo systemctl restart xgeo"
    sleep 6
    # 401 也算活着：配了令牌时 /api/projects 本来就会回 401
    code="$(R "curl -s -o /dev/null -m 10 -w '%{http_code}' http://127.0.0.1:$PORT/api/projects || true")"
    if [ "$code" = "200" ] || [ "$code" = "401" ]; then
      echo "  ✓ 服务在跑（HTTP $code）"
      [ "$code" = "401" ] || echo "  ⚠ 返回 200 说明 .env 里还没有令牌——这台机器上的看板对任何能访问的人都敞开"
    else
      echo "  ✗ 服务未响应（HTTP $code）。排查：ssh $HOST 'sudo journalctl -u xgeo -n 30'"
      echo "     最常见是 $RDIR/.env 不存在——EnvironmentFile 指向的文件缺失时 systemd 会直接起不来"
      exit 1
    fi

    echo "=== 5/5 nginx 反代 $DOMAIN ==="
    # 已存在就绝不覆盖：certbot 会把 443 的 server 块和证书路径写进同一份文件，
    # 覆盖式重写会让 HTTPS 悄没声地消失（HTTP 还通，所以不看 https 发现不了）。
    R "if [ -f /etc/nginx/sites-available/$DOMAIN ]; then
         echo '  · 已有 $DOMAIN 的 nginx 配置，保留不动（证书配置在里面）'
       else
         sudo tee /etc/nginx/sites-available/$DOMAIN >/dev/null <<'NGINX'
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN www.$DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \"upgrade\";
        proxy_buffering off;
        proxy_read_timeout 3600s;
    }
}
NGINX
         sudo ln -sf /etc/nginx/sites-available/$DOMAIN /etc/nginx/sites-enabled/$DOMAIN
         echo '  ✓ nginx 配置已写入'
       fi
       sudo nginx -t >/dev/null 2>&1 && sudo systemctl reload nginx && echo '  ✓ nginx 已重载'"

    cat <<NEXT

还有三步脚本不替你做（都需要环境就绪，且涉及凭据）：

  1) 注入凭据（脚本不碰这个）：
     .env 里写 XGEO_TOKEN=<管理员令牌> 和可选的 XGEO_PROJECT_TOKENS=<客户令牌>:<项目>

     或者改用账号登录（每人用自己的 FreeModel API Key，不共用令牌）：
       XGEO_ACCOUNTS='邮箱:*;同事邮箱:项目标识'     # * = 管理员，裸邮箱整条丢弃
       XGEO_PUBLIC_HOST=$DOMAIN                    # ★ 这一档必设：本脚本的 nginx 传的是
                                                   #   Host: $DOMAIN，不设它 Host 校验会
                                                   #   把登录页本身 403 掉
       XGEO_AUTH_BASE=https://freemodel.online/api/auth   # 默认值，可省
     两种档可以并存。另外建议配一组**兜底账号**（不经过 fm-auth，认证服务挂了也进得去）：
       XGEO_ADMIN_USER=admin
       XGEO_ADMIN_PASSWORD=<别用弱口令，这台机器在公网上>


     写完 sudo systemctl restart xgeo

  2) 安全组放行 80 / 443（云控制台，脚本够不着）

  3) 上证书：
     ssh $HOST 'sudo certbot --nginx -d $DOMAIN -d www.$DOMAIN --agree-tos -m <邮箱> --redirect'

  验证：curl -s -o /dev/null -w '%{http_code}\\n' https://$DOMAIN/
        期望 401（需令牌）——返回 200 说明令牌没配
NEXT
    ;;

  status)
    R "systemctl is-active xgeo; systemctl is-enabled xgeo; ss -lntp 2>/dev/null | grep ':$PORT ' || echo '端口 $PORT 未监听'" ;;
  logs)
    R "sudo journalctl -u xgeo -n 60 --no-pager" ;;
  *)
    sed -n '2,20p' "$0"; exit 1 ;;
esac
