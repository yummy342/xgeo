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

async function addFact(pre){
  modal(`<h4 style="font-size:17px">记录一条事实比对</h4>
    <div class="field"><label>字段（如：适用规模 / 成立时间 / 价格）</label><input id="f-field" class="input" value="${esc(typeof pre==='string'?pre:'')}"></div>
    <div class="field"><label>AI 说的（样本原话）</label><input id="f-said" class="input"></div>
    <div class="field"><label>官方口径</label><input id="f-truth" class="input"></div>
    <div class="field"><label>状态</label><div class="seg">
      <label class="seg-opt"><input type="radio" name="fst" value="被说错" checked>被说错</label>
      <label class="seg-opt"><input type="radio" name="fst" value="缺失">缺失</label>
      <label class="seg-opt"><input type="radio" name="fst" value="一致">一致</label></div></div>
    <div class="row" style="justify-content:flex-end;margin-top:12px">
      <button class="btn btn-secondary" onclick="closeModal()">取消</button>
      <button class="btn btn-primary" onclick="saveFact()">保存</button></div>`);
}

async function saveFact(){
  const items=(D.analytics.factcheck||[]).slice();
  items.push({field:$('#f-field').value.trim(),said:$('#f-said').value.trim(),
    truth:$('#f-truth').value.trim(),state:document.querySelector('input[name=fst]:checked').value});
  const r=await post('/api/factcheck/'+SLUG,{items});
  toast(r.ok?'已记录（健康分将随之更新）':'失败',r.ok?'':'err');
  if(r.ok){closeModal();load(SLUG,true)}
}

async function delFact(i){
  const items=(D.analytics.factcheck||[]).slice();items.splice(i,1);
  await post('/api/factcheck/'+SLUG,{items});load(SLUG,true);
}

/* ===================== 阵地地图 ===================== */

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

function factModal(i){
  const c=FACT_CARDS[i];if(!c)return;
  modal(`<h4 style="font-size:17px">${esc(c.field)}</h4>
    <div style="font-size:12px;color:var(--t600);margin:10px 0 3px">官方口径（你希望 AI 这么说）</div>
    <div style="font-size:13.5px;line-height:1.6">${esc(c.value)}</div>
    <div style="font-size:12px;color:var(--t600);margin:12px 0 3px">AI 当前说法 ${c.ai.state?`<span class="tag ${c.ai.state==='一致'?'pill-good':'tag-accent'}" style="font-size:10px">${c.ai.state}</span>`:'<span class="tag tag-dim" style="font-size:10px">未比对</span>'}</div>
    <div style="font-size:13px;line-height:1.6;color:var(--t400)">${esc(c.ai.txt)}</div>
    <p class="muted" style="font-size:11.5px;margin-top:10px">「AI 当前说法」来自「引擎表现 → 样本回放」的真实回答。人工比对后记一条，「事实一致性」才会进健康分。</p>
    <div class="row" style="justify-content:flex-end;margin-top:14px">
      <button class="btn btn-ghost" style="margin-right:auto" onclick="closeModal();editFactsSrc()">编辑口径（源文件）</button>
      <button class="btn btn-secondary" onclick="closeModal()">关闭</button>
      <button class="btn btn-primary" onclick="closeModal();addFact(${esc(JSON.stringify(c.field))})">记一条比对</button></div>`);
}

async function editFactsSrc(){
  const f=await api('/api/facts/'+SLUG);
  modal(`<h4 style="font-size:17px">品牌事实卡 · 源文件</h4>
    <p class="muted" style="font-size:12px">Markdown。每条事实标证据等级 A–E；没来源的标「待确认」，不许编。保存后点「重新生成」同步到资产。</p>
    <textarea id="factsrc" class="input" rows="20">${esc(f.text||'')}</textarea>
    <div class="row" style="justify-content:flex-end;margin-top:12px">
      <button class="btn btn-secondary" onclick="closeModal()">取消</button>
      <button class="btn btn-primary" onclick="saveFactsSrc()">保存</button></div>`);
}

