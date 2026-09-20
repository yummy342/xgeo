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

const diagTag=d=>{if(!d)return'<span style="font-size:12px;color:var(--t600)">—</span>';
  const cls=d.sev==='P0'?'tag-accent':d.sev==='P1'?'pill-warn':d.sev==='P2'?'tag-dim':'pill-good';
  return `<span class="tag ${cls}" title="${esc(d.detail)}" style="cursor:help">${esc(d.type)}</span>`};

function distRows(list,me){ // 品牌提及分布条：me=自己品牌名高亮
  const max=((list||[])[0]||{}).rate||1;
  return (list||[]).map(x=>{const mine=x.name===me;
    return `<div class="row" style="gap:8px;padding:4px 0">
      <span style="width:132px;flex:none;font-size:12.5px;${mine?'color:var(--a300)':''};overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(x.name)}">${esc(x.name)}${mine?' ⭑':''}</span>
      <div class="bar" style="flex:1;height:6px"><div style="height:100%;width:${Math.max(3,Math.round(x.rate/max*100))}%;background:${mine?'var(--a400)':'#595d6c'};border-radius:4px"></div></div>
      <span style="width:86px;flex:none;text-align:right;font-size:11.5px;color:var(--t400)">${pct(x.rate)} · ${x.hits} 次</span></div>`}).join('')
    ||'<div class="muted" style="font-size:12px">本期没有实体被提及</div>';
}

function progBar(p,f,w){ // 任务级 before/after：首测(f) → 当前(p) → 目标
  if(!p)return'';
  const fmt=v=>v==null?'—':(p.pct?pct(v):v),op=p.op==='lte'?'≤':'≥';
  let ratio; // 完成度：lte 型看从基线降到目标走了多远；gte 型看距目标比例
  if(p.op==='lte'){const b=(f&&f.cur!=null?f.cur:null)??p.base??Math.max(p.cur,p.target,1);
    ratio=b>p.target?(b-p.cur)/(b-p.target):(p.cur<=p.target?1:0)}
  else ratio=p.target?p.cur/p.target:0;
  ratio=Math.max(0,Math.min(1,ratio));
  return `<div style="margin-top:5px;max-width:280px">
    <div style="font-size:11px;color:var(--t500)">${esc(p.label)}：首测 ${fmt(f&&f.cur)} → 当前 <b style="color:var(--t300)">${fmt(p.cur)}</b> · 目标 ${op}${fmt(p.target)}</div>
    <div class="bar" style="margin-top:3px;height:5px"><div style="height:100%;width:${Math.round(ratio*100)}%;background:${ratio>=1?'var(--a400)':'var(--accent)'};border-radius:4px"></div></div></div>`}

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

function headline(){
  const a=D.analytics,h=a.health,tr=a.trend||[];
  if(h.score==null)return['还没有采样数据','到「设置 → 运行任务」跑一期，才能开始诊断。'];
  const prev=tr.length>1?tr[tr.length-2]:null;
  const dm=prev&&prev.mention!=null&&tr[tr.length-1].mention!=null?((tr[tr.length-1].mention-prev.mention)*100).toFixed(1):null;
  const cite=h.subs.cite,m=h.subs.mention;
  if((m||0)===0)return['AI 还没有主动提到过你',
    `最近一期 ${tr.length?tr[tr.length-1].samples:0} 条采样中无提示提及率为 0——不是排名靠后，是还没进入候选集。先补内容缺口和 P0 阵地，不是继续铺渠道。`];
  if((cite||0)<0.05)return['AI 开始提到你了，但几乎不引用你',
    `提及率 ${pct(m)}${dm?`（较上期 ${dm>0?'+':''}${dm}pp）`:''}，但引用份额只有 ${pct(cite)}——「有人在说你」而「你没有可引用的落点」。优先补可被抽取的内容。`];
  return['提及与引用同步在涨',`提及率 ${pct(m)}、引用份额 ${pct(cite)}。保持内容节奏，开始扩阵地。`];
}

function demandTag(qid){
  const d=EXPD&&EXPD.q_demand&&EXPD.q_demand[qid];
  if(!d)return'';
  const tip=`匹配 ${d.n} 条下拉词：${(d.terms||[]).join(' / ')}`;
  return ` <span class="tag ${d.new?'tag-accent':'tag-dim'}" style="font-size:10px" title="${esc(tip)}">🔥 ${d.new?'需求上升':'有搜索需求'}</span>`;
}

