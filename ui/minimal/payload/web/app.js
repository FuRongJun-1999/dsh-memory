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
      const response = await fetch(url, { credentials:'same-origin', ...options, signal:controller.signal });
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
  async function call(tool, args, interactive = false) {
    if (!meta?.csrf) throw new Error('灵枢未连接，请刷新后重试。');
    const mutating = needsConfirm(tool,args);
    if (mutating && (!interactive || !await confirm(tool,args))) throw new Error('已取消操作');
    const response = await fetchJSON('/plugins/lingshu/call', { method:'POST', headers:{'Content-Type':'application/json','X-Lingshu-CSRF':meta.csrf}, body:JSON.stringify({tool,args,confirm:mutating}) });
    return response.result;
  }
  function toast(text) { $('toast').textContent=text; $('toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').hidden=true,4000); }
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
  function rowsOf(value) { if (Array.isArray(value)) return value; for(const key of ['items','results','goals','tasks','records','events','nodes','pack']) if(Array.isArray(value?.[key])) return value[key]; return []; }
  function renderResult(value, target='result') {
    const el=$(target); if(!el)return;
    el.innerHTML=`<div class="panel"><div class="panel-body"><div class="result-head"><h3>调用结果</h3><button id="copy-result" class="button">复制 JSON</button></div>${value?.error?`<div class="notice error">${esc(value.error)}</div>`:''}${value?.verdict||value?.moved_to||value?.committed===false?`<div class="notice">${esc(value.verdict||'未直接提交')}${value.moved_to?' · '+esc(value.moved_to):''}${value.pid?' · 审核 '+esc(value.pid):''}。以下为真实回执，不代表全部已落盘。</div>`:''}<pre id="result-json"></pre></div></div>`;
    $('result-json').textContent = typeof value==='string'?value:json(value);
    $('copy-result').onclick=async()=> { try { await navigator.clipboard.writeText($('result-json').textContent); toast('已复制'); } catch { toast('无法访问剪贴板，可直接选中结果复制。'); } };
  }
  async function execute(button, tool, args) {
    button.disabled=true; const original=button.textContent; button.textContent='执行中…';
    try { renderResult(await call(tool,args,true)); } catch(e) { const target=$('result'); if(target) target.innerHTML=errorHTML(e); }
    finally { button.disabled=false; button.textContent=original; }
  }
  function permissionNote(op) { const allowed=info?.whoami?.principal?.ops_allow; return allowed && !allowed.includes(op) ? `<div class="notice">当前令牌未声明 ${esc(op)} 权限。入口保留，调用仍由灵枢权限系统裁定；本界面不会自动扩权。</div>`:''; }
  async function overview(token) {
    $('main').innerHTML=title('让认知，有迹可循。','COGNITIVE WORKSPACE','记忆、目标与自我，在同一张认知图中延续。','<button id="new-memory" class="button primary">＋ 记录记忆</button>')+loading();
    $('new-memory').onclick=()=>navigate('memory',true);
    const results=await Promise.allSettled([call('cg',{op:'info'}),call('stg',{op:'timeline',limit:5,desc:true})]);
    if(token!==generation)return;
    if(results[0].status==='rejected') throw results[0].reason;
    info=results[0].value; const os=info.os||{}, who=info.whoami?.principal||{}; const timeline=results[1].status==='fulfilled'?results[1].value:null;
    $('main').innerHTML=title('让认知，有迹可循。','COGNITIVE WORKSPACE','记忆、目标与自我，在同一张认知图中延续。','<button id="new-memory" class="button primary">＋ 记录记忆</button>')+
      `<div class="stats">${[['记忆节点',info.total_nodes??info.whoami?.nodes_visible??'—','认知图中的真实记录'],['活跃目标',os.goals?.active??'—','持续追踪的行动方向'],['待审核',os.review_pending??'—','等待裁决的候选'],['受保护',os.protection?.protected_count??'—','需要保留的认知锚点']].map(([name,count,note])=>`<div class="stat"><div class="stat-label">${name}</div><div class="stat-value">${esc(count)}</div><div class="stat-note">${note}</div></div>`).join('')}</div>`+
      `<div class="grid-two"><section class="panel"><div class="panel-head"><h3>最近记忆</h3><button class="button text" id="all-memory">查看全部 ↗</button></div>${timeline?nodeRows(timeline.items):errorHTML(results[1].reason)}</section><div><section class="panel"><div class="panel-head"><h3>运行状态</h3><span class="badge">真实连接</span></div><div class="panel-body">${[['大脑桥',meta.ready?'已就绪':'未就绪'],['写入权限',who.can_write?'可写 · '+(who.role||'已授权'):'只读'],['可见密级',who.clearance||'—'],['自动召回',meta.memory?.autoRecall?'开启':'关闭'],['近期窗口',meta.memory?.contextWindow?.enabled?(meta.memory.contextWindow.turns+' 条'):'关闭']].map(([k,v])=>`<div class="status-line"><span>${k}</span><span>${esc(v)}</span></div>`).join('')}<div class="permission">工具可见不等于全部有权限。保留现有令牌与护栏。</div></div></section><div class="quick-actions"><button class="button quick-action" data-page="goals">目标与任务 <span>明确下一步 ↗</span></button><button class="button quick-action" data-page="tools">完整工具台 <span>${meta.tools.length} 个真实工具 ↗</span></button></div></div></div>`+
      `<div class="panel section-gap"><div class="panel-body"><h3>认知图健康</h3><p class="hint" style="margin-top:10px">${info.problems?.length?esc(info.problems.join('；')):'暂无健康诊断问题。'}</p><div class="path muted">${esc(info.whoami?.root||'')}</div></div></div>`;
    $('new-memory').onclick=()=>navigate('memory',true); $('all-memory').onclick=()=>navigate('memory'); document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>navigate(b.dataset.page)); bindNodes();
  }
  async function memory(token, compose) {
    $('main').innerHTML=title('记忆','MEMORY','检索已有认知，或将一条有价值的信息交给记忆闸门。','<button id="compose-toggle" class="button primary">＋ 记录记忆</button>')+
      `<section id="compose" class="panel" ${compose?'':'hidden'}><div class="panel-head"><h3>记录一条记忆</h3><span class="badge">主动遗忘闸门</span></div><form id="memory-form" class="panel-body form-grid"><label>内容<textarea id="memory-content" required placeholder="记录事实、经验或需要延续的上下文…"></textarea></label><div class="form-inline"><label>归属层<select id="memory-layer"><option value="contextual">情景 · 对话与经历</option><option value="knowledge">知识 · 经验与事实</option><option value="structural">结构 · 方法与规则</option><option value="self">自我 · 身份与认知</option></select></label><label>重要性<input id="memory-importance" type="number" min="0" max="1" step="0.05" value="0.5"></label></div><label>标签<input id="memory-tags" placeholder="使用逗号分隔，如：项目,经验"></label><p class="hint">通过 mdcg_remember 写入。可能接受、合并、丢弃或进入审核队列；结果以真实回执为准。不会指定节点 ID 或覆盖已有记录。</p><div class="actions"><button type="submit" class="button primary">确认记录</button></div></form></section><form id="search-form" class="toolbar ${compose?'section-gap':''}"><input id="search-query" class="search" placeholder="搜索记忆中的关键词或问题…" aria-label="搜索记忆"><select id="search-layer" aria-label="记忆层"><option value="">所有层</option>${Object.entries(layers).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select><button class="button" type="submit">检索 ↗</button></form><section class="panel"><div class="panel-head"><h3 id="memory-list-title">最近写入的记忆</h3><span class="count" id="memory-count"></span></div><div id="memory-list">${loading()}</div></section><div id="result"></div>`;
    $('compose-toggle').onclick=()=>{$('compose').hidden=!$('compose').hidden; if(!$('compose').hidden)$('memory-content').focus();};
    $('memory-form').onsubmit=async e=> { e.preventDefault(); const args={content:$('memory-content').value.trim(),layer:$('memory-layer').value,role:'user',importance:Number($('memory-importance').value),tags:$('memory-tags').value.split(/[,，]/).map(s=>s.trim()).filter(Boolean),gated:true,consistency:true,on_conflict:'defer'}; await execute(e.submitter,'mdcg_remember',args); };
    async function loadList(search=false) {
      const query=$('search-query').value.trim(), layer=$('search-layer').value;
      const list=$('memory-list'), count=$('memory-count'); list.innerHTML=loading();
      try { const result=query?await call('cg',{op:'read',query,k:30,...(layer?{layer}:{})}):await call('stg',{op:'timeline',limit:30,desc:true,...(layer?{layer}:{})}); if(token!==generation)return; const items=rowsOf(result); list.innerHTML=result?.error?errorHTML(result.error):nodeRows(items); count.textContent=`${items.length} 条${result.truncated?' · 已截断':''}`; $('memory-list-title').textContent=query?'检索结果':'最近写入的记忆'; bindNodes(list); if(search&&result?.meta)renderResult(result); } catch(e) { if(token===generation)list.innerHTML=errorHTML(e); }
    }
    $('search-form').onsubmit=e=>{e.preventDefault();void loadList(true);}; $('search-layer').onchange=()=>void loadList(); await loadList();
  }
  const presets = {
    goals: {title:'目标与任务',en:'GOALS & TASKS',description:'把目标变成可追踪的行动。查询和新增，都保留真实回执。',items:[['目标列表','cg',{op:'goal',action:'list',limit:20}],['任务列表','cg',{op:'task',action:'list',limit:20}],['新增目标','cg',{op:'goal',action:'add',goal:'',priority:1}],['开启任务','cg',{op:'task',action:'open',goal:'',plan:'',acceptance:''}]]},
    self: {title:'自我认知',en:'SELF & IDENTITY',description:'身份、状态与反思，分别读取，不把生成的文字当作认知事实。',items:[['身份档案','cg',{op:'identity',action:'profile'}],['状态快照','cg',{op:'self_state',action:'snapshot'}],['元认知报告','cg',{op:'metacognition',action:'report'}],['白箱连通','cg',{op:'whitebox',action:'ping'}]]},
    space: {title:'时空关系',en:'SPACE & TIME',description:'沿时间寻找记忆，或比较两个节点的时空关系。',items:[['记忆时间线','stg',{op:'timeline',limit:20,desc:true}],['近期事件','cg',{op:'recent',action:'list',limit:20}],['节点关系','stg',{op:'relation',a:'',b:''}],['时空一致性','stg',{op:'consistency',limit:20}],['锚点查询','stg',{op:'anchors',time_window:[0,Math.floor(Date.now()/1000)],limit:20}],['状态链','stg',{op:'state_chain',subject:'self:lingshu',limit:20}]]},
    review: {title:'审核与维护',en:'REVIEW & CARE',description:'先查看，再裁决。不会在打开页面时启动维护、遗忘或自动演化。',items:[['待审核候选','cg',{op:'review',action:'list'}],['审核记录','cg',{op:'review',action:'records'}],['保护统计','cg',{op:'protect',action:'stats'}],['演化摘要','cg',{op:'evolution',action:'summary'}],['维护状态','cg',{op:'sustain',action:'status'}],['审核裁决','cg',{op:'review',action:'decide',pid:'',decision:'reject'}],['节点核验','cg',{op:'verify',node_id:'',evidence:'',verdict:'confirmed'}]]}
  };
  function grouped(name) {
    const group=presets[name]; let active=0;
    $('main').innerHTML=title(group.title,group.en,group.description)+`<div class="command-tabs">${group.items.map(([label],i)=>`<button class="chip ${i===0?'active':''}" data-preset="${i}">${label}</button>`).join('')}</div><div id="permission"></div><section class="panel"><div class="panel-head"><h3 id="command-title"></h3><span class="badge" id="command-tool"></span></div><div class="panel-body"><div id="preset-fields" class="form-grid"></div><details><summary>原始调用参数</summary><textarea class="raw-args" id="preset-json" aria-label="原始调用参数"></textarea></details><div class="actions"><button id="preset-help" class="button">查看帮助</button><button id="preset-run" class="button primary">执行查询</button></div></div></section><div id="result"></div>`;
    function select(i) {
      active=i; const [label,tool,args]=group.items[i]; $('command-title').textContent=label; $('command-tool').textContent=tool+' · '+args.op;
      document.querySelectorAll('[data-preset]').forEach(b=>b.classList.toggle('active',Number(b.dataset.preset)===i)); $('permission').innerHTML=tool==='cg'?permissionNote(args.op):''; $('preset-json').value=json(args); $('result').innerHTML='';
      $('preset-run').textContent=needsConfirm(tool,args)?'检查并执行':'执行查询';
      $('preset-fields').innerHTML=Object.entries(args).filter(([k])=>!['op','action','limit','desc'].includes(k)).map(([k,v])=>`<label>${esc(fieldLabel(k))}<${typeof v==='string'&&['plan','evidence','acceptance','goal'].includes(k)?'textarea':'input'} data-preset-field="${esc(k)}" ${typeof v==='number'?'type="number" step="any"':''} ${Array.isArray(v)?'placeholder="JSON 数组"':''} ${typeof v==='string'&&['plan','evidence','acceptance','goal'].includes(k)?'':`value="${esc(typeof v==='object'?json(v):v)}"`}>${typeof v==='string'&&['plan','evidence','acceptance','goal'].includes(k)?esc(v):''}</${typeof v==='string'&&['plan','evidence','acceptance','goal'].includes(k)?'textarea':'input'}></label>`).join('') || '<p class="hint">无需额外参数。点击执行，读取真实数据。</p>';
      document.querySelectorAll('[data-preset-field]').forEach(input=>input.oninput=()=>{try{const next=JSON.parse($('preset-json').value),key=input.dataset.presetField,old=args[key];next[key]=typeof old==='number'?Number(input.value):typeof old==='object'?JSON.parse(input.value):input.value;$('preset-json').value=json(next);}catch{/* 继续保留用户编辑 */}});
    }
    document.querySelectorAll('[data-preset]').forEach(b=>b.onclick=()=>select(Number(b.dataset.preset)));
    $('preset-run').onclick=async e=> { try { const args=JSON.parse($('preset-json').value); await execute(e.currentTarget,group.items[active][1],args); }catch(err){$('result').innerHTML=errorHTML(err);} };
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
    try { meta=await fetchJSON('/plugins/lingshu/meta');$('connection').textContent=meta.ready?'大脑已连接':'大脑未就绪';$('connection').classList.toggle('online',meta.ready);$('identity').textContent=meta.identity+' · '+meta.tools.length+' 个工具'; await navigate(location.hash.slice(1)||page); }
    catch(e){meta=null;$('connection').textContent='连接失败';$('connection').classList.remove('online');$('main').innerHTML=errorHTML(e);}
    finally{$('refresh').disabled=false;}
  }
  $('nav').innerHTML=pages.map(([id,icon,label])=>`<button class="nav-item" data-nav="${id}"><span class="nav-icon" aria-hidden="true">${icon}</span>${label}</button>`).join('');
  document.querySelectorAll('[data-nav]').forEach(b=>b.onclick=()=>navigate(b.dataset.nav)); $('refresh').onclick=boot; $('close-detail').onclick=()=>$('detail').close();
  let theme='';try{theme=localStorage.getItem('lingshu.theme')||'';}catch{} if(theme)document.documentElement.dataset.theme=theme;else if(matchMedia('(prefers-color-scheme:dark)').matches)document.documentElement.dataset.theme='dark';
  $('theme').onclick=()=>{const next=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=next;try{localStorage.setItem('lingshu.theme',next);}catch{}};
  window.addEventListener('hashchange',()=>navigate(location.hash.slice(1))); void boot();
})();
