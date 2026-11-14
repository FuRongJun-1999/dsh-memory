(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const json = value => JSON.stringify(value, null, 2);
  const pages = [ ['overview','◈','概览'], ['memory','▤','记忆'], ['goals','◎','目标与任务'], ['self','◇','自我认知'], ['space','◷','时空关系'], ['review','☷','审核与维护'], ['tools','⌘','工具台'] ];
  const layers = { knowledge:'知识', contextual:'情景', structural:'结构', anchor:'锚点', self:'自我', rejected:'否证', unresolved:'待定' };
  let meta = null, info = null, page = 'overview', generation = 0, chosen = 'cg', toolsFilter = '', toastTimer;
  const safeRead = new Set(['info','read','route','help','edges','status']);
  const readActions = {goal:['list'],task:['list','get','find','session'],recent:['list'],identity:['profile'],self_state:['snapshot'],metacognition:['report'],review:['list','records'],protect:['stats'],evolution:['summary'],sustain:['status'],maintain:['stat'],ref:['stat'],theory:['check'],link:['ls'],whitebox:['ping']};
  function needsConfirm(tool, args) {
    if (tool === 'stg') return !['relation','timeline','anchors','consistency','state_chain'].includes(args.op) || ['content','text','goal','set','apply','write','force','override','auto_flywheel'].some(k=>args[k]!==undefined);
    if (tool === 'cg') return !(safeRead.has(args.op) || (readActions[args.op]?.includes(args.action) && !['content','text','goal','set','apply','write','force','override','auto_flywheel'].some(k => args[k] !== undefined)));
    return !['mdcg_recall','mdcg_search','mdcg_get','mdcg_review_list','mdcg_review_records','mdcg_forgetting_history','mdcg_health','mdcg_whoami','mdcg_service_info','mdcg_rejected','mdcg_unresolved','mdcg_watermarks'].includes(tool);
  }
  async function fetchJSON(url, options = {}) {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 70000);
    try {
      // issue #925：调用方的 signal 曾被这里**覆盖**（展开 options 后又赋值 signal）⇒「取消」只中止了
      // 内部 controller，交给 fetch 的仍是它自己那条。两条都要能中止，故合并而非覆盖。
      const signal = options.signal ? AbortSignal.any([controller.signal, options.signal]) : controller.signal;
      const response = await fetch(url, { credentials:'same-origin', ...options, signal });
      const text = await response.text(); let value;
      try { value = JSON.parse(text); } catch { throw new Error(response.status === 401 ? '登录已过期，请返回 DSH 登录后重试。' : '服务器未返回 JSON，请检查插件是否已加载。'); }
      if (!response.ok) throw new Error(value.error || `请求失败 (${response.status})`);
      return value;
    } catch (e) { if (e.name === 'AbortError') throw new Error('等待超时；操作可能仍在后台进行，请检查结果，不要重复提交。'); throw e; }
    finally { clearTimeout(timeout); }
  }
  async function confirm(tool, args) {
    $('confirm-body').textContent = json({ tool, args });
    const dialog = $('confirm'); dialog.returnValue = ''; dialog.showModal();
    return new Promise(resolve => dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), { once:true }));
  }
  async function call(tool, args, options = {}) {
    const interactive = options.interactive === true
    if (!meta?.csrf) throw new Error('灵枢未连接，请刷新后重试。');
    const mutating = needsConfirm(tool,args);
    if (mutating && (!interactive || !await confirm(tool,args))) throw new Error('已取消操作');
    const response = await fetchJSON('/plugins/lingshu/call', { method:'POST', signal:options.signal, headers:{'Content-Type':'application/json','X-Lingshu-CSRF':meta.csrf}, body:JSON.stringify({tool,args,confirm:mutating}) });
    return response.result;
  }
  function toast(text) { $('toast').textContent=text; $('toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').hidden=true,4000); }
  // ---- 客户端缓存（issue #UI-PERF）：同参数 60s 内复用，切页/来回切换不再重复取数 ----
  const CACHE_TTL=60000, cacheMap=new Map()
  function cacheGet(key){ const hit=cacheMap.get(key); if(!hit)return null; if(Date.now()-hit.t>CACHE_TTL){cacheMap.delete(key);return null} return hit.v }
  function cacheSet(key,value){ cacheMap.set(key,{t:Date.now(),v:value}); if(cacheMap.size>120){ const first=cacheMap.keys().next().value; cacheMap.delete(first) } }

  function time(ts) { if (!ts) return '—'; const d = new Date(typeof ts==='number'?ts*1000:ts); return Number.isNaN(d.getTime()) ? String(ts) : d.toLocaleDateString('zh-CN',{month:'2-digit',day:'2-digit'})+' '+d.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'}); }
  function title(name, en, subtitle, action='') { return `<div class="title-row"><div><div class="eyebrow">${en}</div><h1>${name}</h1><p class="subtitle">${subtitle}</p></div>${action}</div>`; }
  function loading() { return '<div class="loading">正在读取认知图</div>'; }
  function errorHTML(error) { return `<div class="notice error">${esc(error.message || error)}</div>`; }
  function nodeRows(items, events=false) {
    if (!items?.length) return '<div class="empty">这里还没有记录。<br>认知从一次真实的记录开始。</div>';
    return items.map(item => { const n=item.node || item, fm=n.frontmatter || {}; const id=n.id || n.node_id; const preview=n.preview || n.content || n.text || n.goal || n.title || n.name || json(n);
      return `<${id?'button':'div'} ${id?`type="button" data-node="${esc(id)}"`:''} class="row-item ${id?'node-button':''}">${events?`<span class="feed-time">${esc(time(n.start || n.t || n.ts || fm.created_at))}</span>`:'<span class="row-dot"></span>'}<div class="row-content"><div class="row-title">${esc(String(preview).slice(0,220))}</div><div class="row-meta"><span class="badge">${esc(layers[n.layer||fm.layer] || n.layer || fm.layer || n.role || fm.role || '记录')}</span><span>${esc(time(n.start||n.t||n.ts||fm.created_at))}</span>${id?`<span>${esc(id)}</span>`:''}${item.state?`<span>${esc(item.state)}</span>`:''}</div></div></${id?'button':'div'}>`;
    }).join('');
  }
  function bindNodes(root=$('main')) { root.querySelectorAll('[data-node]').forEach(button=>button.addEventListener('click',async()=> { $('detail-body').textContent='正在读取…'; $('detail').showModal(); try { const r=await call('cg',{op:'read',node_id:button.dataset.node}); $('detail-body').textContent=r===null?'节点不存在、不可见或已删除。':json(r); } catch(e) { $('detail-body').textContent=e.message; } })); }
  const ROW_KEYS = ['items','results','goals','tasks','records','events','nodes','pack','subjects','pending','hits','issues','by_layer','entries','protected_ids']
  function rowsOf(value) { if (Array.isArray(value)) return value; if (!value || typeof value!=='object') return [];
    for(const key of ROW_KEYS) if(Array.isArray(value[key])) return value[key];
    // 兜底：形状未登记的新 op 也尽量出列表（取第一个数组值），避免「有数据却显示空」
    for(const key of Object.keys(value)) if(Array.isArray(value[key])) return value[key];
    return []; }
  function renderResult(value, target='result') {
    const el=$(target); if(!el)return;
    el.innerHTML=`<div class="panel"><div class="panel-body"><div class="result-head"><h3>调用结果</h3><button id="copy-result" class="button">复制 JSON</button></div>${value?.error?`<div class="notice error">${esc(value.error)}</div>`:''}${value?.verdict||value?.moved_to||value?.committed===false?`<div class="notice">${esc(value.verdict||'未直接提交')}${value.moved_to?' · '+esc(value.moved_to):''}${value.pid?' · 审核 '+esc(value.pid):''}。以下为真实回执，不代表全部已落盘。</div>`:''}<pre id="result-json"></pre></div></div>`;
    $('result-json').textContent = typeof value==='string'?value:json(value);
    $('copy-result').onclick=async()=> { try { await navigator.clipboard.writeText($('result-json').textContent); toast('已复制'); } catch { toast('无法访问剪贴板，可直接选中结果复制。'); } };
  }
  // ---- 人类可读渲染（issue #UI-MD）：自我认知 / 审核与维护 不再直接甩 JSON ----
  // 原则：只显示核心内容；按「时间→会话」分组；原始回执折叠在 <details>（不隐藏、不篡改）。
  const CARD=(title,body,badge="")=>`<section class="panel"><div class="panel-head"><h3>${esc(title)}</h3>${badge?`<span class="badge">${esc(badge)}</span>`:""}</div>${body}</section>`
  const KV=rows=>rows.length?`<div class="panel-body">${rows.map(([k,v])=>`<div class="status-line"><span>${esc(k)}</span><span>${esc(v)}</span></div>`).join("")}</div>`:'<div class="empty">暂无数据。</div>'
  const EMPTY=msg=>`<div class="empty">${esc(msg)}</div>`
  function dayOf(ts){ if(!ts)return '未知时间'; const d=new Date(typeof ts==='number'?ts*1000:ts); if(Number.isNaN(d.getTime()))return '未知时间'
    const t=new Date(), same=(a,b)=>a.getFullYear()===b.getFullYear()&&a.getMonth()===b.getMonth()&&a.getDate()===b.getDate()
    if(same(d,t))return '今天'; if(same(d,new Date(t.getTime()-86400000)))return '昨天'
    return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0') }
  function sessOf(item){ const s=String(item?.session||item?.meta?.session||'未归属会话'); return s.length>18?s.slice(0,18)+'…':s }
  // 按「时间（今天/昨天/日期）→ 会话」两级分组，只显示核心内容
  function groupFeed(items){
    const hasTime=(items||[]).some(it=>it&&(it.t||it.ts||it.created_at))
    if(!hasTime) return plainFeed(items)
    if(!items?.length) return EMPTY('这里还没有记录。')
    const byDay=new Map()
    for(const it of items){ const d=dayOf(it?.t||it?.ts||it?.created_at); if(!byDay.has(d))byDay.set(d,[]); byDay.get(d).push(it) }
    return [...byDay.entries()].map(([day,list])=>{
      const bySess=new Map()
      for(const it of list){ const s=sessOf(it); if(!bySess.has(s))bySess.set(s,[]); bySess.get(s).push(it) }
      const body=[...bySess.entries()].map(([sess,arr])=>`<div class="panel-body"><div class="eyebrow">会话 ${esc(sess)}</div><div style="margin-top:10px">${arr.slice(0,30).map(it=>{
        const core=String(it?.content??it?.text??it?.goal??it?.preview??'').replace(/\s+/g,' ').trim().slice(0,200)
        const layer=layers[it?.layer]||it?.layer||''
        return `<div class="row-item"><span class="feed-time">${esc(time(it?.t||it?.ts||it?.created_at))}</span><div class="row-content"><div class="row-title">${esc(core||'（空）')}</div><div class="row-meta">${layer?`<span class="badge">${esc(layer)}</span>`:''}${it?.pid?`<span>${esc(String(it.pid).slice(0,14))}</span>`:''}</div></div></div>`}).join('')}</div></div>`).join('')
      return `<section class="panel"><div class="panel-head"><h3>${esc(day)}</h3><span class="count">${list.length} 条</span></div>${body}</section>`
    }).join('')
  }
  // 主体标识人话化：self:lingshu → 「自我主体 · 灵枢」（不把内部 ID 端给使用者）
  const SUBJ_KIND={self:'自我主体',user:'使用者',role:'角色',agent:'代理',other:'其它'}
  // 展示名优先取锚点正文里的「身份=X」（数据在，不硬编码）；取不到才退回 ID 末段。
  function displayNameFromAnchor(anchorText){
    const m=String(anchorText||'').match(/身份\s*[=＝]\s*([^;；,，、\n]{1,20})/)
    return m?m[1].trim():''
  }
  // 人话状态值：不认识/空 一律「未登记」，不把英文枚举端给使用者。
  const HUMAN_STATE={unknown:'未登记',unassigned:'未归属',none:'无'}
  function humanState(v){ if(v===undefined||v===null||v==='')return '未登记'; return HUMAN_STATE[String(v)]||String(v) }
  function humanSubject(id){
    const s=String(id||'')
    const i=s.indexOf(':')
    if(i<0) return {name:s,kind:'',label:s||'未命名主体'}
    const kind=s.slice(0,i), name=s.slice(i+1)
    const k=SUBJ_KIND[kind]||kind
    return {name,kind,label:name?(k?k+' · '+name:name):(k||'未命名主体')}
  }
  // 无时间字段的面（身份、统计）平铺：不编造「未知时间」分组
  function plainFeed(items){
    if(!items?.length) return EMPTY('这里还没有记录。')
    const bySess=new Map()
    for(const it of items){ const s=sessOf(it); if(!bySess.has(s))bySess.set(s,[]); bySess.get(s).push(it) }
    return [...bySess.entries()].map(([sess,arr])=>`<section class="panel"><div class="panel-head"><h3>${esc(sess)}</h3><span class="count">${arr.length} 条</span></div><div class="panel-body"><div style="margin-top:6px">${arr.map(it=>{
      const core=String(it?.content??it?.text??it?.label??it?.goal??'').replace(/\s+/g,' ').trim().slice(0,300)
      return `<div class="row-item"><span class="row-dot"></span><div class="row-content"><div class="row-title">${esc(core||'（空）')}</div></div></div>`}).join('')}</div></div></section>`).join('')
  }

  // 通用价值观（不变层）：真源 = docs/theory/智能论3.4.md §2.1（本处只**引用**，不改写）；
  // 守卫 test/ui-identity-human.test.ts 的 S4 断言这段原文仍在该文档里（防双副本漂移）。
  const UNIVERSAL_VALUES={
    quote:'通过熵管理维持自身结构完整，在适当条件下缩小或扩大信息差，以建立并维持值得信任的协作关系。',
    first_law:'保持对未知的好奇。',
    note:'好奇不是无条件的第一性；真正的第一性是「存在受到威胁的感知」，它决定是否开始行动。',
    test:'关键判定：该行为是否支持熵管理？是否维持了值得信任的协作关系？',
    source:'智能论 3.4 §2.1 通用价值观（不变层）',
  }
  function universalValuesCard(){
    const v=UNIVERSAL_VALUES
    return `<section class="panel"><div class="panel-head"><h3>通用价值观（不变层）</h3><span class="badge">${esc(v.source)}</span></div>`+
      `<div class="panel-body"><p class="hint" style="line-height:1.8">${esc(v.quote)}</p>`+
      `<div class="status-line"><span>第一定律</span><span>${esc(v.first_law)}</span></div>`+
      `<div class="status-line"><span>判定</span><span>${esc(v.test)}</span></div>`+
      `<p class="hint" style="margin-top:10px">${esc(v.note)}</p>`+
      `<p class="hint" style="margin-top:10px">状态：不可变（生存压力下可被「再理解」，见 §2.1.2）；特化价值观由场景推演生成，可迭代。</p></div></section>`
  }

  const RENDERERS={
    // 身份档案：两种形态（列表 / 单主体完整画像），都用人话标题，内部 ID 只作副标
    // 身份档案：两种形态（列表 / 单主体画像）；列表不预取详情；名称优先取锚点里的「身份=X」
    self_profile:v=>{
      const hasDetail=Array.isArray(v?.anchors)||Array.isArray(v?.traits)
      if(hasDetail){
        const anchors=Array.isArray(v.anchors)?v.anchors:[]
        const traits=Array.isArray(v.traits)?v.traits:[]
        const dn=displayNameFromAnchor((anchors[0]||{}).content)
        const kindCN=v?.kind?(SUBJ_KIND[v.kind]||v.kind):''
        const label=dn?(kindCN?kindCN+' · '+dn:dn):(kindCN?kindCN+' · '+(v?.name||''):(v?.name||'未命名主体'))
        const anchorHTML=anchors.map(a=>{
          const parts=String(a.content||'').trim().split(/;\s*/).filter(Boolean)
          const rows=parts.map(seg=>{
            const i=seg.indexOf('=')
            if(i<=0) return `<div class="row-item"><span class="row-dot"></span><div class="row-content"><div class="row-title" style="white-space:pre-wrap">${esc(seg)}</div></div></div>`
            const k=seg.slice(0,i).replace(/^[^:：]*[:：]/,'').trim()
            const val=seg.slice(i+1).trim()
            return `<div class="row-item"><span class="row-dot"></span><div class="row-content"><div class="eyebrow">${esc(k)}</div><div class="row-title" style="white-space:pre-wrap;line-height:1.75">${esc(val)}</div></div></div>`
          })
          return `<div class="panel-body"><div class="eyebrow">锚点 · ${esc(a.node_id||'')}</div><div style="margin-top:10px">${rows.join('')}</div></div>`
        }).join('')
        const traitHTML=traits.length?`<div class="panel-body"><div class="eyebrow">特征 ${traits.length} 条</div><div style="margin-top:8px">${traits.map(t=>`<div class="row-item"><span class="row-dot"></span><div class="row-content"><div class="row-title" style="white-space:pre-wrap">${esc(String(t.content||'').trim().slice(0,400))}</div><div class="row-meta">${t.importance!==undefined?`<span class="badge">重要度 ${esc(t.importance)}</span>`:''}<span>${esc(t.node_id||'')}</span></div></div></div>`).join('')}</div></div>`:''
        const foot=`<div class="panel-body"><div class="status-line"><span>位置</span><span>${esc(humanState(v?.position))}</span></div><div class="status-line"><span>主体 ID</span><span>${esc(v?.subject_id||'')}</span></div></div>`
        return CARD(label, anchorHTML+traitHTML+foot, '完整画像')
      }
      const subs=rowsOf(v)
      if(!subs.length) return CARD('读取结果 · 身份档案', EMPTY(v?.hint||'尚无身份锚点。'), '0 个主体')
      const body=subs.map(s=>{
        const h=humanSubject(s.subject_id||s.name)
        const rows=[
          ['主体 ID', esc(s.subject_id||'')],
          ['身份面节点', esc(s.nodes??'—')+' <small class="hint">（锚点 / 特征 / 状态卡；不含 self 层其它记录）</small>'],
          ['位置', esc(humanState(s.position))],
          ['证据', esc(s.evidence_count??0)+' 条'],
        ].map(([k,val])=>`<div class="status-line"><span>${k}</span><span>${val}</span></div>`).join('')
        return `<div class="panel-body"><div class="row-title">${esc(h.label)}</div><div style="margin-top:8px">${rows}</div><div class="actions"><button class="button" data-subject="${esc(s.subject_id||'')}">查看完整画像</button></div></div>`
      })
      return CARD('读取结果 · 身份档案', body.join(''), subs.length+' 个主体') },
    self_state:v=>{ const s=v?.state||{}
      const rows=[['自我重要性',s.importance_self],['信任度',s.p_trust],['信息差',s.d_current],['情绪',s.emotion],['情感倾向',s.affect],['层',s.layer],['节点',s.node_id]].filter(([,x])=>x!==undefined&&x!==null&&x!=='').map(([k,x])=>[k,typeof x==='object'?json(x).slice(0,120):String(x)])
      const dims=s.dimensions&&typeof s.dimensions==='object'?Object.entries(s.dimensions).slice(0,8).map(([k,x])=>[k,typeof x==='object'?json(x).slice(0,80):String(x)]):[]
      const extra=dims.length?`<div class="panel-body"><div class="eyebrow">维度</div><div style="margin-top:8px">${dims.map(([k,x])=>`<div class="status-line"><span>${esc(k)}</span><span>${esc(x)}</span></div>`).join('')}</div></div>`:''
      return CARD('自我状态', KV(rows)+extra, '快照') },
    meta_report:v=>{ const cal=v.calibration||{}, blind=rowsOf(v.blindspots), adv=Array.isArray(v.advice)?v.advice:rowsOf(v.advice)
      const parts=[CARD('校准',KV([['样本',cal.n??cal.samples??'—'],['平均误差',cal.error??cal.mean_error??'—'],['方向一致性',cal.signed??'—']]),'calibration'),
        CARD('盲区', blind.length?groupFeed(blind):EMPTY('没有记录到盲区。'), blind.length+' 条')]
      if(adv.length) parts.push(CARD('建议', groupFeed(adv.map(a=>({content:typeof a==='string'?a:json(a).slice(0,160)}))), adv.length+' 条'))
      return parts.join('') },
    whitebox:v=>CARD('白箱连通',KV([['状态',v?.ok?'可用':'不可用'],['工具',v?.tool||'—'],['信息',typeof v?.info==='object'?json(v.info).slice(0,160):String(v?.info??'—')]]),'ping'),
    review_pending:v=>{ const pd=rowsOf(v.pending||v); return CARD('待裁决候选', groupFeed(pd), pd.length+' 条') },
    review_records:v=>{ const rs=rowsOf(v.records||v); return CARD('审核记录', groupFeed(rs.map(r=>({content:[r.pid,r.decision,r.actor].filter(Boolean).join(' · ')||json(r).slice(0,120),t:r.t||r.ts,layer:r.layer,session:r.session}))), rs.length+' 条') },
    protect_stats:v=>{ const by=v.by_layer&&typeof v.by_layer==='object'?Object.entries(v.by_layer).map(([k,x])=>[layers[k]||k,String(x)]):[]
      return CARD('保护统计',KV([['受保护节点',v.protected_count??'—'],['不可变节点',v.immutable_count??'—'],...by]),'protect') },
    evolution:v=>{ const mp=v.most_missing&&typeof v.most_missing==='object'?Object.entries(v.most_missing).slice(0,6).map(([k,x])=>[k,String(x)]):[]
      return CARD('演化摘要',KV([['总计',v.evolutions??'—'],['回滚',v.rollbacks??'—'],['最常见缺失',v.top_pattern||'—'],...mp]),'evolution') },
    sustain:v=>{ const hb=v.heartbeat||{}, loop=v.loop||{}, ss=v.sessions||{}
      return CARD('维护状态',KV([['心跳',hb.alive?'在跳':'停'],['最近心跳',hb.t?time(hb.t):'—'],['循环轮次',loop.round??'—'],['会话数',Array.isArray(ss)?ss.length:(ss.count??'—')]]),'sustain') },
  }

  async function execute(button, tool, args, view) {
    // e.submitter 在键盘提交/程序化提交时可能为 null —— 旧实现直接取 .disabled 抛错，
    // 表现为「点了没反应」。按钮缺席时照常执行，只是不做执行中反馈。
    const btn = button || null; if (btn) { btn.disabled=true; btn.dataset.label=btn.textContent; btn.textContent='执行中…'; }
    try { const value=await call(tool,args,{interactive:true});
      const render=RENDERERS[view||'']
      const target=$('result')
      if(render&&target) target.innerHTML=render(value)+`<details class="raw"><summary>原始回执（机器面，未改写）</summary><pre>${esc(json(value))}</pre></details>`
      else renderResult(value)
      // 身份档案：点「查看完整画像」时才拉单个主体（列表页不预取）
      if((view||'')==='self_profile'&&target){
        target.querySelectorAll('[data-subject]').forEach(b=>b.onclick=async()=>{
          const sid=b.dataset.subject; if(!sid) return
          b.disabled=true; const old=b.textContent; b.textContent='读取中…'
          try{ const one=await call('cg',{op:'identity',action:'profile',subject_id:sid})
            if(token!==generation)return
            target.innerHTML=RENDERERS.self_profile(one)+`<details class="raw"><summary>原始回执（机器面，未改写）</summary><pre>${esc(json(one))}</pre></details>`
          }catch(err){ b.disabled=false; b.textContent=old; toast(err.message||'读取失败') }
        })
      }
    } catch(e) { const target=$('result'); if(target) target.innerHTML=errorHTML(e); }
    finally { if (btn) { btn.disabled=false; btn.textContent=btn.dataset.label||''; } }
  }
  function permissionNote(op) { const allowed=info?.whoami?.principal?.ops_allow; return allowed && !allowed.includes('*') && !allowed.includes(op) ? `<div class="notice">当前令牌未声明 ${esc(op)} 权限。入口保留，调用仍由灵枢权限系统裁定；本界面不会自动扩权。</div>`:''; }
  // issue #UI-PERF：概览页曾用 info(full=true) —— 实测 3.5 万节点库 **13.94s**（health_os 全库扫描）。
  // 改法：只取快照面 info（0.09s），四张统计卡各用**各自最便宜的 op** 并行取（0.02–0.03s/个），
  // 谁先回来先渲染（渐进），慢的那个不再阻塞首屏。
  async function overview(token) {
    const head=()=>title('让认知，有迹可循。','COGNITIVE WORKSPACE','记忆、目标与自我，在同一张认知图中延续。','<button id="new-memory" class="button primary">＋ 记录记忆</button>')
    $('main').innerHTML=head()+loading()
    const cards=[['记忆节点','—','认知图中的真实记录'],['活跃目标','—','持续追踪的行动方向'],['待审核','—','等待裁决的候选'],['受保护','—','需要保留的认知锚点']]
    const shell=()=>head()+`<div class="stats">${cards.map(([name,count,note])=>`<div class="stat"><div class="stat-label">${name}</div><div class="stat-value">${esc(count)}</div><div class="stat-note">${note}</div></div>`).join('')}</div><div id="ov-rest">${loading()}</div>`
    // 1) 先拿快照（便宜）：info 不带 full
    let info0
    try { info0 = await call('cg',{op:'info'}) } catch(e) { if(token===generation)$('main').innerHTML=head()+errorHTML(e); return }
    if(token!==generation)return
    info=info0; meta=meta||{}
    cards[0][1]=info0.node_count??info0.total_nodes??'—'
    $('main').innerHTML=shell()
    $('new-memory').onclick=()=>navigate('memory',true)
    $('ov-rest').innerHTML=loading()
    // 2) 三张统计卡各走最便宜的 op（并行、容错；单个失败只影响自己那张卡）
    const [g,p,pr]=await Promise.allSettled([
      call('cg',{op:'goal',action:'list',limit:1}),
      call('cg',{op:'review',action:'list'}),
      call('cg',{op:'protect',action:'stats'})
    ])
    if(token!==generation)return
    cards[1][1]=g.status==='fulfilled'?((g.value?.active&&g.value.active.length)??'—'):'—'
    cards[2][1]=p.status==='fulfilled'?((p.value?.pending||[]).length):'—'
    cards[3][1]=pr.status==='fulfilled'?(pr.value?.protected_count??'—'):'—'
    $('main').innerHTML=shell()
    $('new-memory').onclick=()=>navigate('memory',true)
    // 3) 时间线与运行状态（timeline 5 实测 0.5s；失败不拖垮整页）
    const tl=await call('stg',{op:'timeline',limit:5,desc:true}).catch(e=>e)
    if(token!==generation)return
    const who=info0.whoami?.principal||{}
    $('ov-rest').outerHTML='<div id="ov-rest">'+
      `<div class="grid-two"><section class="panel"><div class="panel-head"><h3>最近记忆</h3><button class="button text" id="all-memory">查看全部 ↗</button></div>${tl instanceof Error?errorHTML(tl):nodeRows(tl.items)}</section><div><section class="panel"><div class="panel-head"><h3>运行状态</h3><span class="badge">真实连接</span></div><div class="panel-body">${[['大脑桥',meta.ready?'已就绪':'未就绪'],['写入权限',who.can_write?'可写 · '+(who.role||'已授权'):'只读'],['可见密级',who.clearance||'—'],['自动召回',meta.memory?.autoRecall?'开启':'关闭'],['近期窗口',meta.memory?.contextWindow?.enabled?(meta.memory.contextWindow.turns+' 条'):'关闭']].map(([k,v])=>`<div class="status-line"><span>${k}</span><span>${esc(v)}</span></div>`).join('')}<div class="permission">工具可见不等于全部有权限。保留现有令牌与护栏。</div></div></section><div class="quick-actions"><button class="button quick-action" data-page="goals">目标与任务 <span>明确下一步 ↗</span></button><button class="button quick-action" data-page="tools">完整工具台 <span>${(meta.tools||[]).length} 个真实工具 ↗</span></button></div></div></div>`+
      `<div class="panel section-gap"><div class="panel-body"><h3>认知图健康</h3><p class="hint" style="margin-top:10px">${info0.problems?.length?esc(info0.problems.join('；')):'快照模式：未跑全库健康扫描（点了才跑，避免首屏等十几秒）。'}</p><div class="path muted">${esc(info0.whoami?.root||'')}</div></div></div></div>`
    $('all-memory').onclick=()=>navigate('memory'); document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>navigate(b.dataset.page)); bindNodes()
  }
  // ---- issue #UI-PERF-2（使用者裁定 2026-11-14）：记忆页优先显示「便宜的、近的、待办的」，
  // 历史一律**手动加载**。实测（3.5 万节点库）：self_state 0.02s / review list 0.15s /
  // recent 100 0.00s / timeline 100 0.62s，而 cg read 24s ⇒ 首屏绝不发 read。
  const ROLE_CN={user:'我',assistant:'灵枢',tool:'工具',system:'系统'}
  function feedRows(events){
    if(!events?.length) return '<div class="empty">今天还没有对话。</div>'
    return events.map(e=>{const role=e.role||'',cn=ROLE_CN[role]||role||'记录',t=e.t||e.ts||e.start
      return `<div class="row-item"><span class="feed-time">${esc(time(t))}</span><div class="row-content"><div class="row-title">${esc(String(e.text||e.preview||'').slice(0,300))}</div><div class="row-meta"><span class="badge">${esc(cn)}</span>${e.meta?.session?`<span>${esc(String(e.meta.session).slice(0,12))}</span>`:''}</div></div></div>`}).join('')
  }
  async function memory(token, compose) {
    const today0=new Date(); today0.setHours(0,0,0,0); const todayTs=today0.getTime()/1000
    $('main').innerHTML=title('记忆','MEMORY','先看近的与待办的；历史检索按需手动加载。','<button id="compose-toggle" class="button primary">＋ 记录记忆</button>')+
      `<section id="compose" class="panel" ${compose?'':'hidden'}><div class="panel-head"><h3>记录一条记忆</h3><span class="badge">主动遗忘闸门</span></div><form id="memory-form" class="panel-body form-grid"><label>内容<textarea id="memory-content" required placeholder="记录事实、经验或需要延续的上下文…"></textarea></label><div class="form-inline"><label>归属层<select id="memory-layer"><option value="contextual">情景 · 对话与经历</option><option value="knowledge">知识 · 经验与事实</option><option value="structural">结构 · 方法与规则</option><option value="self">自我 · 身份与认知</option></select></label><label>重要性<input id="memory-importance" type="number" min="0" max="1" step="0.05" value="0.5"></label></div><label>标签<input id="memory-tags" placeholder="使用逗号分隔，如：项目,经验"></label><p class="hint">通过 mdcg_remember 写入。可能接受、合并、丢弃或进入审核队列；结果以真实回执为准。</p><div class="actions"><button type="submit" class="button primary">确认记录</button></div></form></section>`+
      `<div class="grid-two"><section class="panel"><div class="panel-head"><h3>自我层</h3><span class="badge" id="self-badge">读取中…</span></div><div id="sec-self" class="panel-body">${loading()}</div></section><section class="panel"><div class="panel-head"><h3>待裁决</h3><span class="count" id="review-count"></span></div><div id="sec-review">${loading()}</div></section></div>`+
      `<section class="panel section-gap"><div class="panel-head"><h3>今日对话</h3><span class="count" id="today-count"></span></div><div id="sec-today">${loading()}</div></section>`+
      `<section class="panel section-gap"><div class="panel-head"><h3>最近 100 条对话</h3><span class="count" id="recent-count"></span></div><div id="sec-recent">${loading()}</div></section>`+
      `<section class="panel section-gap"><div class="panel-head"><h3>历史（手动加载）</h3><span class="badge">默认不读</span></div><div class="panel-body"><p class="hint">历史与全库检索成本高（实测 read≈24s / timeline≈0.6s）。点按钮才发起，可随时取消。</p><form id="hist-search" class="toolbar"><input id="hist-query" class="search" placeholder="全库检索（手动、较慢，约 10–25 秒）…" aria-label="全库检索"><button class="button" type="submit">检索 ↗</button></form>
        <div class="actions"><button id="load-older" class="button">加载更早的对话（100 条）</button><button id="cancel-load" class="button" hidden>取消</button></div></div><div id="sec-history"></div><div id="result"></div></section>`
    $('compose-toggle').onclick=()=>{$('compose').hidden=!$('compose').hidden; if(!$('compose').hidden)$('memory-content').focus();}
    $('memory-form').onsubmit=async e=>{e.preventDefault(); await execute(e.submitter,'mdcg_remember',{content:$('memory-content').value.trim(),layer:$('memory-layer').value,role:'user',importance:Number($('memory-importance').value),tags:$('memory-tags').value.split(/[,，]/).map(s=>s.trim()).filter(Boolean),gated:true,consistency:true,on_conflict:'defer'});}
    // 四个优先区块并行、各自渲染；任一失败只影响自己
    const selfP=call('cg',{op:'self_state',action:'snapshot'}).then(r=>{ if(token!==generation)return; const s=r?.state||{}
      const rows=[['自我重要性',s.importance_self],['信任',s.p_trust],['信息差',s.d_current],['情绪',s.emotion??s.affect]].filter(([,v])=>v!==undefined&&v!==null)
      $('sec-self').innerHTML=rows.length?rows.map(([k,v])=>`<div class="status-line"><span>${k}</span><span>${esc(typeof v==='object'?json(v).slice(0,80):v)}</span></div>`).join(''):'<div class="empty">自我层暂无状态卡。</div>'
      $('self-badge').textContent='已读取' }).catch(e=>{ if(token===generation){$('sec-self').innerHTML=errorHTML(e);$('self-badge').textContent='读取失败'} })
    const reviewP=call('cg',{op:'review',action:'list'}).then(r=>{ if(token!==generation)return; const pd=r?.pending||[]; $('review-count').textContent=`${pd.length} 条`
      $('sec-review').innerHTML=pd.length?pd.slice(0,20).map(p=>`<button type="button" class="row-item node-button" data-node="${esc(p.id||'')}"><span class="row-dot"></span><div class="row-content"><div class="row-title">${esc(String(p.content||'').slice(0,160))}</div><div class="row-meta"><span class="badge">${esc(layers[p.layer]||p.layer||'候选')}</span><span>${esc(time(p.t))}</span><span>${esc(p.pid||'')}</span></div></div></button>`).join('')+(pd.length>20?`<div class="panel-body"><span class="hint">还有 ${pd.length-20} 条未展示（渲染上限 20，避免一次铺 240 条 DOM）</span></div>`:'') : '<div class="empty">没有待裁决候选。</div>'
      bindNodes($('sec-review')) }).catch(e=>{ if(token===generation)$('sec-review').innerHTML=errorHTML(e) })
    const recentP=call('cg',{op:'recent',action:'list',limit:100}).then(r=>{ if(token!==generation)return; const ev=r?.events||[]
      $('recent-count').textContent=`${ev.length} 条`; $('sec-recent').innerHTML=feedRows(ev)
      const today=ev.filter(e=>(e.t||e.ts||0)>=todayTs); $('today-count').textContent=`${today.length} 条`
      $('sec-today').innerHTML=today.length?feedRows(today):'<div class="empty">今天还没有对话。</div>' }).catch(e=>{ if(token===generation){$('sec-recent').innerHTML=errorHTML(e);$('sec-today').innerHTML=errorHTML(e)} })
    // 历史：只有点击才发（timeline 0.6s / read 24s 都不进首屏）
    let histCtrl=null
    $('load-older').onclick=async e=>{
      const btn=e.currentTarget, list=$('sec-history'); btn.disabled=true; $('cancel-load').hidden=false
      histCtrl=new AbortController(); list.innerHTML=loading()
      try{ const r=await call('stg',{op:'timeline',limit:100,desc:true},{signal:histCtrl.signal})
        if(token!==generation)return; const items=rowsOf(r)
        list.innerHTML=`<section class="panel"><div class="panel-head"><h3>更早的对话</h3><span class="count">${items.length} 条</span></div>${nodeRows(items)}</section>`; bindNodes(list)
      }catch(err){ if(err.name!=='AbortError'&&token===generation) list.innerHTML=errorHTML(err); else if(token===generation) list.innerHTML='<div class="panel-body"><span class="hint">已取消。</span></div>' }
      finally{ btn.disabled=false; $('cancel-load').hidden=true }
    }
    // 全库检索：同样是**手动**入口（read 实测 24s），与历史加载共用取消
    $('hist-search').onsubmit=async e=>{
      e.preventDefault(); const q=$('hist-query').value.trim(); if(!q) return
      const list=$('sec-history'); if(histCtrl) try{histCtrl.abort()}catch{}; histCtrl=new AbortController()
      $('cancel-load').hidden=false; list.innerHTML=loading()
      try{ const r=await call('cg',{op:'read',query:q,k:20},{signal:histCtrl.signal})
        if(token!==generation)return; const items=rowsOf(r)
        list.innerHTML=`<section class="panel"><div class="panel-head"><h3>检索结果</h3><span class="count">${items.length} 条</span></div>${items.length?nodeRows(items):'<div class="empty">没有命中。</div>'}</section>`; bindNodes(list)
      }catch(err){ if(err.name==='AbortError'){ if(token===generation) list.innerHTML='<div class="panel-body"><span class="hint">已取消。</span></div>' } else if(token===generation) list.innerHTML=errorHTML(err) }
      finally{ $('cancel-load').hidden=true }
    }
    $('cancel-load').onclick=()=>{ if(histCtrl) try{histCtrl.abort()}catch{} }
    await Promise.allSettled([selfP,reviewP,recentP])
  }
  const presets = {
    goals: {title:'目标与任务',en:'GOALS & TASKS',description:'把目标变成可追踪的行动。查询和新增，都保留真实回执。',items:[['目标列表','cg',{op:'goal',action:'list',limit:20}],['任务列表','cg',{op:'task',action:'list',limit:20}],['新增目标','cg',{op:'goal',action:'add',goal:'',priority:1}],['开启任务','cg',{op:'task',action:'open',goal:'',plan:'',acceptance:''}]]},
    self: {title:'自我认知',en:'SELF & IDENTITY',description:'身份、状态与反思，分别读取，不把生成的文字当作认知事实。',items:[['身份档案','cg',{op:'identity',action:'profile'},'','self_profile'],['状态快照','cg',{op:'self_state',action:'snapshot'},'','self_state'],['元认知报告','cg',{op:'metacognition',action:'report'},'','meta_report'],['白箱连通','cg',{op:'whitebox',action:'ping'},'','whitebox']]},
    space: {title:'时空关系',en:'SPACE & TIME',description:'沿时间寻找记忆，或比较两个节点的时空关系。',items:[['记忆时间线','stg',{op:'timeline',limit:20,desc:true}],['近期事件','cg',{op:'recent',action:'list',limit:20}],['节点关系','stg',{op:'relation',a:'',b:''}],['时空一致性','stg',{op:'consistency',limit:20}],['锚点查询','stg',{op:'anchors',time_window:[0,Math.floor(Date.now()/1000)],limit:20}],['状态链','stg',{op:'state_chain',subject:'self:lingshu',limit:20},'本面默认关：需在灵枢进程设 MDCG_STG_STATE=1 才启用（返回 error=disabled 属如实拒绝，不是界面故障）。']]},
    review: {title:'审核与维护',en:'REVIEW & CARE',description:'先查看，再裁决。不会在打开页面时启动维护、遗忘或自动演化。',items:[['待审核候选','cg',{op:'review',action:'list'},'','review_pending'],['审核记录','cg',{op:'review',action:'records'},'','review_records'],['保护统计','cg',{op:'protect',action:'stats'},'','protect_stats'],['演化摘要','cg',{op:'evolution',action:'summary'},'','evolution'],['维护状态','cg',{op:'sustain',action:'status'},'','sustain'],['审核裁决','cg',{op:'review',action:'decide',pid:'',decision:'reject'}],['节点核验','cg',{op:'verify',node_id:'',evidence:'',verdict:'confirmed'}]]}
  };
  // 生效条件：预设项带 note 时，在执行区顶部如实显示前置开关（如 MDCG_STG_STATE=1）
  function noteOf(item) { return item && item[3] ? `<div class="notice">${esc(item[3])}</div>` : ''; }
  function grouped(name) {
    const group=presets[name]; let active=0;
    $('main').innerHTML=title(group.title,group.en,group.description)+(name==="self"?universalValuesCard():"")+`<div class="command-tabs">${group.items.map(([label],i)=>`<button class="chip ${i===0?'active':''}" data-preset="${i}">${label}</button>`).join('')}</div><div id="permission"></div><section class="panel"><div class="panel-head"><h3 id="command-title"></h3><span class="badge" id="command-tool"></span></div><div class="panel-body"><div id="preset-fields" class="form-grid"></div><details><summary>原始调用参数</summary><textarea class="raw-args" id="preset-json" aria-label="原始调用参数"></textarea></details><div class="actions"><button id="preset-help" class="button">查看帮助</button><button id="preset-run" class="button primary">执行查询</button></div></div></section><div id="result"></div>`;
    function select(i) {
      active=i; const [label,tool,args]=group.items[i]; $('command-title').textContent=label; $('command-tool').textContent=tool+' · '+args.op; const _note=noteOf(group.items[i]); const _pf=$('preset-fields');
      document.querySelectorAll('[data-preset]').forEach(b=>b.classList.toggle('active',Number(b.dataset.preset)===i)); $('permission').innerHTML=tool==='cg'?permissionNote(args.op):''; $('preset-json').value=json(args); $('result').innerHTML='';
      $('preset-run').textContent=needsConfirm(tool,args)?'检查并执行':'执行查询';
      $('preset-fields').innerHTML=_note+Object.entries(args).filter(([k])=>!['op','action','limit','desc'].includes(k)).map(([k,v])=>`<label>${esc(fieldLabel(k))}<${typeof v==='string'&&['plan','evidence','acceptance','goal'].includes(k)?'textarea':'input'} data-preset-field="${esc(k)}" ${typeof v==='number'?'type="number" step="any"':''} ${Array.isArray(v)?'placeholder="JSON 数组"':''} ${typeof v==='string'&&['plan','evidence','acceptance','goal'].includes(k)?'':`value="${esc(typeof v==='object'?json(v):v)}"`}>${typeof v==='string'&&['plan','evidence','acceptance','goal'].includes(k)?esc(v):''}</${typeof v==='string'&&['plan','evidence','acceptance','goal'].includes(k)?'textarea':'input'}></label>`).join('') || '<p class="hint">无需额外参数。点击执行，读取真实数据。</p>';
      document.querySelectorAll('[data-preset-field]').forEach(input=>input.oninput=()=>{try{const next=JSON.parse($('preset-json').value),key=input.dataset.presetField,old=args[key];next[key]=typeof old==='number'?Number(input.value):typeof old==='object'?JSON.parse(input.value):input.value;$('preset-json').value=json(next);}catch{/* 继续保留用户编辑 */}});
    }
    document.querySelectorAll('[data-preset]').forEach(b=>b.onclick=()=>select(Number(b.dataset.preset)));
    $('preset-run').onclick=async e=> { try { const args=JSON.parse($('preset-json').value); await execute(e.currentTarget,group.items[active][1],args,group.items[active][4]); }catch(err){$('result').innerHTML=errorHTML(err);} };
    $('preset-help').onclick=async e=>await execute(e.currentTarget,'cg',{op:'help',query:group.items[active][2].op}); select(0);
  }
  function fieldLabel(key) { return {goal:'目标内容',plan:'执行计划',acceptance:'验收标准',priority:'优先级',a:'节点 A',b:'节点 B',node_id:'节点 ID',pid:'候选 ID',decision:'裁决：accept / reject / edit / merge',evidence:'验证依据',verdict:'判定：confirmed / weakened / falsified',time_window:'时间窗口（秒级时间戳数组）',subject:'主体'}[key]||key; }
  async function toolsPage() {
    const tools=meta?.tools||[];
    $('main').innerHTML=title('工具台','PLUGIN CAPABILITIES','完整工具来自灵枢实时目录。常用参数可填表，高级能力通过原始 JSON 调用。')+
      `<div class="notice">保持插件原有权限边界。写入、裁决、索引、导出与维护操作均需确认；不会自动启动后台任务。</div><div class="tool-layout"><section class="panel"><div class="panel-body" style="padding:15px"><input id="tool-search" style="width:100%" placeholder="查找工具…" aria-label="查找工具"></div><div id="tool-list" class="tool-list"></div></section><section class="panel"><div class="panel-body"><h2 id="tool-name"></h2><div id="tool-description" class="tools-description"></div><div id="op-chooser"></div><div id="schema-fields" class="schema-fields"></div><details open><summary>原始 JSON 参数 · 完整能力入口</summary><textarea id="tool-args" class="raw-args" spellcheck="false" aria-label="工具 JSON 参数"></textarea></details><div class="actions"><button id="tool-help" class="button">调用说明</button><button id="tool-run" class="button primary">执行调用</button></div></div></section></div><div id="result"></div>`;
    function renderList() { $('tool-list').innerHTML=tools.filter(t=>(t.name+' '+t.description).toLowerCase().includes(toolsFilter.toLowerCase())).map(t=>`<button class="tool-choice ${chosen===t.name?'active':''}" data-tool="${esc(t.name)}">${esc(t.name)}</button>`).join('') || '<div class="empty">没有匹配工具</div>'; document.querySelectorAll('[data-tool]').forEach(b=>b.onclick=()=>selectTool(b.dataset.tool)); }
    async function selectTool(name) {
      chosen=name; const tool=tools.find(t=>t.name===name); if(!tool)return;
      renderList(); $('tool-name').textContent=name; $('tool-description').textContent=tool.description;
      const properties=tool.inputSchema?.properties || {}, required=tool.inputSchema?.required || [];
      const defaults = name==='cg'?{op:'info'}:name==='stg'?{op:'timeline',limit:20,desc:true}:{};
      $('tool-args').value=json(defaults); $('result').innerHTML='';
      const opProp=properties.op;
      let ops=opProp?.enum || [];
      if(!ops.length && opProp?.description) ops=(opProp.description.split(/[\s，。]/)[0]||'').split('|').filter(Boolean);
      $('op-chooser').innerHTML=ops.length?`<label class="schema-field" style="margin-top:20px">操作<select id="tool-op">${ops.map(op=>`<option value="${esc(op)}">${esc(op)}</option>`).join('')}</select></label>`:'';
      if($('tool-op')){ $('tool-op').value=defaults.op||ops[0]; $('tool-op').onchange=()=>{try{const args=JSON.parse($('tool-args').value);args.op=$('tool-op').value;delete args.action;$('tool-args').value=json(args);}catch(e){toast('先修正 JSON 参数。');}}; }
      const common=Object.entries(properties).filter(([key])=>key!=='op' && (required.includes(key)||['query','content','action','node_id','layer','limit','goal','evidence','verdict','a','b'].includes(key)));
      $('schema-fields').innerHTML=common.map(([key,p])=>`<label class="schema-field">${esc(fieldLabel(key))}${required.includes(key)?' *':''}<input data-field="${esc(key)}" data-type="${esc(p.type||'string')}" placeholder="${esc(p.enum?.join(' / ')||p.type||'string')}" ${p.type==='number'||p.type==='integer'?'type="number" step="any"':''}><small>${esc((p.description||'').slice(0,240))}</small></label>`).join('');
      document.querySelectorAll('[data-field]').forEach(input=>input.oninput=()=>{try{const args=JSON.parse($('tool-args').value),key=input.dataset.field;if(input.value==='')delete args[key];else args[key]=['number','integer'].includes(input.dataset.type)?Number(input.value):['object','array','boolean'].includes(input.dataset.type)?JSON.parse(input.value):input.value;$('tool-args').value=json(args);}catch{toast('该字段需要有效 JSON，或请直接编辑原始参数。');}});
    }
    $('tool-search').value=toolsFilter; $('tool-search').oninput=e=>{toolsFilter=e.target.value;renderList();};
    $('tool-run').onclick=async e=>{try{const args=JSON.parse($('tool-args').value);await execute(e.currentTarget,chosen,args);}catch(err){$('result').innerHTML=errorHTML(err);}};
    $('tool-help').onclick=async e=>await execute(e.currentTarget,'cg',{op:'help',query:chosen});
    if(!tools.some(t=>t.name===chosen))chosen=tools[0]?.name; renderList(); if(chosen)await selectTool(chosen); else $('tool-name').textContent='大脑未就绪，目录不可用';
  }
  async function navigate(name, compose=false) {
    page=pages.some(p=>p[0]===name)?name:'overview'; const token=++generation;
    history.replaceState(null,'', '#'+page); $('crumb').textContent=pages.find(p=>p[0]===page)[2];
    document.querySelectorAll('[data-nav]').forEach(b=>{b.classList.toggle('active',b.dataset.nav===page); if(b.dataset.nav===page)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
    $('main').innerHTML=loading();
    try { if(!meta)throw new Error('插件未连接，请点击右上角刷新。'); if(page==='overview')await overview(token);else if(page==='memory')await memory(token,compose);else if(presets[page])grouped(page);else await toolsPage(); }
    catch(e) { if(token===generation)$('main').innerHTML=title('暂时无法读取','CONNECTION','数据没有被替换为演示内容。请检查灵枢连接。')+errorHTML(e); }
  }
  async function boot() {
    $('refresh').disabled=true;
    try { meta=await fetchJSON('/plugins/lingshu/meta');$('connection').textContent=meta.ready?'大脑已连接':'大脑未就绪';$('connection').classList.toggle('online',meta.ready);$('identity').textContent=meta.identity+' · '+meta.tools.length+' 个工具';
      if (meta.version) { const v=$('version'); if (v) v.textContent='LINGSHU / '+meta.version; } await navigate(location.hash.slice(1)||page); }
    catch(e){meta=null;$('connection').textContent='连接失败';$('connection').classList.remove('online');$('main').innerHTML=errorHTML(e);}
    finally{$('refresh').disabled=false;}
  }
  $('nav').innerHTML=pages.map(([id,icon,label])=>`<button class="nav-item" data-nav="${id}"><span class="nav-icon" aria-hidden="true">${icon}</span>${label}</button>`).join('');
  document.querySelectorAll('[data-nav]').forEach(b=>b.onclick=()=>navigate(b.dataset.nav)); $('refresh').onclick=boot; $('close-detail').onclick=()=>$('detail').close();
  let theme='';try{theme=localStorage.getItem('lingshu.theme')||'';}catch{} if(theme)document.documentElement.dataset.theme=theme;else if(matchMedia('(prefers-color-scheme:dark)').matches)document.documentElement.dataset.theme='dark';
  $('theme').onclick=()=>{const next=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=next;try{localStorage.setItem('lingshu.theme',next);}catch{}};
  window.addEventListener('hashchange',()=>navigate(location.hash.slice(1))); void boot();
})();