function demandRank(qid){const d=EXPD&&EXPD.q_demand&&EXPD.q_demand[qid];return d?(d.new?2:1):0}

function demandSort(qs){
  if(!EXPD)return qs;
  const idx=new Map(qs.map((q,i)=>[q.id,i]));
  return qs.slice().sort((a,b)=>{
    if((a.brand_probe?1:0)!==(b.brand_probe?1:0))return a.brand_probe?1:-1;
    const d=demandRank(b.id)-demandRank(a.id);
    return d||idx.get(a.id)-idx.get(b.id)});
}

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

function showMethod(){
  const li=(t)=>`<li style="margin:5px 0;line-height:1.6">${t}</li>`;
  const h=(t)=>`<div style="font-size:14px;font-weight:500;margin:18px 0 4px;color:var(--a300)">${t}</div>`;
  modal(`<h4 style="font-size:17px">这些数字怎么来的——生成规则与指标口径</h4>
    <p class="muted" style="font-size:12.5px;margin-top:4px">全站指标都来自「问题库 × 引擎」的批量采样。规则是固定的、可复现的，下面是完整口径。</p>

    ${h('一、问题库怎么批量生成（接入品牌 / AI 补充选题）')}
    <ul style="font-size:12.5px;color:var(--t400);padding-left:18px">
      ${li('输入只有四样：<b>品牌名、品类、目标用户、一句话定义</b>——全部从官网正文自动抽取，抽不到的标「待确认」，不用常识填充。')}
      ${li('由你配置的 LLM 按固定提示词出题，分七组：<b>推荐、比较、替代、价格、风险、品牌验证、场景</b>，每组 2–4 题。')}
      ${li('题量按市场定：国内 18–24 题；海外 14–20 题；双市场 = 国内 16–20 + 海外 12–16 + 通用 2。编号 q001 起为国内、q101 起为海外、q901 起为通用。')}
      ${li('要求真实口语问法：国内题像真人在 AI 里打的字；海外题是<b>英文原生问法</b>，不是中文题翻译。')}
      ${li('<b>关键纪律：绝大多数问题不出现品牌名</b>——考的是 AI 会不会主动想到你。只有「品牌验证」组点名，这类题带「点名」标记，单独归品牌认知，不计入提及率。')}
      ${li('生成后自动去重、校验分组与市场标记；问题库随时可人工编辑，改完重跑采样才生效。')}
      ${li('拓词选题：以品牌/竞品/品类为词根，拉百度下拉（国内）与 Google 补全（海外）的真实搜索词，按线索词归入七组并转写成问句。只产候选、入库必须手动勾选；每期快照 diff，首次出现的词标「需求上升」，参与选题排序但不进任何指标。')}
    </ul>

    ${h('二、采样怎么跑')}
    <ul style="font-size:12.5px;color:var(--t400);padding-left:18px">
      ${li('每期把问题库里的每道题逐个引擎各问一遍，存<b>原始回答全文</b>——引擎表现页的「样本回放」就是原文。')}
      ${li('市场路由：中文题只问国内引擎，英文题只问海外引擎，通用题两边都问；两套市场的指标分开算，分母各用各的。')}
      ${li('引擎分三类：联网 API（回答带真实引用来源）、不联网 API（测的是模型参数化知识里的品牌认知）、无公开 API（走人工采样表）。行内已标注。')}
      ${li('每条样本同时记录 API 耗时；引擎表现页显示中位耗时（抗超时长尾），让采样成本透明。')}
      ${li('<b>结果稳定性</b>：单条 AI 回答天然有随机性，所以指标从不看单条——看的是「几十道题 × 多引擎」的聚合比例；模型版本按引擎固定（设置里可查可改）；采样命令支持 <code>--repeat</code> 多轮加密样本；跨期对比遵守归因纪律——单期波动默认只作观察，连续两期同向变化才当趋势。')}
    </ul>

    ${h('三、指标口径（引擎表现页每一列）')}
    <ul style="font-size:12.5px;color:var(--t400);padding-left:18px">
      ${li('<b>提及率</b> = 无提示样本中，回答提到品牌（含别名）的比例。问题里点名了品牌的样本一律剔除——否则必然 100%，是假阳性。别名漏配会低估，到「设置 → 编辑当前品牌配置」补。')}
      ${li('<b>提及位次</b> = 回答里品牌相对其他候选品牌出现顺序的中位数，越小越靠前。')}
      ${li('<b>引用份额</b> = 回答引用的全部域名条数中，属于你自有域名（含子域名）的比例。不联网引擎通常没有引用，显示 —。')}
      ${li('<b>结论</b>列的判语规则：0% → 完全不可见；严格高于同市场所有引擎 → 表现最好；≥5% → 有存在感但不稳定；&lt;5% → 偶发提及；从未引用你的域名会单独标注。样本不足或无法比较时不下结论。')}
      ${li('<b>GEO 健康分</b> = 提及率×30 + 引用份额×25 + 阵地覆盖×20 + 内容承接×15 + 事实一致性×10。没测到的项不按 0 分计，而是把权重重新归一，避免惩罚「还没测」。')}
      ${li('<b>诊断</b>列（问题库/差距诊断）按固定优先级分型：<b>疑似负面</b>（品牌附近命中负面线索词，需人工复核）&gt; <b>竞品主导</b>（你 0% 且某对手出现率 ≥50%）&gt; <b>完全缺席</b>（0%）&gt; <b>排名靠后</b>（位次中位 &gt;3）&gt; 表现正常。悬停标签可看依据。')}
      ${li('<b>疑似负面</b>只是线索词（避雷/不推荐/投诉/scam 等）在品牌名 ±百余字符窗口内命中，不做自动定性——定性靠样本回放人工复核，误报比漏报便宜。')}
      ${li('<b>品牌提及分布 / 竞品最强引擎</b>：统计回答中出现的你与已配置竞品（别名并入），分母为对应范围的无提示样本数，同一样本提多次只算一次。<b>未配置的品牌不计入</b>——竞品清单和别名越全，分布越真实。')}
    </ul>

    <p class="muted" style="font-size:11.5px;margin-top:10px">规则实现在 scripts/bootstrap.py（出题）、expand.py（拓词）、sample.py（采样与判定）、analytics.py（指标），本弹窗与代码同步维护。</p>
    <div class="row" style="justify-content:flex-end;margin-top:12px">
      <button class="btn btn-primary" onclick="closeModal()">知道了</button></div>`);
}

