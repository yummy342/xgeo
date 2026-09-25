// XGEO 采样助手 · 侧边栏
// 流程：载入队列 → 选题 → 填入问题(人按回车) → 答案生成完 → 提取 → 保存 → 上传/导出。

const $ = (s) => document.querySelector(s);
let QUEUE = { questions: [], platforms: [], groups: [] };
let SEL = null;            // 选中的题
let LAST = null;           // 最近一次提取结果
let SAMPLES = [];          // 已采集未上传

// 看板侧字符串进 innerHTML 前必须转义：题目文本来自 geo.json，而它由
// bootstrap / expand 的 LLM 生成（expand 还会从百度/Google 联想词改写），
// 含 HTML 就在扩展源里执行 —— 那个源有 chrome.storage、chrome.tabs 和
// 打本地看板的 fetch 权限。预览框用的是 textContent，说明本来就该转，
// 只是列表渲染这几处漏了。
const esc = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
let GROUPS = [];           // 选中的意图分组（空 = 全部）

// 站点 → 平台码。识别不了的站让用户在下拉里自己选（下拉来自服务端平台清单）。
const HOST2PLAT = {
  "chatgpt.com": "chatgpt", "chat.openai.com": "chatgpt",
  "claude.ai": "claude_web",
  "doubao.com": "doubao_app",
  "google.com": "google_aio",
  "chat.baidu.com": "baidu", "yiyan.baidu.com": "baidu", "wenxin.baidu.com": "baidu",
  "metaso.cn": "metaso", "n.cn": "nano_ai", "bot.n.cn": "nano_ai",
  // 这 6 个是采样目标，原来只在 content.js 的 NEWCHAT 里、不在这张表：
  // 后果是 detectPlatform 恒「未识别」，以及自动跑的「标签页被导走即停」
  // 判据（HOST2PLAT[host] && 与启动时不同）恒假 —— 样本仍记在启动时那个平台上。
  "perplexity.ai": "perplexity", "gemini.google.com": "gemini",
  "chatglm.cn": "glm_web", "kimi.com": "kimi_web", "kimi.moonshot.cn": "kimi_web",
  "yuanbao.tencent.com": "yuanbao",
};

const store = {
  async get(k, d) { const o = await chrome.storage.local.get(k); return o[k] ?? d; },
  async set(k, v) { await chrome.storage.local.set({ [k]: v }); },
};

const DEFAULT_SERVER = "http://127.0.0.1:8765";

// 看板地址只放行 http/https。`javascript:`、`data:` 这类 scheme 也能被 new URL
// 解析出来，直接拼进 fetch 就去向了别处。非法时抛错而不是静默回退到默认地址：
// 回退会让人以为样本发去了远端，实际全落在本机看板里，比报错更难发现。
// 非本机地址不拦 —— 看板可以部署在别处，但 manifest 的 host_permissions 要
// 一并加上那个地址，否则请求会被 Chrome 拦（README「Manual sampling」一节写了）。
function serverUrl() {
  const raw = $("#server").value.trim().replace(/\/$/, "") || DEFAULT_SERVER;
  let u;
  try {
    u = new URL(raw);
  } catch {
    throw new Error(`看板地址不是合法 URL：${raw}`);
  }
  if (u.protocol !== "http:" && u.protocol !== "https:") {
    throw new Error(`看板地址只支持 http/https：${raw}`);
  }
  return raw;
}

// 看板那侧的凭据。两种档都靠这个头：管理员令牌（XGEO_TOKEN）与分项目令牌。
// **账号档例外** —— 那是浏览器里的事，助手进不去；本机开了账号档就给看板也配一个
// 令牌，否则助手所有请求都会 401（README 里写明了）。
function authHeaders() {
  const t = $("#token").value.trim();
  return t ? { "X-Xgeo-Token": t } : {};
}
function slug() { return $("#slug").value; }

