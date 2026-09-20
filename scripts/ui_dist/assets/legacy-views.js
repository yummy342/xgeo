/* 从 scripts/ui.html 抽出的旧辅助函数——迁移收尾阶段的遗留部分。
 *
 * 17 个视图已全部迁到 Svelte。这里只剩下还被新组件调用的那批：
 * 纯工具、HTML 片段生成器、弹窗、任务动作。保留名单由
 * frontend/scripts/extract-legacy.py 维护，来源是对 frontend/src 的扫描。
 *
 * 这是普通脚本（非 ESM），函数落在全局作用域。它们读的 D / SLUG / ST /
 * RUNNING 等由 lib/legacy.js 的 installBridge() 用 getter 注入。
 *
 * 下一步：把这里的弹窗逐个改写成 Svelte 组件，桥就能拆掉了。
 * 由 frontend/scripts/extract-legacy.py 生成，不要手改。
 */

const $=(s,r=document)=>r.querySelector(s);

const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

const pct=v=>v==null?'—':(v*100).toFixed(v>0&&v<0.095?1:0)+'%';
// 非 2xx 也尽量读 body：服务端错误响应带具体原因（如「缺凭证：GITHUB_TOKEN」），
// 只报 HTTP 状态码会把可行动的信息丢掉

const api=async(u,o)=>{try{const r=await fetch(u,o);const j=await r.json().catch(()=>null);
  if(!r.ok)return (j&&j.error)?j:{error:`HTTP ${r.status}`};
  return j??{error:'响应不是 JSON'}}catch(e){return{error:'连接失败：服务未响应'}}};

const mktLabel=m=>m==='cn'?'国内':m==='global'?'海外':'通用';

const post=(u,b)=>api(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});

function head(kicker,title,sub){return `<div class="kicker">${esc(kicker)}</div>
  <h3 style="margin-bottom:6px">${title}</h3>
  ${sub?`<p class="soft" style="font-size:14px;max-width:700px;text-wrap:pretty">${sub}</p>`:''}`}

/* ===================== 界面多语言(zh/en/ja) =====================
   中文是源文案。en/ja 用「整句精确匹配 + 短节点词级替换」在渲染后翻译 DOM,
   字典未覆盖的保持中文(优雅降级);项目数据(问题库/工单/阵地文案)跟随数据语言,不翻。*/

const ULANG=(()=>{
  const q=new URLSearchParams(location.search).get('lang');
  if(['zh','en','ja'].indexOf(q)>=0){try{localStorage.setItem('ulang',q)}catch(e){}return q}
  const s=localStorage.getItem('ulang');if(['zh','en','ja'].indexOf(s)>=0)return s;
  const l=(navigator.language||'').toLowerCase();
  return l.indexOf('zh')===0?'zh':l.indexOf('ja')===0?'ja':'en'})();
document.documentElement.lang={zh:'zh-CN',en:'en',ja:'ja'}[ULANG]||'zh-CN';

function setLang(l){localStorage.setItem('ulang',l);location.reload()}

const NAV=[
 {t:'现状 · 我在 AI 里什么样',items:[['overview','总览'],['engines','引擎表现'],['competitors','竞品对比'],['questions','问题库'],['samples','样本库']]},
 {t:'诊断 · 为什么是这样',items:[['siteaudit','站点体检'],['gaps','差距诊断'],['channels','阵地地图'],['facts','品牌事实库']]},
 {t:'提升 · 该做什么',items:[['plan','行动计划'],['workbench','内容工作台'],['assets','部署资产']]},
 {t:'成效 · 做了有没有用',items:[['verify','效果验收'],['report','报告与交付']]},
 {t:'账号',items:[['settings','设置'],['publishing','发布渠道']]},
];

function badge(k){
  if(!D||!D.analytics)return'';
  const a=D.analytics;
  if(k==='questions')return String(D.question_count||'');
  if(k==='siteaudit')return D.audit&&D.audit.avg_score!=null?String(D.audit.avg_score):'';
  if(k==='assets'&&D.lint&&D.lint.total)return '!'+D.lint.total;
  if(k==='engines')return String((a.engines||[]).length||'');
  if(k==='plan'){const n=(D.tasks||[]).filter(t=>t.status!=='done').length;return n?String(n):''}
  if(k==='gaps'){const q=(a.questions||[]).filter(x=>x.content!=='已成稿'&&!x.brand_probe).length;return q?String(q):''}
  if(k==='verify'){const n=(a.q_delta||[]).filter(x=>(x.after||0)>(x.before||0)).length;return n?String(n):''}
  return'';
}