async function saveFactsSrc(){
  const r=await post('/api/facts/'+SLUG,{text:$('#factsrc').value});
  toast(r.ok?'已保存':'失败',r.ok?'':'err'); if(r.ok){closeModal();load(SLUG,true)}
}

/* ===================== 行动计划 ===================== */

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

function taskModal(id){
  const t=(D.tasks||[]).find(x=>x.id===id);
  if(!t)return;
  const acc=t.acceptance||{};
  const ev=(t.evidence||[]).slice(-3).reverse();
  modal(`<h4 style="font-size:17px">${esc(t.id)} · ${esc(t.title)}</h4>
    <div class="row" style="gap:6px;margin-top:6px">
      <span class="tag ${t.priority==='P0'?'tag-accent':'tag-neutral'}">${t.priority}</span>
      <span class="tag tag-outline">${esc(t.package)}</span>
      ${t.risk?`<span class="tag ${t.risk==='high'?'tag-accent':'tag-dim'}">${({low:'低风险',watch:'需观察',high:'高风险'})[t.risk]}</span>`:''}
      <span style="font-size:11.5px;color:var(--t600)">负责：${esc(t.owner)} · 工作量 ${esc(t.effort)} · 窗口 ${esc(t.window||'—')} · ${mktLabel(t.market)}</span></div>
    <div style="font-size:12px;color:var(--t600);margin:12px 0 3px">为什么做</div>
    <div style="font-size:13px;line-height:1.6;color:var(--t400)">${esc(t.why||'—')}</div>
    <div style="font-size:12px;color:var(--t600);margin:12px 0 3px">具体怎么干</div>
    <div style="font-size:13px;line-height:1.6">${esc(t.action||'—')}</div>
    <div style="font-size:12px;color:var(--t600);margin:12px 0 3px">怎么算做完（${acc.type==='auto'?'自动验收——重抓/采样后系统判定，不靠人说':'人工验收'}）</div>
    <div style="font-size:13px;line-height:1.6">${esc(acc.desc||'—')}${acc.check?`<div class="muted" style="font-size:11.5px;margin-top:2px">检查器：<code>${esc(acc.check)}</code></div>`:''}</div>
    ${progBar(t.progress,t.progress_first)}
    ${(t.affected||[]).length?`<div style="font-size:12px;color:var(--t600);margin:12px 0 3px">受影响页面（${t.affected.length}）</div>
      <div style="max-height:120px;overflow:auto;font-size:11.5px;line-height:1.7;color:var(--t500)">${t.affected.slice(0,20).map(u=>`<div style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(u)}</div>`).join('')}${t.affected.length>20?`<div class="muted">…共 ${t.affected.length} 个</div>`:''}</div>`:''}
    ${ev.length?`<div style="font-size:12px;color:var(--t600);margin:12px 0 3px">最近验收记录</div>
      ${ev.map(e=>`<div style="font-size:11.5px;color:var(--t500);padding:2px 0">${esc((e.at||'').slice(0,16).replace('T',' '))} · ${({pass:'✓ 通过',fail:'✗ 未达标',manual:'待人工'})[e.result]||esc(e.result)} · ${esc(e.note||'')}</div>`).join('')}`:''}
    <div class="row" style="justify-content:flex-end;margin-top:14px">
      ${t.package==='内容矩阵'?`<button class="btn btn-secondary" style="margin-right:auto" onclick="wbFromTask(${esc(JSON.stringify(t.id))})">去内容工作台</button>`:''}
      <button class="btn btn-primary" onclick="closeModal()">关闭</button></div>`);
}

async function setTask(id,status){
  const r=await post('/api/task',{slug:SLUG,id,status});
  if(!r.ok){toast(r.error||'失败','err');return}
  const t=(D.tasks||[]).find(x=>x.id===id);if(t)t.status=status;render();
}

/* ===================== 内容工作台 ===================== */