// 清掉「上一次提取」的全部痕迹。换题、换平台、换项目都要调 ——
// 不然保存按钮还是可点的，会把上一题的答案记到当前题（或当前平台）名下。
function resetExtract() {
  LAST = null;
  $("#save").disabled = true;
  $("#preview").hidden = true;
  $("#preview").textContent = "";
  $("#exmeta").textContent = "";
}

async function apiGet(path) {
  const r = await fetch(serverUrl() + path, { headers: authHeaders() });
  // 401 单独说清怎么办：看板配了凭据而助手没带令牌时，所有读取都会走到这里，
  // 只说 HTTP 401 的话用户会去查网络。
  if (r.status === 401) throw new Error("看板要求凭据：把访问令牌填到上面那一栏");
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

/** 等标签页 status 变成 complete（或超时）；返回的 Promise 一定会 resolve，
 *  调用方不必接住异常。*/
function waitTabLoaded(tabId, timeout = 12000) {
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      try { chrome.tabs.onUpdated.removeListener(listener); } catch (e) { /* 忽略 */ }
      resolve();
    };
    const listener = (id, info) => { if (id === tabId && info.status === 'complete') finish(); };
    chrome.tabs.onUpdated.addListener(listener);
    setTimeout(finish, timeout);
  });
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  return tab || null;
}

// 采样环境说明。国内引擎多数必须登录，无痕并非总是可行——
// 关键不是「有没有开无痕」，而是「这批样本是在什么环境采的、有没有如实记录」。
const SESSION_NOTE = {
  sandbox: "由 extension/sandbox.sh 起的一次性沙箱：无历史、无 Cookie、未登录，关掉即清除。免登录引擎（百度AI搜索、Google AI Overviews、秘塔、Perplexity 游客态）用这个最干净。",
  incognito: "无痕 + 未登录，最接近陌生买家看到的答案。注意无痕默认禁用扩展（需在 chrome://extensions 里单独授权），且关窗后未上传的样本会丢失。",
  clean_profile: "专用 Chrome Profile：只用于采样，从不搜自己品牌、不点自己官网，并关掉各家的记忆/个性化开关。需要登录的豆包/Kimi/元宝/ChatGPT 用这个。",
  personal: "你的日常账号带着历史与个性化，测出来的是「AI 对你的画像」。这类样本会自动降级为「待复核」，不计入可信的可见性证据。",
};

function sessionMode() { return $("#session").value || "sandbox"; }

async function refreshDiscipline() {
  const el = $("#discipline"), sm = sessionMode();
  $("#sesnote").textContent = SESSION_NOTE[sm];
  const tab = await activeTab();
  const warns = [];
  // 只有选了「无痕」却不在无痕窗口时才报警——选专用 Profile 时无痕本来就不适用
  if (sm === "incognito" && tab && !tab.incognito)
    warns.push("你选的是「无痕未登录」，但当前不是无痕窗口——要么换无痕窗口，要么把上面的采样环境改成实际用的那个");
  if (sm === "personal")
    warns.push("个人日常账号采集：样本会标为「待复核」，别用它下可见性结论");
  warns.push("每题新开对话，不连续追问；答案没提到品牌也照样保存");
  el.hidden = false;
  el.innerHTML = warns.map(w => "· " + w).join("<br>");
  el.style.display = warns.length > 1 ? "" : "none";
}

async function detectPlatform() {
  const tab = await activeTab();
  let code = "";
  if (tab && tab.url) {
    try { code = HOST2PLAT[new URL(tab.url).hostname.replace(/^www\./, "")] || ""; } catch (e) {}
  }
  const known = QUEUE.platforms.find(p => p.code === code);
  $("#plat").textContent = known ? known.label : (code || "未识别");
  // 未识别时必须清空下拉，不能静默停在第一项：在 kimi / perplexity / glm 这类
  // 页面采样时，下拉里默认是「纳米AI搜索（360）」，而该平台码是已知的，
  // 保存不会被拦 —— 答案就这样记到另一个引擎名下直接入库了。
  $("#platSel").value = known ? code : "";
}

function currentPlatform() {
  return $("#platSel").value || "";
}