async function runAction(a,params){
  const r=await post('/api/run',{slug:SLUG,action:a,params:params||{}});
  if(!r.ok){toast(r.error||'启动失败','err');return null}
  RUNNING=r.job.id;LASTJOB=r.job.id;LOGOFF=0;renderSide();pollJob();
  toast('已启动：'+((ACTIONS[a]||{}).label||a));return r.job;
}

async function pollJob(){
  clearTimeout(POLL); if(!RUNNING)return;
  const r=await api(`/api/job/${RUNNING}?offset=${LOGOFF}`);
  if(r.error){RUNNING=null;renderSide();toast('任务状态丢失','err');return}
  LOGOFF=r.offset;
  const pre=$('#joblog'); if(pre&&r.log){pre.textContent+=r.log;pre.scrollTop=pre.scrollHeight}
  const st=$('#jobstat'); if(st)st.innerHTML=r.job.status==='running'
    ?`<span class="spin"></span>${esc(r.job.label)} 运行中…`
    :`${r.job.status==='done'?'✓':'✗'} ${esc(r.job.label)} ${({done:'完成',failed:'失败',stopped:'已停止',interrupted:'已中断'})[r.job.status]||r.job.status}`;
  if(r.job.status==='running'){POLL=setTimeout(pollJob,900)}
  else{RUNNING=null;
    toast(`${r.job.label} ${r.job.status==='done'?'完成':'结束'}`,r.job.status==='done'?'':'err');
    if(R==='onboard'&&ST.obStep===2){
      if(r.job.status==='done'){ST.obFail=false;ST.obStep=3;await load(SLUG,true);return}
      ST.obFail=true;render();return}
    await load(SLUG,true)}
}

/* ===================== 总览 ===================== */

function expandModal(){
  if(!EXPD){
    modal(`<h4 style="font-size:17px">拓词选题 · 来自真实搜索需求</h4>
      <p class="muted" style="font-size:12.5px;margin-top:6px">词根：品牌 + 竞品 + 品类；来源：百度下拉（国内）+ Google 补全（海外）。勾选后入库，不自动加题。</p>
      <p class="muted" style="font-size:12.5px">还没有拓词数据</p>
      <div class="row" style="justify-content:flex-end;margin-top:12px">
        <button class="btn btn-secondary" onclick="closeModal()">取消</button>
        <button class="btn btn-primary" onclick="closeModal();runAction('expand')">开始拓词</button></div>`);
    return}
  const cand=(EXPD.terms||[]).filter(t=>!t.in_bank);
  const groups=['推荐','比较','替代','价格','风险','品牌验证','场景'];
  const rows=groups.map(gp=>{
    const ts=cand.filter(t=>t.group===gp);
    if(!ts.length)return'';
    return `<div style="font-size:12px;color:var(--a300);margin:12px 0 4px">${gp} · ${ts.length}</div>`+
      ts.map(t=>`<label class="row" style="gap:8px;padding:6px 8px;border-radius:var(--r-sm);cursor:pointer;box-shadow:inset 0 -1px 0 var(--line);align-items:flex-start">
        <input type="checkbox" class="expchk" data-q="${esc(t.question)}" data-g="${esc(t.group)}" data-m="${esc(t.market)}" style="margin-top:3px">
        <span style="flex:1">
          <span style="font-size:13px">${esc(t.question)}</span>
          <span style="display:block;font-size:11px;color:var(--t600);margin-top:2px">${esc(t.term)} · ${esc(t.root)} · ${mktLabel(t.market)}${t.new?' · <span style="color:var(--a300)">新词</span>':''}</span>
        </span></label>`).join('');
  }).join('');
  modal(`<h4 style="font-size:17px">拓词选题 · 来自真实搜索需求</h4>
    <p class="muted" style="font-size:12px;margin-top:4px"><span>词根：品牌 + 竞品 + 品类；来源：百度下拉（国内）+ Google 补全（海外）。勾选后入库，不自动加题。</span>
      <span>${EXPD.generated_at?esc(EXPD.generated_at)+' · ':''}</span><span>${EXPD.llm?'LLM 转写':'模板转写'}</span></p>
    <div style="max-height:440px;overflow:auto;margin-top:6px">${rows||'<p class="muted" style="font-size:12.5px">候选都已入库——重新拓词看看有没有新词。</p>'}</div>
    <div class="row" style="justify-content:flex-end;margin-top:12px">
      <button class="btn btn-ghost" onclick="closeModal();runAction('expand')">重新拓词</button>
      <button class="btn btn-secondary" onclick="closeModal()">取消</button>
      <button class="btn btn-primary" onclick="expAdd()">加入问题库</button></div>`);
}