async function editQuestions(){
  const cfg=await api('/api/config/'+SLUG);
  const rows=(cfg.questions||[]).map(q=>`${q.id}|${q.group}|${q.market}|${q.text}`).join('\n');
  modal(`<h4 style="font-size:17px">编辑问题库</h4>
    <p class="muted" style="font-size:12px">每行一题：<code>编号|分组|市场(cn/global/both)|问题</code>。保存后重跑采样才生效。</p>
    <textarea id="qedit" class="input" rows="18">${esc(rows)}</textarea>
    <div class="row" style="justify-content:flex-end;margin-top:12px">
      <button class="btn btn-secondary" onclick="closeModal()">取消</button>
      <button class="btn btn-primary" onclick="saveQuestions()">保存</button></div>`);
}

async function saveQuestions(){
  const cfg=await api('/api/config/'+SLUG);
  const qs=[];
  for(const line of $('#qedit').value.split('\n')){
    const m=line.split('|');if(m.length<4||!m[3].trim())continue;
    qs.push({id:m[0].trim(),group:m[1].trim()||'推荐',market:['cn','global','both'].indexOf(m[2].trim())>=0?m[2].trim():'cn',text:m.slice(3).join('|').trim()});
  }
  cfg.questions=qs; if(cfg.bootstrap)cfg.bootstrap.needs_review=false;
  const r=await post('/api/config/'+SLUG,cfg);
  toast(r.ok?`已保存 ${qs.length} 题`:'保存失败',r.ok?'':'err');
  if(r.ok){closeModal();load(SLUG,true)}
}

/* ===================== 差距诊断 ===================== */

function chanFitQs(c){
  return (D.analytics.questions||[]).filter(q=>!q.brand_probe
    &&(c.fits||[]).includes(q.group)&&(q.market==='both'||q.market===c.market));
}

function distOf(qid,chid){return !!(((D.distribution||{})[qid]||{})[chid])}