function collectedKey(p, qid) { return `${p}::${qid}`; }

async function renderQueue() {
  const doneSet = new Set(SAMPLES.map(s => collectedKey(s.platform, s.question_id)));
  const p = currentPlatform();
  // 按分组分节渲染：同一类问题连着采，人的思路不用来回切换
  const byGroup = {};
  QUEUE.questions.forEach(q => (byGroup[q.group || "未分组"] = byGroup[q.group || "未分组"] || []).push(q));
  const sections = Object.entries(byGroup).map(([g, list]) => {
    const left = list.filter(q => !doneSet.has(collectedKey(p, q.id))).length;
    // 分组名来自 geo.json（bootstrap/expand 的 LLM 生成，与题目文本同一个不可信源），
    // 这里原来是裸插值 —— 同文件的 renderGroups 是转义的。MV3 的 CSP 挡掉内联事件
    // 处理器，所以是 HTML 注入 / 面板内 UI 伪造（能塞 <form action=外站>），不是
    // 可直接执行的 XSS，但一行就能收掉。
    return `<div class="small" style="color:var(--t600);margin:8px 0 2px">${esc(g)}
        <span style="color:var(--t500)">· 待采 ${left}/${list.length}</span></div>` +
      list.map(q => `
        <div class="q ${SEL && SEL.id === q.id ? "sel" : ""}" data-id="${esc(q.id)}">
          <span class="id">${esc(q.id)}</span>${esc(q.text)}
          ${doneSet.has(collectedKey(p, q.id)) ? '<span class="done">✓ 已采</span>' : ""}
        </div>`).join("");
  }).join("");
  $("#qlist").innerHTML = sections || '<div class="muted" style="padding:8px">先点「载入队列」</div>';
  document.querySelectorAll(".q").forEach(el => el.onclick = () => {
    SEL = QUEUE.questions.find(x => x.id === el.dataset.id);
    // 换题必须把上一题的提取结果丢掉：LAST 留着上一题的答案、保存按钮仍可点，
    // 直接点「保存本题」就把 Q1 的答案存成了 Q2 的（预览框里明明还是 Q1 的正文）。
    resetExtract();
    renderQueue();
  });
  $("#qmeta").textContent = QUEUE.questions.length
    ? `${QUEUE.brand} · ${QUEUE.questions.length} 题${GROUPS.length ? "（" + GROUPS.join("/") + "）" : ""}` : "";
}

async function loadProjects() {
  try {
    const ps = await apiGet("/api/projects");
    $("#slug").innerHTML = ps.map(p => `<option value="${esc(p.slug)}">${esc(p.name)}</option>`).join("");
    const saved = await store.get("slug");
    if (saved && ps.some(p => p.slug === saved)) $("#slug").value = saved;
  } catch (e) {
    // 别把 apiGet 抛出来的那句吞掉：看板配了凭据时它会说「把访问令牌填到上面那一栏」，
    // 而这里统一回「先启动 geo.py ui」会让用户去重启一个本来就在跑的看板。
    const m = (e && e.message) || String(e);
    $("#qmeta").textContent = /凭据|401/.test(m) ? m : "连不上看板——先启动 geo.py ui";
  }
}

function renderGroups() {
  $("#groups").innerHTML = (QUEUE.groups || []).map(g => `
    <span class="chip ${GROUPS.includes(g.name) ? "on" : ""} ${g.buyer ? "buyer" : ""}"
      data-g="${esc(g.name)}" title="${g.buyer ? "买家意图组——离成交最近" : "需求教育/探测组"}">${esc(g.name)}<span class="n">${esc(g.count)}</span></span>`).join("");
  document.querySelectorAll(".chip").forEach(el => el.onclick = async () => {
    const g = el.dataset.g;
    GROUPS = GROUPS.includes(g) ? GROUPS.filter(x => x !== g) : GROUPS.concat(g);
    await store.set("groups", GROUPS);
    loadQueue();
  });
}