function expAddIdx(i){
  const t=EXPD&&EXPD.terms&&EXPD.terms[i];
  if(t)expAdd([{text:t.question,group:t.group,market:t.market}]);
}

async function expAdd(items){
  if(!items){
    items=[...document.querySelectorAll('.expchk')].filter(c=>c.checked)
      .map(c=>({text:c.dataset.q,group:c.dataset.g,market:c.dataset.m}));
  }
  if(!items.length){toast('先勾选要入库的题','err');return}
  const r=await post('/api/questions-add',{slug:SLUG,items});
  toast(r.ok?`已加入 ${r.added} 题`:(r.error||'保存失败'),r.ok?'':'err');
  if(r.ok){closeModal();load(SLUG,true)}
}

/* ===================== 问题库 ===================== */

async function distToggle(qid,ch,on){
  const r=await post('/api/distribution/'+SLUG,{qid,channel:ch,on});
  if(r.ok){D.distribution=r.distribution;toast(on?'已标记铺设 ✓':'已取消标记');render()}
  else toast('失败：'+(r.error||''),'err');
}

async function editSheet(name){
  const r=await fetch(`/files/${SLUG}/samples/${encodeURIComponent(name)}`);
  if(!r.ok){toast('采样表不存在','err');return}
  const text=await r.text();
  modal(`<h4 style="font-size:17px">${esc(name)}</h4>
    <p class="muted" style="font-size:12px">把答案粘进 \`\`\`answer 块；留空的题会被跳过，不会算成「未提及」。</p>
    <textarea id="sheet" class="input" rows="18">${esc(text)}</textarea>
    <div class="row" style="justify-content:flex-end;margin-top:12px">
      <button class="btn btn-secondary" onclick="closeModal()">取消</button>
      <button class="btn btn-primary" onclick="importSheet(${esc(JSON.stringify(name))})">保存并导入</button></div>`);
}

async function importSheet(name){
  const r=await post('/api/sample-import',{slug:SLUG,file:name,text:$('#sheet').value});
  toast(r.ok?'已导入':'失败：'+(r.error||''),r.ok?'':'err');
  if(r.ok){closeModal();load(SLUG,true)}
}

/* ===================== 设置 ===================== */

function editPub(i){
  const x=PUB.publishers[i];
  const g=x.guide||{};
  modal(`<h4 style="font-size:17px">${esc(x.name)}</h4>
    <p class="muted" style="font-size:12px;margin-top:4px">${esc(x.note)}</p>
    ${(g.steps||[]).length?`<div style="background:var(--deep);border-radius:var(--r-md);padding:11px 14px;margin-top:10px">
      <div class="row" style="margin-bottom:5px">
        <span style="font-size:11px;letter-spacing:.08em;color:var(--t600);flex:1">怎么拿到这些配置</span>
        ${g.url?`<a href="${esc(g.url)}" target="_blank" style="font-size:11.5px;color:var(--a300)">打开申请页 ↗</a>`:''}</div>
      ${g.steps.map((s,n)=>`<div style="display:flex;gap:8px;padding:3px 0;font-size:12px;line-height:1.55;color:var(--t400)">
        <span style="color:var(--a300);flex:none">${n+1}.</span><span>${esc(s)}</span></div>`).join('')}
    </div>`:''}
    ${x.env.map(e=>`<div class="field"><label>${esc(e)}${x.missing.includes(e)?'':'（已配置，留空保持不变）'}</label>
      <input class="input pub-env" data-env="${esc(e)}" type="password" autocomplete="off" placeholder="${x.missing.includes(e)?'必填':'留空保持不变'}"></div>`).join('')}
    ${x.cfg.map(c=>`<div class="field"><label>${esc(c.key)}</label>
      <input class="input pub-cfg" data-key="${esc(c.key)}" value="${esc(c.value)}" placeholder="${esc(c.hint)}"></div>`).join('')}
    <div class="row" style="justify-content:flex-end;margin-top:12px">
      <button class="btn btn-secondary" onclick="closeModal()">取消</button>
      <button class="btn btn-primary" onclick="savePub(${i})">保存</button></div>`);
}