function pendPubModal(){
  const cp=D.content_pub||[];
  modal(`<h4 style="font-size:17px">成稿发布状态</h4>
    <p class="muted" style="font-size:12px;margin-top:4px">每篇成稿逐一发布；已发布的显示渠道与链接。改完稿要重新发布才会更新渠道上的内容。</p>
    <div style="max-height:340px;overflow:auto">
    ${cp.map(f=>{const pubs=f.published||[];return `<div style="padding:9px 0;box-shadow:inset 0 -1px 0 var(--line)">
      <div class="row">
        <div style="flex:1;min-width:0">
          <div style="font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(f.path)}">${esc(f.title)}</div>
          <div style="font-size:11px;color:var(--t600)">${esc(f.path)}${f.qids.length?' · 承接 '+f.qids.map(esc).join('/'):''}</div>
          ${pubs.map(p=>`<div style="font-size:11px;color:var(--t500)">✓ ${esc(p.platform_name)} ${esc((p.at||'').slice(0,10))} ${p.url?`<a href="${esc(p.url)}" target="_blank" style="color:var(--a300)">${esc(p.url.slice(0,40))}</a>`:''}</div>`).join('')}
        </div>
        <button class="btn ${pubs.length?'btn-ghost':'btn-primary'}" style="flex:none;font-size:12px"
          onclick="closeModal();pubModal(${esc(JSON.stringify('content/'+f.path))})">${pubs.length?'再发布':'发布'}</button>
      </div></div>`}).join('')||'<div class="muted">还没有成稿——先到内容工作台写</div>'}
    </div>
    <div class="row" style="justify-content:flex-end;margin-top:12px">
      <button class="btn btn-secondary" onclick="closeModal()">关闭</button></div>`);
}

async function pubModal(rel){
  // rel 缺省时取工作台当前成稿——同一个弹窗也被行动计划的「待发布清单」逐篇调用
  if(!rel){
    if(!WB.cur||WB.cur.kind!=='content'){toast('先切到成稿再发布','err');return}
    rel='content/'+WB.cur.path;
  }
  if(!PUB)PUB=await api('/api/publish/'+SLUG);
  const pubs=(PUB&&PUB.publishers)||[];
  const okRecs=((PUB&&PUB.records)||[]).filter(r=>r.path===rel&&r.ok);
  const lastOf=code=>okRecs.filter(r=>r.platform===code).slice(-1)[0];
  // 记住上次勾选的渠道组合：同一批文章通常发同一组渠道
  let sel=[];try{sel=JSON.parse(localStorage.getItem('pubSel:'+SLUG)||'[]')}catch(e){}
  modal(`<h4 style="font-size:17px">发布到渠道</h4>
    <p class="muted" style="font-size:12px;margin-top:4px">文件：${esc(rel)}。勾选要发布的渠道——只发这一篇；公众号 / WordPress 只建草稿，到各自后台确认后才对外。</p>
    ${pubs.map(x=>{const ok=!x.missing.length,done=lastOf(x.code);
      return `<label class="row" style="padding:7px 0;box-shadow:inset 0 -1px 0 var(--line);cursor:${ok?'pointer':'default'};${ok?'':'opacity:.55'}">
      <input type="checkbox" class="pub-ch" value="${x.code}" ${ok?'':'disabled'} ${ok&&sel.includes(x.code)?'checked':''} style="accent-color:var(--accent)">
      <span style="flex:1;font-size:13px">${esc(x.name)}<span class="muted" style="font-size:11px;margin-left:6px">${esc(x.note)}</span></span>
      ${done?`<span style="font-size:11px;color:var(--a300)" title="${esc(done.url||'')}">✓ 已发 ${esc((done.at||'').slice(5,10))}</span>`:''}
      ${ok?'':`<button class="btn btn-ghost" style="font-size:11.5px;padding:2px 8px" onclick="closeModal();go('publishing')">缺凭证 · 去配置</button>`}
    </label>`}).join('')}
    <div id="pubprog" style="margin-top:8px"></div>
    <div class="row" style="justify-content:flex-end;margin-top:12px">
      <button class="btn btn-ghost" style="margin-right:auto" onclick="closeModal();go('publishing')">渠道配置</button>
      <button class="btn btn-secondary" onclick="closeModal()">关闭</button>
      <button class="btn btn-primary" onclick="doPublishSel(${esc(JSON.stringify(rel))})">发布到已选渠道</button></div>`);
}