async function loadQueue() {
  try {
    const qp = new URLSearchParams({ limit: "40" });
    if (GROUPS.length) qp.set("groups", GROUPS.join(","));
    else qp.set("intent", "buyer");     // 没选过分组时默认买家意图，和周检表口径一致
    QUEUE = await apiGet(`/api/collect/queue/${slug()}?${qp}`);
    if (!GROUPS.length && QUEUE.selected && QUEUE.selected.length) GROUPS = QUEUE.selected;
    await store.set("slug", slug());
    $("#platSel").innerHTML = QUEUE.platforms
      .map(p => `<option value="${esc(p.code)}">${esc(p.label)}</option>`).join("");
    await detectPlatform();
    renderGroups();
    SEL = QUEUE.questions[0] || null;
    renderQueue();
  } catch (e) {
    $("#qmeta").textContent = "加载失败：" + e.message;
  }
}

async function sendToTab(msg) {
  const tab = await activeTab();
  if (!tab) return { ok: false, error: "找不到活动标签页" };
  try { return await chrome.tabs.sendMessage(tab.id, msg); }
  catch (e) { return { ok: false, error: "此页面没有采样脚本（站点不在支持列表，或需刷新页面）" }; }
}

$("#load").onclick = loadQueue;
// 换平台也要清：A 平台提取的答案记到 B 平台名下，比存错题更隐蔽。
$("#platSel").onchange = () => { resetExtract(); renderQueue(); };
$("#pickbuyer").onclick = async () => {
  GROUPS = (QUEUE.groups || []).filter(g => g.buyer).map(g => g.name);
  await store.set("groups", GROUPS); loadQueue();
};
$("#pickall").onclick = async () => {
  GROUPS = (QUEUE.groups || []).map(g => g.name);
  await store.set("groups", GROUPS); loadQueue();
};

$("#copy").onclick = async () => {
  if (!SEL) return;
  await navigator.clipboard.writeText(SEL.text);
  $("#exmeta").textContent = "已复制，去页面粘贴提问";
};

$("#fill").onclick = async () => {
  if (!SEL) return;
  const r = await sendToTab({ type: "xgeo-fill", text: SEL.text });
  if (!r.ok) { await navigator.clipboard.writeText(SEL.text); }
  $("#exmeta").textContent = r.ok ? "已填入输入框——检查后自己按回车" : (r.error || "填入失败，已复制到剪贴板");
};

$("#extract").onclick = async () => {
  if (!SEL) { $("#exmeta").textContent = "先选一道题"; return; }
  const r = await sendToTab({ type: "xgeo-extract" });
  if (!r.ok) { $("#exmeta").textContent = r.error || "提取失败"; $("#save").disabled = true; return; }
  LAST = r;
  $("#preview").hidden = false;
  $("#preview").textContent = r.answer.slice(0, 800) + (r.answer.length > 800 ? " …" : "");
  $("#exmeta").innerHTML = `<span class="okline">${r.mode === "selection" ? "选区提取" : "自动提取"} · ${r.answer.length} 字 · 引用 ${r.citations.length} 条</span>`;
  $("#save").disabled = false;
};

$("#save").onclick = async () => {
  if (!LAST || !SEL) return;
  const plat = currentPlatform();
  if (!plat) { $("#exmeta").textContent = "先在右上下拉选择当前引擎"; return; }
  SAMPLES = SAMPLES.filter(s => !(s.platform === plat && s.question_id === SEL.id));
  SAMPLES.push({ platform: plat, question_id: SEL.id, question: SEL.text,
                 answer: LAST.answer, citations: LAST.citations, page_url: LAST.url,
                 session_mode: sessionMode(), ts: new Date().toISOString() });
  await store.set("samples:" + slug(), SAMPLES);
  LAST = null; $("#save").disabled = true; $("#preview").hidden = true;
  $("#exmeta").textContent = "已保存。下一题：新开对话再问。";
  // 自动跳到下一道未采的题
  const done = new Set(SAMPLES.map(s => collectedKey(s.platform, s.question_id)));
  SEL = QUEUE.questions.find(q => !done.has(collectedKey(plat, q.id))) || SEL;
  $("#count").textContent = SAMPLES.length;
  renderQueue();
};