async function savePub(i){
  const x=PUB.publishers[i],u={};
  document.querySelectorAll('.pub-env').forEach(el=>{const v=el.value.trim();if(v)u[el.dataset.env]=v});
  if(Object.keys(u).length){
    const r=await post('/api/keys',{updates:u});
    if(!r.ok){toast('凭证保存失败：'+(r.error||''),'err');return}
  }
  if(x.cfg.length){
    const cfg={};document.querySelectorAll('.pub-cfg').forEach(el=>cfg[el.dataset.key]=el.value.trim());
    const r=await post('/api/publishcfg/'+SLUG,{platform:x.code,cfg});
    if(!r.ok){toast('配置保存失败：'+(r.error||''),'err');return}
  }
  toast('已保存');closeModal();PUB=null;KEYS=null;render();
}

async function stopJob(){if(RUNNING){await post(`/api/job/${RUNNING}/stop`,{});toast('已发送停止信号')}}

async function showLog(id){
  const r=await api(`/api/job/${id}?offset=0`);const pre=$('#joblog'),st=$('#jobstat');
  if(pre&&!r.error){pre.textContent=r.log||'';pre.scrollTop=pre.scrollHeight;
    if(st)st.innerHTML=`${r.job.status==='done'?'✓':'✗'} ${esc(r.job.label)} ${({done:'完成',failed:'失败',stopped:'已停止',interrupted:'已中断'})[r.job.status]||r.job.status}`}
}

async function setMonitor(days){
  const next=days?new Date(Date.now()+days*864e5).toISOString().slice(0,10):null;
  const r=await post('/api/config/'+SLUG,{monitor:days?{every_days:days,next_run:next}:{}});
  toast(r.ok?(days?`已开启：每 ${days} 天自动跑完整一期，首次 ${next}`:'已关闭周期复跑'):'失败：'+(r.error||''),r.ok?'':'err');
  if(r.ok){SET_CFG=null;render()}
}

async function obCreate(){
  const url=$('#ob-url').value.trim();
  if(!url){toast('请填写官网地址','err');return}
  ST.obUrl=url;ST.obName=$('#ob-name').value.trim();
  ST.obMkt=document.querySelector('input[name=obm]:checked').value;
  // 没配任何引擎 Key：明确告知会缺什么,让用户选择继续或先去配置
  const okKeys=(KEYS||[]).filter(k=>k.ok===true);
  if(!okKeys.length&&!confirm('还没有配置任何引擎 API Key。\n\n继续创建将跳过「答案采样」与「AI 推导问题库/品牌事实」——只做抓站和站点体检，问题库与品牌事实需要手动填写。\n\n建议先到「设置」配置至少一个 Key（如 DeepSeek / 智谱GLM）。\n\n仍要继续吗？'))
    {go('settings');return}
  const mkNeed=ST.obMkt==='both'?['cn','global']:[ST.obMkt];
  const miss=mkNeed.filter(m=>!okKeys.some(k=>k.market===m));
  if(okKeys.length&&miss.length&&!confirm(`所选市场里 ${miss.map(m=>m==='cn'?'国内':'海外').join('、')} 尚无已配置的引擎 Key，该市场的自动采样会被跳过（可稍后补 Key 或用人工采样表）。\n\n仍要继续吗？`))
    {go('settings');return}
  ST.obNoSample=$('#ob-nosample').checked;
  const r=await post('/api/init',{url,name:ST.obName,
    market:ST.obMkt,max_pages:25});
  if(!r.ok){toast(r.error||'创建失败','err');return}
  ST.obSlug=r.slug;KEYS=null;PROJECTS=null;
  await load(r.slug,true);
  ST.obStep=2;ST.obFail=false;R='onboard';render();
  const p=ST.obNoSample?{'--no-sample':true}:{};
  const job=await runAction('autopilot',p);
  if(!job){ST.obStep=1;render();return}
}

async function obRetry(){
  ST.obFail=false;render();
  const p=ST.obNoSample?{'--no-sample':true}:{};
  const job=await runAction('autopilot',p);
  if(!job){ST.obFail=true;render()}
}

/* ===================== 站点体检 ===================== */


// 新壳的侧栏复用这三者（普通脚本的 const 不挂 window，必须显式导出）
window.GL_NAV = NAV;
window.GL_BADGE = badge;
window.GL_ULANG = ULANG;