async function doPublishSel(rel){
  const codes=[...document.querySelectorAll('.pub-ch:checked')].map(e=>e.value);
  if(!codes.length){toast('先勾选至少一个渠道（没有可勾的先去设置配凭证）','err');return}
  localStorage.setItem('pubSel:'+SLUG,JSON.stringify(codes));
  const names=codes.map(c=>((PUB&&PUB.publishers)||[]).find(x=>x.code===c)?.name||c);
  if(!confirm(`发布「${rel}」到 ${codes.length} 个渠道：${names.join('、')}\n\n公众号/WordPress 只建草稿。确认？`))return;
  const prog=$('#pubprog');let okN=0;
  for(let i=0;i<codes.length;i++){
    const line=document.createElement('div');
    line.style.cssText='font-size:12px;padding:3px 0;color:var(--t400)';
    line.textContent=`→ ${names[i]} 发布中…`;prog.appendChild(line);
    const r=await post('/api/publish/'+SLUG,{platform:codes[i],path:rel});
    if(r.ok){okN++;line.innerHTML=`✓ ${esc(names[i])} 已发布 ${r.url?`<a href="${esc(r.url)}" target="_blank" style="color:var(--a300)">${esc(r.url.slice(0,50))}</a>`:esc(r.note||'')}`}
    else line.innerHTML=`<span style="color:var(--accent)">✗ ${esc(names[i])} 失败：${esc(r.error||'')}</span>`;
  }
  toast(okN===codes.length?`已发布到 ${okN} 个渠道`:`${okN}/${codes.length} 个渠道成功，失败的看弹窗明细`,okN===codes.length?'':'err');
  PUB=null;await load(SLUG,true);   // 刷新 content_pub：计划页/问题库/清单状态同步，弹窗保留结果明细
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

async function switchModal(){
  const ps=await api('/api/projects');
  if(!Array.isArray(ps)||!ps.length){go('onboard',{obStep:1});return}
  modal(`<h4 style="font-size:17px">切换品牌</h4>
    <div style="margin-top:8px">
    ${ps.map(p=>`<div class="row" style="gap:10px;padding:10px 8px;cursor:pointer;border-radius:var(--r-md);box-shadow:inset 0 -1px 0 var(--line)"
        onmouseover="this.style.background='var(--deep)'" onmouseout="this.style.background=''"
        onclick="closeModal();${p.slug===SLUG?'':'switchProject('+esc(JSON.stringify(p.slug))+')'}">
      <span style="flex:1;font-size:13.5px">${esc(p.name)}${p.slug===SLUG?' <span class="tag tag-accent" style="font-size:10px">当前</span>':''}</span>
      <span class="muted" style="font-size:11.5px">${esc((p.site||'').replace(/^https?:\/\//,''))}</span>
      <span class="muted" style="font-size:11.5px;width:70px;text-align:right">体检 ${p.avg_score==null?'—':p.avg_score}</span>
    </div>`).join('')}
    </div>
    <div class="row" style="justify-content:flex-end;margin-top:12px">
      <button class="btn btn-secondary" onclick="closeModal();go('onboard',{obStep:1})">+ 接入新品牌</button>
      <button class="btn btn-primary" onclick="closeModal()">关闭</button></div>`);
}

async function switchProject(slug){KEYS=null;PROJECTS=null;SET_CFG=null;PUB=null;AS={tree:null,cur:null,text:''};
  WB={qid:null,sources:[],cur:null,text:'',check:null,q:null};ST.engSel=null;
  await load(slug);go('overview')}

async function editConfig(){
  const cfg=await api('/api/config/'+SLUG);const b=cfg.brand||{};
  modal(`<h4 style="font-size:17px">品牌配置</h4>
    <div class="field"><label>品牌名</label><input id="c-name" class="input" value="${esc(b.name||'')}"></div>
    <div class="field"><label>别名（顿号分隔——漏别名会低估提及率）</label><input id="c-alias" class="input" value="${esc((b.aliases||[]).join('、'))}"></div>
    <div class="field"><label>竞品（顿号分隔——它是排名指标的分母）</label><input id="c-comp" class="input" value="${esc((cfg.competitors||[]).map(c=>c.name).join('、'))}"></div>
    <div class="field"><label>市场</label><div class="seg">
      ${['cn','global','both'].map(m=>`<label class="seg-opt"><input type="radio" name="cmkt" value="${m}" ${cfg.market===m?'checked':''}>${({cn:'国内',global:'海外',both:'两者都要'})[m]}</label>`).join('')}</div></div>
    <div class="row" style="justify-content:flex-end;margin-top:12px">
      <button class="btn btn-secondary" onclick="closeModal()">取消</button>
      <button class="btn btn-primary" onclick="saveCfg()">保存</button></div>`);
}

async function saveCfg(){
  const cfg=await api('/api/config/'+SLUG);
  const sp=v=>v.split(/[、,，]/).map(s=>s.trim()).filter(Boolean);
  cfg.brand.name=$('#c-name').value.trim();
  cfg.brand.aliases=sp($('#c-alias').value);
  const old={};(cfg.competitors||[]).forEach(c=>old[c.name]=c);
  cfg.competitors=sp($('#c-comp').value).map(n=>old[n]||{name:n,aliases:[],market:cfg.market==='global'?'global':'cn'});
  cfg.market=document.querySelector('input[name=cmkt]:checked').value;
  if(cfg.bootstrap)cfg.bootstrap.needs_review=false;
  const r=await post('/api/config/'+SLUG,cfg);
  toast(r.ok?'已保存':'失败',r.ok?'':'err');if(r.ok){closeModal();load(SLUG,true)}
}

function editKey(i){
  const k=KEYS[i];
  modal(`<h4 style="font-size:17px">${esc(k.label)}</h4>
    ${k.note?`<p class="muted" style="font-size:12px;margin:4px 0 0">${esc(k.note)}</p>`:''}
    <div class="field"><label>API Key（${esc(k.env)}${k.ok===true?'，已配置'+(k.key_tail?'，尾号 '+k.key_tail:''):''}）</label>
      <input id="k-key" class="input" type="password" autocomplete="off"
        placeholder="${k.ok===true?'留空则保持现有 Key 不变':'粘贴 API Key'}"></div>
    ${k.model_env?`<div class="field"><label>模型（${esc(k.model_env)}，留空用默认）</label>
      <input id="k-model" class="input" value="${k.model_set?esc(k.model):''}" placeholder="${esc(k.model)}"></div>`:''}
    <div class="row" style="justify-content:flex-end;margin-top:12px">
      ${k.ok===true?`<button class="btn btn-ghost" style="margin-right:auto" onclick="if(confirm('确定从 .env 删除 ${esc(k.env)}？'))saveKey(${i},true)">清除 Key</button>`:''}
      <button class="btn btn-secondary" onclick="closeModal()">取消</button>
      <button class="btn btn-primary" onclick="saveKey(${i})">保存</button></div>`);
}

async function saveKey(i,clear){
  const k=KEYS[i],u={};
  if(clear)u[k.env]='';
  else{const v=$('#k-key').value.trim();if(v)u[k.env]=v}
  if(k.model_env&&!clear){
    const m=$('#k-model').value.trim();
    if(m!==(k.model_set?k.model:''))u[k.model_env]=m;
  }
  if(!Object.keys(u).length){closeModal();return}
  const r=await post('/api/keys',{updates:u});
  toast(r.ok?'已写入 .env':'失败：'+(r.error||''),r.ok?'':'err');
  if(r.ok){closeModal();KEYS=null;render()}
}

/* ===================== 接入引导 ===================== */

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

function auditFlag(i){
  // 站点体检顶部卡片的联动：robots/sitemap 直接看源文件，UA 实测跳相关工单，
  // llms.txt 去部署资产，页面可访问定位到问题页列表，语言覆盖跳相关工单
  const site=(D.brand.site||'').replace(/\/$/,'');
  const byCheck=rx=>{const t=(D.tasks||[]).find(x=>rx.test((x.acceptance||{}).check||''));if(t)taskModal(t.id);else go('plan')};
  if(i===0&&site)window.open(site+'/robots.txt','_blank');
  else if(i===1)byCheck(/^site\.no_ai_ua_block/);
  else if(i===2&&site)window.open(site+'/sitemap.xml','_blank');
  else if(i===3)go('assets',{assetSel:'llms.txt'});
  else if(i===4){const el=document.querySelector('#audit-pages');if(el)el.scrollIntoView({block:'start'})}
  else if(i===5)byCheck(/^site\.(en_pages_gte|lang_balance)/);
}

/* ===================== 部署资产 ===================== */

let SMP=null,SMPF={date:'',platform:'',flag:''};

async function loadSamples(){
  const q=new URLSearchParams({date:SMPF.date,platform:SMPF.platform,flag:SMPF.flag,limit:'300'});
  SMP=await api(`/api/samples/${SLUG}?${q}`);
  render();
}

async function sampleModal(key){
  const r=await api(`/api/sample/${SLUG}?key=${encodeURIComponent(key)}`);
  if(!r||r.error){toast('读取失败','err');return}
  const a=r.analysis||{},cites=r.citations||[];
  modal(`<h4 style="font-size:16px">${esc(r.question||'')}</h4>
    <div class="row" style="gap:6px;margin-top:6px;flex-wrap:wrap">
      <span class="tag tag-outline">${esc(r.platform_name||r.platform)}</span>
      <span class="tag tag-dim">${esc(r.date||'')}</span>
      <span class="tag tag-dim">${esc(r.evidence_level||'')}</span>
      ${r.session_label?`<span class="tag tag-outline" title="采样环境——不同环境的样本不该混在一起算平均">${esc(r.session_label)}</span>`:''}
      ${r.manual_override?'<span class="tag tag-accent">已人工核对</span>':''}
      <span style="font-size:11.5px;color:var(--t600)">${esc(r.terminal||'')} · ${esc(r.sample_mode||'')} · ${(r.answer||'').length} 字</span></div>
    <div style="font-size:12px;color:var(--t600);margin:12px 0 3px">答案原文</div>
    <div style="max-height:210px;overflow:auto;background:var(--deep);border-radius:8px;padding:10px 12px;font-size:12.5px;line-height:1.65;white-space:pre-wrap;color:var(--t400)">${esc(r.answer||'')}</div>
    ${cites.length?(()=>{
      // 源站构成：这条答案的引用都来自哪些域名、各占多少——占比高的就是该题的主导信源
      const dom={};cites.forEach(c=>{try{const h=new URL(c.url).hostname.replace(/^www\./,'');dom[h]=(dom[h]||0)+1}catch(e){}});
      const own=((D.brand&&D.brand.site)||'').replace(/^https?:\/\//,'').replace(/^www\./,'').split('/')[0];
      const rows=Object.entries(dom).sort((a,b)=>b[1]-a[1]);
      return `<div style="font-size:12px;color:var(--t600);margin:12px 0 3px">引用（${cites.length}）· 源站构成</div>
      <div class="row" style="gap:5px;flex-wrap:wrap;margin-bottom:6px">
        ${rows.map(([h,n])=>{const mine=own&&(h===own||h.endsWith('.'+own));
          return `<span class="tag ${mine?'tag-accent':'tag-dim'}" style="font-size:11px" title="${mine?'你的官网':''}">${esc(h)} ×${n} · ${Math.round(n/cites.length*100)}%</span>`}).join('')}
      </div>
      <div style="max-height:110px;overflow:auto;font-size:11.5px;line-height:1.7">
        ${cites.map(c=>`<div style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap"><a href="${esc(c.url)}" target="_blank" style="color:var(--a300)">${esc(c.url)}</a> <span style="color:var(--t600)">${esc(c.title||'')}</span></div>`).join('')}</div>`})():''}
    <div style="font-size:12px;color:var(--t600);margin:14px 0 4px">人工复核（改完立刻重算当日指标）</div>
    <div class="row" style="gap:8px;flex-wrap:wrap">
      <label class="small">品牌被提及
        <select id="sm-men" style="background:var(--deep);color:var(--text);border:1px solid #3f424d;border-radius:6px;padding:4px 8px;font:inherit;margin-left:4px">
          <option value="1" ${a.brand_mentioned?'selected':''}>是</option>
          <option value="0" ${a.brand_mentioned?'':'selected'}>否</option></select></label>
      <label class="small">位次 <input id="sm-rank" class="input" style="width:64px;display:inline-block;padding:4px 8px" value="${a.brand_rank||0}"></label>
      <label class="small" style="flex:1;min-width:220px">竞品（顿号分隔）
        <input id="sm-comp" class="input" style="padding:4px 8px" value="${esc((a.competitors_mentioned||[]).join('、'))}"></label>
    </div>
    <div class="field" style="margin-top:8px"><label>复核备注</label>
      <input id="sm-note" class="input" value="${esc(r.review_note||'')}" placeholder="例：品牌名撞词，实际未提及"></div>
    ${(a.negative_cues||[]).length?`<div class="small" style="color:var(--a300);margin-top:4px">负面线索词：${esc(a.negative_cues.join('、'))}——请人工判断是否真的负面</div>`:''}
    <div class="row" style="justify-content:flex-end;margin-top:14px">
      <button class="btn btn-ghost" style="margin-right:auto;color:var(--t500)" onclick="delSample(${esc(JSON.stringify(key))})">删除此样本</button>
      ${r.needs_review?`<button class="btn btn-secondary" onclick="saveSample(${esc(JSON.stringify(key))},true)">标记已复核</button>`:''}
      <button class="btn btn-secondary" onclick="closeModal()">取消</button>
      <button class="btn btn-primary" onclick="saveSample(${esc(JSON.stringify(key))})">保存</button></div>`);
}

async function saveSample(key,clearReview){
  const comp=($('#sm-comp').value||'').split(/[、,，]/).map(s=>s.trim()).filter(Boolean);
  const patch={brand_mentioned:$('#sm-men').value==='1',brand_rank:parseInt($('#sm-rank').value||'0',10)||0,
    competitors_mentioned:comp,review_note:$('#sm-note').value.trim()};
  if(clearReview)patch.needs_review=false;
  const r=await post('/api/sample/'+SLUG,{key,patch});
  if(!r.ok){toast(r.error||'保存失败','err');return}
  toast('已保存，当日指标已重算');closeModal();SMP=null;await load(SLUG,true);loadSamples();
}

async function delSample(key){
  if(!confirm('删除这条样本？当日指标会重算，且不可恢复。'))return;
  const r=await post('/api/sample/'+SLUG,{key,patch:{delete:true}});
  if(!r.ok){toast(r.error||'删除失败','err');return}
  toast('已删除，指标已重算');closeModal();SMP=null;await load(SLUG,true);loadSamples();
}

/* ===================== 框架 ===================== */


// 新壳的侧栏复用这三者（普通脚本的 const 不挂 window，必须显式导出）
window.GL_NAV = NAV;
window.GL_BADGE = badge;
window.GL_ULANG = ULANG;

// const 箭头函数不会自动成为 window 属性，按名调用就得显式挂上
// （progBar/chanOpen 那些是 function 声明，本来就在 window 上）
window.diagTag = diagTag;
window.distRows = distRows;