/* ---------------- 自动跑队列 ----------------
   人在场、小批量、限速、异常即停。这是「替你操作」，不是「无人值守爬取」：
   侧栏关掉就停、切走标签页就停、撞到验证码/风控立刻停并交回给人。*/
let RUN = null;

const sleep = (ms) => new Promise(r => setTimeout(r, ms));
function alog(msg, cls) {
  const el = document.createElement("div");
  el.className = cls || "";
  el.textContent = `${new Date().toTimeString().slice(0, 5)} ${msg}`;
  $("#autolog").prepend(el);
}

async function waitAnswer(tabId, timeoutMs) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    if (!RUN) return { state: "aborted" };
    await sleep(1500);
    let s;
    try { s = await chrome.tabs.sendMessage(tabId, { type: "xgeo-status", stableMs: 2500 }); }
    catch (e) { continue; }              // 导航中，重试
    if (!s) continue;
    if (s.state === "blocked") return s;
    if (s.state === "done") return s;
  }
  return { state: "timeout" };
}

async function autoRun() {
  // 重入闸必须在**同步段**里：`#auto` 直到两处 confirm() 之后才隐藏，而双击的
  // 第二下早在第一个 await 之后就被派发了 —— 两次执行共用同一个 RUN、抢 i/fails，
  // 同一标签页并发提问、样本归属错乱。
  if (RUN || $("#auto").disabled) return;
  $("#auto").disabled = true;
  try {
    return await autoRunInner();
  } finally {
    $("#auto").disabled = false;
  }
}