async function distToggle(qid,ch,on){
  const r=await post('/api/distribution/'+SLUG,{qid,channel:ch,on});
  if(r.ok){D.distribution=r.distribution;toast(on?'已标记铺设 ✓':'已取消标记');render()}
  else toast('失败：'+(r.error||''),'err');
}

function chanOpen(name){
  const c=((D.blueprint||{}).channels||[]).find(x=>x.name===name);
  if(!c){toast('蓝图里没有这个阵地','err');return}
  const rel=(D.tasks||[]).filter(t=>(t.title||'').indexOf(name.split('（')[0].split(' / ')[0])>=0);
  modal(`<h4 style="font-size:17px">${esc(c.name)}</h4>
    <div class="row" style="gap:6px;margin-top:6px">
      <span class="tag ${c.priority==='P0'?'tag-accent':c.priority==='P1'?'tag-neutral':'tag-dim'}">${c.priority}</span>
      <span class="tag tag-outline">${esc(c.kind||'')}</span>
      <span class="tag ${c.covered?'pill-good':'tag-accent'}">${c.covered?'✓ 本期已被引用':'未建'}</span>
      <span style="font-size:11.5px;color:var(--t600)">${c.national?('全库引用量 '+c.national.toLocaleString()):''}${c.position?(' · 平均引用位置 '+c.position):''}${c.platforms?(' · 覆盖 '+c.platforms+' 个平台端'):''}</span></div>
    <p style="font-size:13px;color:var(--t400);line-height:1.6;margin:10px 0 4px">${esc(c.why||'').replace(/\*\*(.+?)\*\*/g,'<b>$1</b>')}</p>
    <div style="font-size:12px;color:var(--t600);margin:10px 0 4px">建什么（逐项做完为止）</div>
    <ul style="margin:0;padding-left:18px;font-size:13px;line-height:1.8">
      ${(c.forms||[]).map(f=>`<li>${esc(f)}</li>`).join('')||'<li class="muted">蓝图未给出具体形式</li>'}</ul>
    <div class="spec" style="margin-top:12px">
      <div><div class="k">建多少</div><div class="v">${esc(c.volume||'—')}</div></div>
      <div><div class="k">节奏</div><div class="v">${esc(c.cadence||'—')}</div></div>
      <div><div class="k">谁来做</div><div class="v">${esc(c.owner||'—')}</div></div>
      <div><div class="k">相关工单</div><div class="v">${rel.length?rel.map(t=>esc(t.id)).join('、'):'—'}</div></div>
    </div>
    ${(c.fits||[]).length?(()=>{const qs=chanFitQs(c);
      const done=qs.filter(q=>distOf(q.id,c.id)).length;
      const sorted=qs.slice().sort((a,b)=>{
        const w=q=>distOf(q.id,c.id)?3:q.content==='已成稿'?0:q.content==='缺口'?2:1;
        return w(a)-w(b)});
      return `<div style="font-size:12px;color:var(--t600);margin:12px 0 4px">适合放这里的内容
        <span class="muted">（承接 ${c.fits.join('/')} 类 · 共 ${qs.length} 题 · 已铺 ${done}）</span></div>
      ${sorted.slice(0,6).map(q=>`<div class="row" style="gap:8px;padding:4px 0;font-size:12.5px;cursor:pointer;box-shadow:inset 0 -1px 0 var(--line)"
          title="点击到内容工作台写/改这篇" onclick="closeModal();go('workbench',{wq:${esc(JSON.stringify(q.id))}})">
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;${distOf(q.id,c.id)?'color:var(--t600)':''}">${esc(q.text)}</span>
        <span class="tag ${q.content==='已成稿'?'pill-good':'tag-dim'}" style="font-size:10px;flex:none">${esc(q.content)}</span>
        ${distOf(q.id,c.id)?'<span class="tag tag-outline" style="font-size:10px;flex:none">已铺 ✓</span>':''}</div>`).join('')}
      ${qs.length>6?`<div class="muted" style="font-size:11px;padding-top:4px">…共 ${qs.length} 题，其余在问题库按类别筛</div>`:''}`})():
      '<p class="muted" style="font-size:11.5px;margin-top:10px">该阵地是收录/基础设施型，不承接具体内容篇目。</p>'}
    <p class="muted" style="font-size:11.5px;margin-top:10px">内容素材从「内容工作台」按目标问题产出；官网类阵地的部署片段在「部署资产」（含 DEPLOY.md 步骤与验收标准）。</p>
    <div class="row" style="justify-content:flex-end;margin-top:12px">
      ${rel.length?`<button class="btn btn-ghost" style="margin-right:auto" onclick="closeModal();go('plan')">看相关工单 →</button>`:''}
      <button class="btn btn-secondary" onclick="closeModal();go('workbench')">去内容工作台</button>
      <button class="btn btn-primary" onclick="closeModal()">关闭</button></div>`);
}