async function autoRunInner() {
  const plat = currentPlatform();
  if (!plat) { alog("先在上方选择当前引擎", "okline"); return; }
  const tab = await activeTab();
  if (!tab) return;
  if (sessionMode() === "incognito" && !tab.incognito &&
      !confirm("采样环境选的是「无痕未登录」，但当前不是无痕窗口。\n继续的话样本环境标记会与实际不符——建议先改上面的采样环境。仍要继续吗？")) return;
  const ivl = Math.max(10, +$("#ivl").value || 25) * 1000;
  const cap = Math.max(1, Math.min(30, +$("#cap").value || 20));
  const done = new Set(SAMPLES.map(s => collectedKey(s.platform, s.question_id)));
  const todo = QUEUE.questions.filter(q => !done.has(collectedKey(plat, q.id))).slice(0, cap);
  if (!todo.length) { alog("这个引擎的队列已采完"); return; }
  if (!confirm(`将在当前标签页自动提问 ${todo.length} 题（每题间隔 ${ivl / 1000}s）。\n请全程留在页面上；随时可点「中止」。`)) return;

  let newChatWarned = false;   // 「这个站没有新会话入口」只问一次
  RUN = { tabId: tab.id, plat, total: todo.length, i: 0, fails: 0 };
  $("#auto").hidden = true; $("#abort").hidden = false;
  alog(`开始：${todo.length} 题 · ${plat}${GROUPS.length ? " · " + GROUPS.join("/") : ""}`);

  for (const q of todo) {
    if (!RUN) break;
    RUN.i++;
    // 每轮校验标签页没被导到别的引擎：sendMessage 打到新站的 content script 上
    // 照常工作，plat 还是启动时捕获的旧平台码，于是整批样本的平台标签与来源页
    // 互相矛盾。README 承诺的「标签页导航走即停」原来只在导航到名单外的站时生效。
    try {
      const cur = await chrome.tabs.get(RUN.tabId);
      const host = cur && cur.url ? new URL(cur.url).hostname.replace(/^www\./, "") : "";
      if (host && HOST2PLAT[host] && HOST2PLAT[host] !== plat) {
        alog(`标签页已切到 ${host}，本轮停止（否则样本会记错平台）`, "okline");
        break;
      }
    } catch (e) { /* 拿不到标签页信息就当没变，交给后面的提交失败兜底 */ }
    // 每题新开会话：连续追问会让上文污染后面的答案
    try {
      const nc = await chrome.tabs.sendMessage(RUN.tabId, { type: "xgeo-newchat" });
      if (nc && nc.url) {
        await chrome.tabs.update(RUN.tabId, { url: nc.url });
        // 固定 3.5s 对慢站（ChatGPT 冷启动、要登录的国内引擎）不够，提交失败连着
        // 两题就把自动跑停掉，日志只写「提交失败」，看不出是加载没跟上。
        await waitTabLoaded(RUN.tabId, 15000);
        await sleep(600);   // SPA 还要水合一会儿，complete 之后再缓一下
      } else if (!newChatWarned) {
        // 站点不在新会话映射表里时原来静默就地继续 —— 所有题在同一个对话里
        // 连着问，上文污染后面每一题的答案，而这正是采样纪律的头一条。
        newChatWarned = true;
        if (!confirm("当前站点没有新会话入口：所有题会在同一个对话里连着问，"
                   + "上文会污染后面每一题的答案。\n\n仍要继续吗？")) break;
      }
    } catch (e) {
      if (!newChatWarned) {
        newChatWarned = true;
        if (!confirm("取新会话入口失败：" + e.message
                   + "\n\n继续的话所有题会在同一对话里连着问。仍要继续吗？")) break;
      }
    }
    if (!RUN) break;

    let sent;
    try { sent = await chrome.tabs.sendMessage(RUN.tabId, { type: "xgeo-submit", text: q.text }); }
    catch (e) { sent = { ok: false, error: "页面无采样脚本" }; }
    if (!sent || !sent.ok) {
      RUN.fails++; alog(`[${RUN.i}/${RUN.total}] ${q.id} 提交失败：${(sent && sent.error) || "未知"}`);
      if (RUN.fails >= 2) { alog("连续失败 2 次，已停止", "okline"); break; }
      continue;
    }
    alog(`[${RUN.i}/${RUN.total}] ${q.id} 已提交，等待生成…`);

    const st = await waitAnswer(RUN.tabId, 120000);
    if (!RUN) break;
    if (st.state === "blocked") { alog("⚠ " + st.reason + " —— 已停止，请人工处理", "okline"); break; }
    if (st.state !== "done") { RUN.fails++; alog(`[${RUN.i}] 超时未拿到答案`); if (RUN.fails >= 2) break; continue; }

    let ex;
    try { ex = await chrome.tabs.sendMessage(RUN.tabId, { type: "xgeo-extract", allowSelection: false }); }
    catch (e) { ex = { ok: false, error: "提取失败" }; }
    if (!ex || !ex.ok) { RUN.fails++; alog(`[${RUN.i}] ${ex && ex.error}`); if (RUN.fails >= 2) break; continue; }

    RUN.fails = 0;
    SAMPLES = SAMPLES.filter(s => !(s.platform === plat && s.question_id === q.id));
    SAMPLES.push({ platform: plat, question_id: q.id, question: q.text, answer: ex.answer,
                   citations: ex.citations, page_url: ex.url,
                   session_mode: sessionMode(), ts: new Date().toISOString() });
    await store.set("samples:" + slug(), SAMPLES);
    $("#count").textContent = SAMPLES.length;
    renderQueue();
    alog(`[${RUN.i}/${RUN.total}] ✓ ${ex.answer.length} 字 · 引用 ${ex.citations.length}`, "okline");
    if (RUN.i < RUN.total) await sleep(ivl + Math.random() * 4000);
  }

  const finished = RUN ? RUN.i : 0;
  RUN = null;
  $("#auto").hidden = false; $("#abort").hidden = true;
  alog(`结束：本轮 ${finished} 题，已采集 ${SAMPLES.length} 条。检查无误后点「上传到 XGEO」。`, "okline");
}

$("#auto").onclick = autoRun;
$("#abort").onclick = () => { RUN = null; alog("已中止"); $("#auto").hidden = false; $("#abort").hidden = true; };

$("#upload").onclick = async () => {
  if (!SAMPLES.length) { $("#upmsg").textContent = "还没有已采集的样本"; return; }
  try {
    const r = await fetch(`${serverUrl()}/api/collect/${slug()}`, {
      method: "POST",
      headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
      body: JSON.stringify({ records: SAMPLES }),
    });
    const j = await r.json();
    if (j.ok) {
      const skipped = Array.isArray(j.skipped) ? j.skipped : [];
      if (skipped.length) {
        // 服务端丢了几条（平台码未知/答案为空）就别清本地缓冲 —— 原来只要 ok 为真
        // 就整个清空：丢掉的样本没了、消息还写着「✓ 已导入 N 条」。
        $("#upmsg").textContent = `⚠ 导入 ${j.imported} 条，服务器丢弃 ${skipped.length} 条`
          + `（${skipped[0].why}）—— 本地缓冲**未清空**，请核对后重传`;
        return;
      }
      $("#upmsg").textContent = `✓ 已导入 ${j.imported} 条（A 级人工样本），指标已重算`;
      SAMPLES = []; await store.set("samples:" + slug(), []);
      $("#count").textContent = "0"; renderQueue();
    } else if (r.status === 401) {
      // 上传走的是裸 fetch（要带 body），401 时给的是服务端那句「需要 X-Xgeo-Token 头」——
      // 对插件用户来说该说的是「填上面那个框」。
      $("#upmsg").textContent = "看板要求凭据：把访问令牌填到上面那一栏";
    } else $("#upmsg").textContent = "导入失败：" + (j.error || r.status);
  } catch (e) { $("#upmsg").textContent = "连不上看板：" + e.message; }
};

$("#export").onclick = () => {
  if (!SAMPLES.length) return;
  const byPlat = {};
  SAMPLES.forEach(s => (byPlat[s.platform] = byPlat[s.platform] || []).push(s));
  let md = `# ${QUEUE.brand || slug()} · 插件采样导出 · ${new Date().toISOString().slice(0, 10)}\n\n`;
  for (const [p, list] of Object.entries(byPlat)) {
    md += `## platform: ${p}\n\n`;
    for (const s of list) {
      const cites = s.citations.map(c => `- ${c.url} ${c.title}`).join("\n");
      md += `### ${s.question_id} · ${s.question}\n\n\`\`\`answer\n${s.answer}\n${cites ? "\n引用：\n" + cites + "\n" : ""}\`\`\`\n\n`;
    }
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
  a.download = `xgeo-samples-${Date.now()}.md`;
  a.click();
};

$("#session").onchange = async () => {
  await store.set("session", sessionMode());
  refreshDiscipline();
};

async function loadSampleBuffer() {
  SAMPLES = await store.get("samples:" + slug(), []);
  $("#count").textContent = SAMPLES.length;
}

(async () => {
  // 地址与令牌都要存：换一次就得重填的字段，用户下次打开就会以为助手坏了
  const savedServer = await store.get("server", "");
  if (savedServer) $("#server").value = savedServer;
  $("#token").value = await store.get("token", "");
  for (const id of ["server", "token"]) {
    $("#" + id).addEventListener("change", () => store.set(id, $("#" + id).value.trim()));
  }
  await loadProjects();
  $("#session").value = await store.get("session", "sandbox");
  GROUPS = await store.get("groups", []);
  await loadSampleBuffer();
  // 切换项目必须重读该项目的缓冲：不重读的话，A 项目采的样本会以 B 的 slug
  // 上传（B 的指标被 A 的答案污染），紧接着还把 B 的槽位清空。
  $("#slug").onchange = async () => {
    await store.set("slug", slug());
    resetExtract();
    await loadSampleBuffer();
    renderQueue();
  };
  await refreshDiscipline();
  chrome.tabs.onActivated.addListener(() => { refreshDiscipline(); detectPlatform(); });
  chrome.tabs.onUpdated.addListener((_, info) => { if (info.status === "complete") { refreshDiscipline(); detectPlatform(); } });
})();