/* ===================== 品牌事实库 ===================== */

function taskWbTarget(t){
  // 行动计划 → 工作台的落点解析：尽量落到「这条任务最该写的那道题」，而不是列表页
  for(const a of (t.assets||[])){const m=String(a).match(/\bq\d{3}\b/);if(m)return m[0]}   // 资产已带 qid
  const qs=demandSort((D.analytics.questions||[]).filter(q=>!q.brand_probe));
  const undone=qs.filter(q=>q.content!=='已成稿');
  const bm=(t.title||'').match(/「(定义|数字事实|对比|操作步骤|FAQ)」/);
  if(bm){
    // 块 → 最需要该块的问题分组（对应 blueprint GROUP_PLAN 的内容形态）
    const bg={'对比':['比较','替代'],'操作步骤':['场景'],'定义':['价格','风险','品牌验证'],
              '数字事实':['推荐','比较','场景'],'FAQ':['价格','风险']};
    const hit=undone.find(q=>(bg[bm[1]]||[]).includes(q.group));
    if(hit)return hit.id;
  }
  if(/英文|中英/.test(t.title||'')){const hit=undone.find(q=>q.market==='global');if(hit)return hit.id}
  return (undone[0]||qs[0]||{}).id||null;   // 兜底：选题池顶部
}

function wbFromTask(id){
  const t=(D.tasks||[]).find(x=>x.id===id);
  const wq=t?taskWbTarget(t):null;
  closeModal&&closeModal();
  go('workbench',wq?{wq}:undefined);
}

function onePager(){
  const a=D.analytics,h=a.health,w=window.open('','_blank');
  if(!w){toast('浏览器拦截了弹窗，请允许后重试','err');return}
  const subs=[['提及率',h.subs.mention],['引用份额',h.subs.cite],['阵地覆盖',h.subs.channel],['内容承接',h.subs.content],['事实一致性',h.subs.fact]];
  const open=(D.tasks||[]).filter(t=>t.status!=='done'&&t.priority==='P0');
  w.document.write(`<!doctype html><meta charset="utf-8"><title>${esc(D.brand.name)} · GEO 一页结论</title>
  <style>body{font:15px/1.7 Inter,system-ui,sans-serif;max-width:720px;margin:40px auto;padding:0 24px;color:#111}
  h1{font-size:24px}h2{font-size:16px;margin-top:28px}table{border-collapse:collapse;width:100%}
  td,th{border-bottom:1px solid #ddd;padding:8px;text-align:left;font-size:14px}
  .big{font-size:44px;font-weight:600}.muted{color:#777;font-size:12.5px}</style>
  <h1>${esc(D.brand.name)} · GEO 一页结论</h1>
  <div class="muted">数据截至 ${esc(a.latest_date||'—')} · 所有数字来自同一份问题库采样</div>
  <div class="big">${h.score==null?'—':h.score}<span style="font-size:16px;color:#777"> / 100 GEO 健康分</span></div>
  <h2>五项分项</h2><table>${subs.map(([n,v])=>`<tr><td>${n}</td><td>${v==null?'未测':(v*100).toFixed(1)+'%'}</td></tr>`).join('')}</table></div>
  <h2>本期结论</h2><p>${esc(headline()[1])}</p>
  <h2>下一步（P0）</h2><ul>${open.map(t=>`<li>${esc(t.title)} — ${esc(t.owner)}，${esc(t.effort)}</li>`).join('')||'<li>无 P0 阻塞</li>'}</ul>
  <p class="muted">GEO 提升的是被引用的概率，不承诺任何引擎一定引用某个页面。</p>`);
  w.document.close();
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

// const 箭头函数不会自动成为 window 属性，按名调用就得显式挂上
// （progBar/chanOpen 那些是 function 声明，本来就在 window 上）
window.diagTag = diagTag;
window.distRows = distRows;
