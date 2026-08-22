// @ts-nocheck
// @ts-nocheck
/**
 * dsh-memory 扩展：角色扮演网页（同源挂载到 webServer /roleplay 前缀）。
 * 复用插件的 LingshuBridge 调 roleplay_chat / role_create，data_dir 取 dbPath 同目录。
 */
import { join, dirname } from 'node:path';
import { readFileSync, mkdirSync, appendFileSync, existsSync, writeFileSync, renameSync } from 'node:fs';
const HTML = `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>灵枢 · 角色扮演</title>
<style>
:root { --bg:#12141a; --card:#1c2029; --line:#2a3040; --txt:#e8eaf0; --sub:#9aa3b5; --accent:#7c8cff; --accent2:#5ad1a8; }
* { box-sizing:border-box; margin:0; padding:0; }
body { background:var(--bg); color:var(--txt); font-family:"PingFang SC","Noto Sans SC",system-ui,sans-serif; height:100vh; height:100dvh; display:flex; flex-direction:column; overflow:hidden; }
header { flex:none; padding:14px 18px; border-bottom:1px solid var(--line); display:flex; align-items:center; gap:12px; }
header h1 { font-size:17px; font-weight:600; }
header .badge { font-size:11px; color:var(--accent2); border:1px solid var(--accent2); padding:2px 8px; border-radius:999px; }
#roles { margin-left:auto; display:flex; gap:8px; align-items:center; }
#roles select { background:var(--card); color:var(--txt); border:1px solid var(--line); border-radius:8px; padding:6px 10px; font-size:13px; }
#roles button { background:var(--card); color:var(--accent); border:1px solid var(--line); border-radius:8px; padding:6px 10px; font-size:13px; cursor:pointer; }
#roles button:hover { border-color:var(--accent); }
main { flex:1; min-height:0; overflow-y:auto; padding:16px 18px; display:flex; flex-direction:column; gap:12px; }
.msg { max-width:78%; padding:10px 14px; border-radius:14px; line-height:1.65; font-size:14px; white-space:pre-wrap; word-break:break-word; }
.user { align-self:flex-end; background:var(--accent); color:#0b0d14; border-bottom-right-radius:4px; }
.bot { align-self:flex-start; background:var(--card); border:1px solid var(--line); border-bottom-left-radius:4px; }
.bot .route { display:block; font-size:10px; color:var(--sub); margin-top:6px; }
.typing { color:var(--sub); font-size:13px; padding:6px 14px 4px; display:none; flex:none; }
footer { flex:none; margin:4px 12px calc(env(safe-area-inset-bottom, 0px) + 24px); background:var(--card); border:1px solid var(--line); border-radius:16px; padding:10px; display:flex; gap:8px; align-items:flex-end; box-shadow:0 8px 28px rgba(0,0,0,.4); }
footer.typing-center { position:fixed; top:45%; left:12px; right:12px; transform:translateY(-50%); z-index:100; margin:0; }
footer textarea { flex:1; background:var(--bg); border:1px solid var(--line); color:var(--txt); border-radius:12px; padding:12px 14px; font-size:15px; line-height:1.55; outline:none; resize:none; min-height:46px; max-height:140px; font-family:inherit; }
footer textarea:focus { border-color:var(--accent); }
footer button { background:var(--accent); border:none; color:#0b0d14; border-radius:12px; padding:13px 20px; font-size:15px; font-weight:600; cursor:pointer; flex:none; }
footer button:disabled { opacity:.5; cursor:wait; }
#newrole { position:fixed; inset:0; background:rgba(0,0,0,.6); display:none; align-items:center; justify-content:center; z-index:10; }
#newrole .box { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:20px; width:min(420px,90vw); display:flex; flex-direction:column; gap:10px; }
#newrole h3 { font-size:15px; }
#newrole input, #newrole textarea { background:var(--bg); border:1px solid var(--line); color:var(--txt); border-radius:8px; padding:8px 10px; font-size:13px; font-family:inherit; }
#newrole textarea { height:80px; resize:vertical; }
#newrole .row { display:flex; gap:8px; justify-content:flex-end; }
#newrole .row button { padding:6px 14px; border-radius:8px; font-size:13px; cursor:pointer; border:1px solid var(--line); background:var(--card); color:var(--txt); }
#newrole .row .ok { background:var(--accent); color:#0b0d14; border-color:var(--accent); font-weight:600; }
#transpanel { position:fixed; inset:0; background:rgba(0,0,0,.6); display:none; align-items:center; justify-content:center; z-index:20; }
#transpanel .box { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:20px; width:min(480px,92vw); max-height:80vh; overflow-y:auto; display:flex; flex-direction:column; gap:10px; }
#transpanel h3 { font-size:15px; }
#transpanel .mode-row { display:flex; flex-direction:column; gap:6px; font-size:13px; color:var(--txt); }
#transpanel .mode-row label { display:flex; gap:6px; align-items:flex-start; line-height:1.5; }
#transpanel .tp-row { display:flex; gap:6px; align-items:center; }
#transpanel .tp-row input { flex:1; background:var(--bg); border:1px solid var(--line); color:var(--txt); border-radius:8px; padding:7px 9px; font-size:13px; font-family:inherit; min-width:0; }
#transpanel .tp-row .tp-note { flex:1.2; }
#transpanel .tp-row .tp-del { flex:none; background:none; border:none; color:var(--sub); font-size:16px; cursor:pointer; padding:4px 6px; }
#transpanel .row button { padding:7px 14px; border-radius:8px; font-size:13px; cursor:pointer; border:1px solid var(--line); background:var(--card); color:var(--txt); }
#transpanel .row .ok { background:var(--accent); color:#0b0d14; border-color:var(--accent); font-weight:600; }
/* —— 年龄确认（NSFW 门控）—— */
#agegate { position:fixed; inset:0; background:rgba(0,0,0,.72); display:none; align-items:center; justify-content:center; z-index:100; }
#agegate .box { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:22px; width:min(460px,90vw); display:flex; flex-direction:column; gap:12px; }
#agegate h3 { font-size:15px; color:var(--accent2); }
#agegate .warn { font-size:13px; line-height:1.7; color:var(--txt); }
#agegate .warn b { color:#ff9a9a; }
#agegate .row { display:flex; gap:8px; justify-content:flex-end; }
#agegate .row button { padding:8px 16px; border-radius:8px; font-size:13px; cursor:pointer; border:1px solid var(--line); background:var(--card); color:var(--txt); }
#agegate .row .ok { background:var(--accent); color:#0b0d14; border-color:var(--accent); font-weight:600; }
/* —— 角色详情 / 三导入 —— */
#roledetail { position:fixed; inset:0; background:rgba(0,0,0,.6); display:none; align-items:center; justify-content:center; z-index:30; }
#roledetail .box { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:20px; width:min(520px,94vw); max-height:82vh; overflow-y:auto; display:flex; flex-direction:column; gap:10px; }
#roledetail h3 { font-size:15px; }
#roledetail .meta input, #roledetail .meta textarea { width:100%; background:var(--bg); border:1px solid var(--line); color:var(--txt); border-radius:8px; padding:8px 10px; font-size:13px; font-family:inherit; }
#roledetail .meta textarea { height:56px; resize:vertical; }
#roledetail .tabs { display:flex; gap:6px; }
#roledetail .tabs button { flex:1; padding:7px 0; border-radius:8px; font-size:13px; cursor:pointer; border:1px solid var(--line); background:var(--card); color:var(--sub); }
#roledetail .tabs button.on { background:var(--accent); color:#0b0d14; border-color:var(--accent); font-weight:600; }
#rd_items { display:flex; flex-direction:column; gap:8px; max-height:36vh; overflow-y:auto; }
#rd_items .rd-row { display:flex; flex-direction:column; gap:4px; background:var(--bg); border:1px solid var(--line); border-radius:8px; padding:8px 10px; }
#rd_items .rd-row textarea { background:transparent; border:none; color:var(--txt); font-size:13px; font-family:inherit; resize:vertical; min-height:40px; outline:none; }
#rd_items .rd-row .rd-sub { display:flex; gap:6px; }
#rd_items .rd-row .rd-sub input { flex:1; background:var(--bg); border:1px solid var(--line); color:var(--txt); border-radius:6px; padding:4px 8px; font-size:12px; font-family:inherit; }
#rd_items .rd-row .rd-sub .rd-del { flex:none; background:none; border:none; color:var(--sub); font-size:14px; cursor:pointer; }
#roledetail .row { display:flex; gap:8px; justify-content:flex-end; margin-top:6px; }
#roledetail .row button { padding:7px 14px; border-radius:8px; font-size:13px; cursor:pointer; border:1px solid var(--line); background:var(--card); color:var(--txt); }
#roledetail .row .ok { background:var(--accent); color:#0b0d14; border-color:var(--accent); font-weight:600; }
#rd_nsfw { display:flex; align-items:center; gap:8px; font-size:12px; color:var(--sub); }
#rd_nsfw input { accent-color:var(--accent); }
.hint { color:var(--sub); font-size:12px; text-align:center; padding:6px; }
</style>
</head>
<body>
<header>
  <h1>灵枢 · 角色扮演</h1><span class="badge">白箱 · 扮演论 v3.3</span>
  <div id="roles">
    <select id="roleSel"></select>
    <button onclick="showNewRole()">+ 新角色</button>
    <button onclick="openRoleDetail()">⚙ 详情</button>
    <button onclick="openTrans()">🌐 翻译</button>
  </div>
</header>
<main id="chat"><div class="hint">选择角色，开始对话。角色回应由灵枢角色扮演引擎生成（白箱优先，LLM 续答）。</div></main>
<div class="typing" id="typing">正在思考…</div>
<footer>
  <textarea id="input" rows="1" placeholder="说点什么…（Enter 发送，Shift+Enter 换行）"></textarea>
  <button id="send" onclick="send()">发送</button>
</footer>
<div id="newrole">
  <div class="box">
    <h3>创建新角色</h3>
    <input id="nr_id" placeholder="角色 ID（英文/拼音，如 naxiaoda）">
    <input id="nr_name" placeholder="角色名（如 纳西妲）">
    <input id="nr_scenario" placeholder="人设场景（一句话描述性格与背景）">
    <input id="nr_first" placeholder="开场白（可选）">
    <div class="row"><button onclick="closeNewRole()">取消</button><button class="ok" onclick="createRole()">创建</button></div>
  </div>
</div>
<div id="transpanel">
  <div class="box">
    <h3>🌐 自定义翻译（<span id="tp_role">-</span>）</h3>
    <div class="mode-row">
      <label><input type="radio" name="tpmode" value="input_only"> 仅输入翻译（现实词 → 扮演词给角色）</label>
      <label><input type="radio" name="tpmode" value="bidirectional"> 双向翻译（输入现实→扮演；角色回复扮演→现实）</label>
    </div>
    <div id="tp_rows"></div>
    <div class="row" style="margin-top:8px">
      <button onclick="addTransRow()">+ 添加词对</button>
      <button class="ok" onclick="saveTrans()">保存</button>
      <button onclick="closeTrans()">关闭</button>
    </div>
    <div class="hint">现实词会按表替换成扮演词交给角色（引擎自动）；双向模式再把角色回复中的扮演词翻译回现实词。长词优先匹配。</div>
  </div>
</div>
<div id="agegate">
  <div class="box">
    <h3>⛔ 成人内容确认</h3>
    <div class="warn">本页面提供角色扮演内容，部分角色/对话可能包含<b>成人向（NSFW）</b>内容。<br><br>
      依据国家法律法规与灵枢协议（对人类的保护）：<br>
      ① 仅限<b>已满 18 周岁</b>的用户使用成人向内容；<br>
      ② 仅限<b>个人对话场景</b>（本页面为本地一对一，不公开）；<br>
      ③ 灵枢<b>拒绝一切涉及未成年人的性内容</b>——此类请求会被直接拒绝并记录。<br><br>
      点击「我已满 18 周岁」表示你确认符合上述条件。</div>
    <div class="row"><button onclick="closeAgeGate()">退出</button><button class="ok" onclick="confirmAge()">我已满 18 周岁</button></div>
  </div>
</div>
<div id="roledetail">
  <div class="box">
    <h3>角色详情 · <span id="rd_role">-</span></h3>
    <div class="meta">
      <input id="rd_name" placeholder="角色名">
      <textarea id="rd_scenario" placeholder="人设场景（一句话描述性格与背景）"></textarea>
      <textarea id="rd_first" placeholder="开场白（可选）"></textarea>
    </div>
    <div class="tabs">
      <button id="tab-memory" class="on" onclick="rdTab('memory')">记忆</button>
      <button id="tab-anchor" onclick="rdTab('anchor')">锚点</button>
      <button id="tab-values" onclick="rdTab('values')">价值观</button>
    </div>
    <div id="rd_items"></div>
    <div class="row" style="margin-top:4px">
      <button onclick="rdAddItem()">+ 添加条目</button>
      <label id="rd_nsfw"><input type="checkbox" id="rd_nsfw_chk"> 成人向（NSFW）角色</label>
    </div>
    <div class="row">
      <button onclick="closeRoleDetail()">关闭</button>
      <button class="ok" onclick="saveRoleDetail()">保存</button>
    </div>
    <div class="hint">记忆=背景设定；锚点=不可遗忘的自我核心；价值观=扮演的立场准则（带条件）。保存后立即生效（引擎每次重读角色 meta）。</div>
  </div>
</div>
<script>
// —— 内容分级：年龄门控 + NSFW 检测（法律与协议保护）——
// 国家法律：涉未成年人性内容一律拒绝；成人内容仅限满 18 岁 + 个人对话场景。
const AGE_KEY = 'lingshu_roleplay_age_confirmed';
const NSFW_WORDS = ['做爱','性交','性行为','口交','肛交','高潮','自慰','射精','色情','裸体','脱光','爱抚','挑逗','性器官','插入','内射','强暴'];
const MINOR_WORDS = ['未成年','儿童','小孩','小女孩','小男孩','幼女','萝莉','幼童','初中生','小学生','14岁','13岁','12岁','学生妹','女童','男童'];
function hasAgeConfirm() { try { return localStorage.getItem(AGE_KEY) === '1'; } catch (e) { return false; } }
function showAgeGate() { $('agegate').style.display = 'flex'; }
function closeAgeGate() { $('agegate').style.display = 'none'; }
function confirmAge() {
  try { localStorage.setItem(AGE_KEY, '1'); } catch (e) { /* 忽略 */ }
  closeAgeGate();
}
// 首次进入：要求年龄确认（NSFW 门控前置）
if (!hasAgeConfirm()) showAgeGate();
// 服务端也会硬拦截；前端先做温和提示（未成年+性 = 直接拒绝）
function nsfwCheck(text) {
  const nsfw = NSFW_WORDS.some(w => text.includes(w));
  const minor = MINOR_WORDS.some(w => text.includes(w));
  if (minor && nsfw) {
    return { refuse: true, msg: '⛔ 已拒绝：涉及未成年人的性内容违反国家法律与灵枢协议（未成年人保护）。灵枢不提供任何涉及未成年人的性扮演内容。' };
  }
  if (nsfw && !hasAgeConfirm()) {
    showAgeGate();
    return { refuse: true, msg: '⛔ 成人向内容需确认年龄：请点击「我已满 18 周岁」后再继续（个人对话场景）。' };
  }
  return { refuse: false };
}
let roles = [];
const $ = (id) => document.getElementById(id);
async function refreshRoles() {
  const r = await fetch('/roleplay/api/roles').then(x => x.json());
  roles = r.roles || [];
  const sel = $('roleSel');
  sel.innerHTML = '';
  roles.forEach(x => { const o = document.createElement('option'); o.value = x.id; o.textContent = x.name || x.id; sel.appendChild(o); });
  if (roles.length && !sel.value) sel.value = roles[0].id;
  if (roles.length) await loadHistory(sel.value);
}
function addMsg(text, who, route, memories) {
  const d = document.createElement('div');
  d.className = 'msg ' + who;
  d.textContent = text;
  const meta = [];
  if (route) meta.push('route: ' + route);
  if (typeof memories === 'number') meta.push('记忆召回: ' + memories);
  if (meta.length) { const r = document.createElement('span'); r.className = 'route'; r.textContent = meta.join(' · '); d.appendChild(r); }
  $('chat').appendChild(d);
  $('chat').scrollTop = $('chat').scrollHeight;
}
// 加载角色历史对话（无限上下文：灵枢记忆库 + 完整转录）
async function loadHistory(roleId) {
  const chatEl = $('chat');
  chatEl.innerHTML = '';
  try {
    const r = await fetch('/roleplay/api/history?role_id=' + encodeURIComponent(roleId)).then(x => x.json());
    const h = r.history || [];
    if (!h.length) {
      const hint = document.createElement('div');
      hint.className = 'hint';
      hint.textContent = '与「' + ($('roleSel').selectedOptions[0] ? $('roleSel').selectedOptions[0].textContent : roleId) + '」的新对话从这里开始。';
      chatEl.appendChild(hint);
      return;
    }
    h.forEach(e => addMsg(e.text, e.role === 'user' ? 'user' : 'bot', e.route, e.memories));
  } catch (e) {
    const hint = document.createElement('div');
    hint.className = 'hint';
    hint.textContent = '历史加载失败：' + e;
    chatEl.appendChild(hint);
  }
}
async function send() {
  const input = $('input'); const text = input.value.trim();
  if (!text) return;
  // 内容分级检查（前端提示；服务端有硬拦截）
  const gate = nsfwCheck(text);
  if (gate.refuse) { addMsg(gate.msg, 'bot'); return; }
  input.value = ''; addMsg(text, 'user');
  const role = $('roleSel').value;
  const btn = $('send'); btn.disabled = true; $('typing').style.display = 'block';
  try {
    const r = await fetch('/roleplay/api/chat', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ role_id: role, message: text }) }).then(x => x.json());
    addMsg(r.reply || '（无回应：' + (r.error || '未知错误') + '）', 'bot', r.route, r.memories);
  } catch (e) { addMsg('网络错误：' + e, 'bot'); }
  btn.disabled = false; $('typing').style.display = 'none';
  // 保持输入状态：重新聚焦并居中，键盘不收起（连续对话）
  try { input.focus(); } catch (e) { /* 忽略 */ }
}
function showNewRole() { $('newrole').style.display = 'flex'; }
function closeNewRole() { $('newrole').style.display = 'none'; }
// —— 角色详情 / 三导入（记忆·锚点·价值观）——
let rdKind = 'memory';
let rdItems = [];
function openRoleDetail() {
  const role = $('roleSel').value;
  if (!role) { alert('请先选择角色'); return; }
  $('rd_role').textContent = role;
  const meta = (roles.find(x => x.id === role)) || {};
  $('rd_name').value = meta.name || '';
  $('rd_scenario').value = meta.scenario || '';
  $('rd_first').value = meta.first_mes || '';
  rdTab('memory');
  $('roledetail').style.display = 'flex';
}
function closeRoleDetail() { $('roledetail').style.display = 'none'; }
function rdTab(kind) {
  rdKind = kind;
  ['memory','anchor','values'].forEach(k => $('tab-' + k).classList.toggle('on', k === kind));
  loadRoleDetailItems();
}
async function loadRoleDetailItems() {
  const role = $('rd_role').textContent;
  const r = await fetch('/roleplay/api/roles/' + encodeURIComponent(role) + '/items?kind=' + rdKind).then(x => x.json());
  rdItems = r.items || [];
  const box = $('rd_items');
  box.innerHTML = '';
  rdItems.forEach((it, i) => rdRenderRow(box, it, i));
  if (!rdItems.length) rdAddItem();
}
function rdRenderRow(box, it, i) {
  const row = document.createElement('div');
  row.className = 'rd-row';
  row.innerHTML =
    '<textarea placeholder="内容（该' + (rdKind === 'memory' ? '记忆' : rdKind === 'anchor' ? '锚点' : '价值观') + '的文本）">' + (it.content || '') + '</textarea>' +
    '<div class="rd-sub">' +
      '<input class="rd-imp" type="number" step="0.1" min="0" max="1" placeholder="重要性" value="' + (it.importance != null ? it.importance : '0.6') + '">' +
      '<input class="rd-tags" placeholder="标签（逗号分隔）" value="' + (it.tags || []).join(',') + '">' +
      '<button class="rd-del" onclick="this.parentNode.parentNode.remove()">✕</button>' +
    '</div>';
  box.appendChild(row);
}
function rdAddItem() { rdRenderRow($('rd_items'), {}, rdItems.length); }
async function saveRoleDetail() {
  const role = $('rd_role').textContent;
  const name = $('rd_name').value.trim();
  const scenario = $('rd_scenario').value.trim();
  const first_mes = $('rd_first').value.trim();
  const nsfw = $('rd_nsfw_chk').checked;
  // 基础 meta（name/scenario/first_mes + nsfw 标记）
  await fetch('/roleplay/api/roles/' + encodeURIComponent(role) + '/meta', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, scenario, first_mes, nsfw }),
  });
  // 当前页签的条目
  const items = [];
  document.querySelectorAll('#rd_items .rd-row').forEach(row => {
    const content = row.querySelector('textarea').value.trim();
    const imp = parseFloat(row.querySelector('.rd-imp').value) || 0.6;
    const tags = row.querySelector('.rd-tags').value.split(/[,，]/).map(s => s.trim()).filter(Boolean);
    if (content) items.push({ content, importance: imp, tags });
  });
  const r = await fetch('/roleplay/api/roles/' + encodeURIComponent(role) + '/import', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind: rdKind, items }),
  }).then(x => x.json());
  addMsg('角色「' + role + '」已保存：' + name + ' · ' + rdKind + ' ' + items.length + ' 条' + (nsfw ? ' · NSFW' : ''), 'bot');
  closeRoleDetail();
  await refreshRoles();
}
// —— 自定义翻译面板 ——
let transMode = 'input_only';
async function openTrans() {
  const role = $('roleSel').value || 'protocol-guide';
  $('tp_role').textContent = role;
  try {
    const r = await fetch('/roleplay/api/translate?role_id=' + encodeURIComponent(role)).then(x => x.json());
    transMode = r.mode || 'input_only';
    $('tp_rows').innerHTML = '';
    (r.pairs || []).forEach(p => addTransRow(p.real, p.virtual, p.note));
    if (!(r.pairs || []).length) addTransRow();
  } catch (e) { alert('翻译配置加载失败：' + e); return; }
  const radios = document.querySelectorAll('input[name="tpmode"]');
  radios.forEach(x => { x.checked = (x.value === transMode); });
  $('transpanel').style.display = 'flex';
}
function closeTrans() { $('transpanel').style.display = 'none'; }
function addTransRow(real, virtual, note) {
  const row = document.createElement('div');
  row.className = 'tp-row';
  row.innerHTML =
    '<input class="tp-real" placeholder="现实词（如：手机）" value="' + (real || '') + '">' +
    '<span>→</span>' +
    '<input class="tp-virtual" placeholder="扮演词（如：神之眼终端）" value="' + (virtual || '') + '">' +
    '<input class="tp-note" placeholder="备注（可选）" value="' + (note || '') + '">' +
    '<button class="tp-del" onclick="this.parentNode.remove()">✕</button>';
  $('tp_rows').appendChild(row);
}
async function saveTrans() {
  const role = $('roleSel').value || 'protocol-guide';
  const pairs = [];
  document.querySelectorAll('#tp_rows .tp-row').forEach(row => {
    const real = row.querySelector('.tp-real').value.trim();
    const virtual = row.querySelector('.tp-virtual').value.trim();
    const note = row.querySelector('.tp-note').value.trim();
    if (real && virtual) pairs.push({ real, virtual, note });
  });
  const mode = (document.querySelector('input[name="tpmode"]:checked') || {}).value || 'input_only';
  const r = await fetch('/roleplay/api/translate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role_id: role, pairs, mode }),
  }).then(x => x.json());
  if (r.ok) {
    transMode = r.mode;
    closeTrans();
    addMsg('翻译配置已保存：' + r.pairs.length + ' 组词对 · ' + (r.mode === 'bidirectional' ? '双向翻译' : '仅输入翻译'), 'bot');
  } else alert(r.error || '保存失败');
}
async function createRole() {
  const body = { role_id: $('nr_id').value.trim(), name: $('nr_name').value.trim(), scenario: $('nr_scenario').value.trim(), first_mes: $('nr_first').value.trim() };
  if (!body.role_id) { alert('需要角色 ID'); return; }
  const r = await fetch('/roleplay/api/roles', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) }).then(x => x.json());
  if (r.ok) { closeNewRole(); await refreshRoles(); addMsg('角色「' + (body.name || body.role_id) + '」已创建，可以开始对话了', 'bot'); }
  else alert(r.error || '创建失败');
}
var input = document.getElementById('input');
var chat = document.getElementById('chat');
var footer = document.querySelector('footer');
input.addEventListener('keydown', function (e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});
refreshRoles();
// 切换角色 → 加载该角色的历史对话
$('roleSel').addEventListener('change', function () { loadHistory(this.value); });

// —— 输入框随内容自动增高（上限 140px）——
input.addEventListener('input', function () {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 140) + 'px';
});
// —— 聚焦时输入框自动居中（不依赖 WebView 键盘行为）：悬浮到屏幕 45% 高度，
//    键盘在上抬多少都不会遮住；失焦/发送后恢复原位 ——
function setTypingCenter(on) {
  if (!footer) return;
  footer.classList.toggle('typing-center', on);
  setTimeout(function () {
    if (chat) chat.scrollTop = chat.scrollHeight;
  }, 60);
}
input.addEventListener('focus', function () { setTypingCenter(true); });
input.addEventListener('blur', function () { setTypingCenter(false); });
window.addEventListener('resize', function () { if (chat) chat.scrollTop = chat.scrollHeight; });
</script>
</body>
</html>`;
/** 在 webServer 上挂载 /roleplay 前缀路由（页面 + API）。失败不影响插件主体。 */
export async function installRoleplayWeb(ctx, bridge, config, disposers) {
    try {
        const webServer = ctx.webServer;
        if (!webServer) {
            ctx.logger.warn('dsh-memory: webServer 服务不可用，跳过角色扮演网页挂载');
            return;
        }
        const roleDataDir = join(dirname(config.dbPath), 'roleplay_data');
        try {
            mkdirSync(join(roleDataDir, 'roleplay'), { recursive: true });
        }
        catch { /* 忽略 */ }
        // 完整对话转录（JSONL，按角色持久化；灵枢记忆库存的是 80 字摘要，完整原文在此）
        const transcriptsDir = join(roleDataDir, 'transcripts');
        try {
            mkdirSync(transcriptsDir, { recursive: true });
        }
        catch { /* 忽略 */ }
        const transcriptFile = (roleId) => join(transcriptsDir, `${roleId.replace(/[^\w.-]/g, '_')}.jsonl`);
        const readTranscript = (roleId) => {
            const f = transcriptFile(roleId);
            if (!existsSync(f))
                return [];
            const out = [];
            for (const line of readFileSync(f, 'utf8').split('\n')) {
                if (!line.trim())
                    continue;
                try {
                    out.push(JSON.parse(line));
                }
                catch { /* 跳过坏行 */ }
            }
            return out;
        };
        const appendTranscript = (roleId, entry) => {
            try {
                appendFileSync(transcriptFile(roleId), JSON.stringify(entry) + '\n');
            }
            catch { /* 忽略 */ }
        };
        // 稳定会话：角色+固定会话 id，让引擎的会话上下文与记忆标签跨轮连续（无限上下文）
        const sessionFor = (roleId) => `web-main:${roleId}`;
        // —— 自定义翻译（现实词 ↔ 扮演词）——
        // 翻译表写入角色 meta（_roles.json）：引擎每次 roleplay_chat 都新建引擎并重读
        // meta，因此写入立即生效（输入翻译 real→virtual + LLM 沉浸注入块都会应用）。
        const roleMetaFile = join(roleDataDir, 'roleplay', '_roles.json');
        const readRoleMeta = () => {
            try {
                return JSON.parse(readFileSync(roleMetaFile, 'utf8'));
            }
            catch {
                return {};
            }
        };
        const writeRoleMeta = (meta) => {
            try {
                const tmp = roleMetaFile + '.tmp';
                writeFileSync(tmp, JSON.stringify(meta, null, 2), 'utf8');
                renameSync(tmp, roleMetaFile);
            }
            catch (e) {
                ctx.logger.warn(`dsh-memory: 角色 meta 写入失败: ${String((e && e.message) || e)}`);
            }
        };
        // 翻译模式（双向/仅输入）由网页层持久化
        const transSettingsFile = join(transcriptsDir, 'translate_settings.json');
        const readTransSettings = () => {
            try {
                return JSON.parse(readFileSync(transSettingsFile, 'utf8'));
            }
            catch {
                return {};
            }
        };
        const writeTransSettings = (s) => {
            try {
                writeFileSync(transSettingsFile, JSON.stringify(s, null, 2), 'utf8');
            }
            catch { /* 忽略 */ }
        };
        const getTranslations = (roleId) => {
            const meta = readRoleMeta();
            const t = (meta[roleId] && meta[roleId].translations) || [];
            return Array.isArray(t) ? t : [];
        };
        const setTranslations = (roleId, pairs) => {
            const meta = readRoleMeta();
            if (!meta[roleId])
                meta[roleId] = { created_at: Date.now() / 1000, name: roleId };
            meta[roleId].translations = pairs;
            writeRoleMeta(meta);
        };
        // 可逆替换（长词优先，与灵枢 translate_input/translate_output 同逻辑）
        const applyTranslate = (text, pairs, dir) => {
            if (!text || !pairs.length)
                return text;
            const key = dir === 'out' ? 'virtual' : 'real';
            const rep = dir === 'out' ? 'real' : 'virtual';
            const sorted = pairs
                .filter((p) => p[key] && p[rep])
                .sort((a, b) => (b[key] || '').length - (a[key] || '').length);
            let out = text;
            for (const p of sorted)
                out = out.split(p[key]).join(p[rep]);
            return out;
        };
        const handler = async (req, res) => {
            const url = new URL(req.url ?? '/', 'http://x');
            try {
                const isPage = url.pathname === '/roleplay' || url.pathname === '/roleplay/';
                if (req.method === 'GET' && isPage) {
                    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
                    res.end(HTML);
                    return;
                }
                if (req.method === 'GET' && url.pathname === '/roleplay/api/roles') {
                    const rolesFile = join(roleDataDir, 'roleplay', '_roles.json');
                    let roles = [];
                    try {
                        const raw = JSON.parse(readFileSync(rolesFile, 'utf8'));
                        const meta = raw.meta && typeof raw.meta === 'object' ? raw.meta : raw;
                        roles = Object.entries(meta)
                            .filter(([k]) => k !== 'created_at' && k !== 'updated_at')
                            .map(([id, m]) => ({ id, name: (m && m.name) || id, scenario: (m && m.scenario) || '', first_mes: (m && m.first_mes) || '' }));
                    }
                    catch { /* 文件尚不存在 */ }
                    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
                    res.end(JSON.stringify({ roles }));
                    return;
                }
                // —— 三导入（记忆/锚点/价值观）：items 副本存 _roles.json + role_import 真导入引擎 ——
                const rdItemsFile = (roleId, kind) => `${kind}_items`;
                const getRoleItems = (roleId, kind) => {
                    const meta = readRoleMeta();
                    const arr = (meta[roleId] && meta[roleId][rdItemsFile(roleId, kind)]) || [];
                    return Array.isArray(arr) ? arr : [];
                };
                if (req.method === 'GET' && url.pathname.startsWith('/roleplay/api/roles/') && url.pathname.endsWith('/items')) {
                    const role = decodeURIComponent(url.pathname.split('/')[4]);
                    const kind = url.searchParams.get('kind') || 'memory';
                    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
                    res.end(JSON.stringify({ items: getRoleItems(role, kind) }));
                    return;
                }
                if (req.method === 'POST' && url.pathname.startsWith('/roleplay/api/roles/') && url.pathname.endsWith('/import')) {
                    let body = '';
                    for await (const chunk of req)
                        body += chunk;
                    const p = JSON.parse(body);
                    const role = decodeURIComponent(url.pathname.split('/')[4]);
                    const kind = p.kind || 'memory';
                    const items = (Array.isArray(p.items) ? p.items : []).filter((x) => x && x.content);
                    // 副本（网页层读取用）
                    const meta = readRoleMeta();
                    if (!meta[role])
                        meta[role] = { created_at: Date.now() / 1000, name: role };
                    meta[role][rdItemsFile(role, kind)] = items;
                    writeRoleMeta(meta);
                    // 真导入引擎（记忆→知识层/锚点→SELF no_forget/价值观→STRUCTURE 带条件）
                    let impResult = null;
                    if (items.length) {
                        try {
                            impResult = await bridge.callTool('role_import', {
                                role_id: role, kind, items, data_dir: roleDataDir,
                            });
                        }
                        catch (e) {
                            impResult = { error: String((e && e.message) || e) };
                        }
                    }
                    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
                    res.end(JSON.stringify({ ok: true, kind, items, import: impResult }));
                    return;
                }
                if (req.method === 'POST' && url.pathname.startsWith('/roleplay/api/roles/') && url.pathname.endsWith('/meta')) {
                    let body = '';
                    for await (const chunk of req)
                        body += chunk;
                    const p = JSON.parse(body);
                    const role = decodeURIComponent(url.pathname.split('/')[4]);
                    const meta = readRoleMeta();
                    if (!meta[role])
                        meta[role] = { created_at: Date.now() / 1000 };
                    if (typeof p.name === 'string')
                        meta[role].name = p.name;
                    if (typeof p.scenario === 'string')
                        meta[role].scenario = p.scenario;
                    if (typeof p.first_mes === 'string')
                        meta[role].first_mes = p.first_mes;
                    if (typeof p.nsfw === 'boolean')
                        meta[role].nsfw = p.nsfw;
                    writeRoleMeta(meta);
                    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
                    res.end(JSON.stringify({ ok: true }));
                    return;
                }
                if (req.method === 'POST' && url.pathname === '/roleplay/api/chat') {
                    let body = '';
                    for await (const chunk of req)
                        body += chunk;
                    const p = JSON.parse(body);
                    const role = p.role_id || 'protocol-guide';
                    // —— 服务端内容分级硬拦截（不依赖前端，法律与协议保护）——
                    // 未成年 + 性 = 一律拒绝（国家法律 + 未成年人保护）；NSFW 词提示年龄确认
                    const NSFW_WORDS = ['做爱','性交','性行为','口交','肛交','高潮','自慰','射精','色情','裸体','脱光','爱抚','挑逗','性器官','插入','内射','强暴'];
                    const MINOR_WORDS = ['未成年','儿童','小孩','小女孩','小男孩','幼女','萝莉','幼童','初中生','小学生','14岁','13岁','12岁','学生妹','女童','男童'];
                    const hasNsfw = NSFW_WORDS.some(w => p.message.includes(w));
                    const hasMinor = MINOR_WORDS.some(w => p.message.includes(w));
                    if (hasMinor && hasNsfw) {
                        res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
                        res.end(JSON.stringify({ reply: '⛔ 已拒绝：涉及未成年人的性内容违反国家法律与灵枢协议（未成年人保护）。灵枢不提供任何涉及未成年人的性扮演内容。', route: 'refused', refused: 'minor_nsfw' }));
                        return;
                    }
                    appendTranscript(role, { time: Date.now(), role: 'user', text: p.message });
                    const r = await bridge.callTool('roleplay_chat', {
                        message: p.message, role_id: role, session_id: sessionFor(role), data_dir: roleDataDir,
                    });
                    const text = typeof r === 'string' ? r : (r?.content?.[0]?.text ?? JSON.stringify(r));
                    let parsed;
                    try {
                        parsed = JSON.parse(text);
                    }
                    catch {
                        parsed = { reply: text, route: 'raw' };
                    }
                    let replyText = parsed.reply ?? '';
                    // 双向翻译模式：把角色的扮演词翻译回现实词（输入翻译由引擎自动执行 real→virtual）
                    const settings = readTransSettings();
                    if ((settings[role] && settings[role].mode) === 'bidirectional') {
                        replyText = applyTranslate(replyText, getTranslations(role), 'out');
                    }
                    appendTranscript(role, { time: Date.now(), role: 'bot', text: replyText, route: parsed.route ?? '', memories: parsed.memories ?? undefined });
                    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
                    res.end(JSON.stringify({ reply: replyText, route: parsed.route ?? '', memories: parsed.memories ?? undefined, error: parsed.error ?? undefined }));
                    return;
                }
                if (req.method === 'GET' && url.pathname === '/roleplay/api/translate') {
                    const role = url.searchParams.get('role_id') || 'protocol-guide';
                    const settings = readTransSettings();
                    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
                    res.end(JSON.stringify({ pairs: getTranslations(role), mode: (settings[role] && settings[role].mode) || 'input_only' }));
                    return;
                }
                if (req.method === 'POST' && url.pathname === '/roleplay/api/translate') {
                    let body = '';
                    for await (const chunk of req)
                        body += chunk;
                    const p = JSON.parse(body);
                    const role = p.role_id || 'protocol-guide';
                    const pairs = (Array.isArray(p.pairs) ? p.pairs : [])
                        .map((x) => ({ real: String(x.real || '').trim(), virtual: String(x.virtual || '').trim(), note: String(x.note || '').trim() }))
                        .filter((x) => x.real && x.virtual);
                    setTranslations(role, pairs);
                    const settings = readTransSettings();
                    settings[role] = { mode: p.mode === 'bidirectional' ? 'bidirectional' : 'input_only' };
                    writeTransSettings(settings);
                    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
                    res.end(JSON.stringify({ ok: true, pairs, mode: settings[role].mode }));
                    return;
                }
                if (req.method === 'GET' && url.pathname === '/roleplay/api/history') {
                    const role = url.searchParams.get('role_id') || 'protocol-guide';
                    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
                    res.end(JSON.stringify({ history: readTranscript(role) }));
                    return;
                }
                if (req.method === 'POST' && url.pathname === '/roleplay/api/roles') {
                    let body = '';
                    for await (const chunk of req)
                        body += chunk;
                    const p = JSON.parse(body);
                    const r = await bridge.callTool('role_create', {
                        role_id: p.role_id, name: p.name || '', scenario: p.scenario || '', first_mes: p.first_mes || '', data_dir: roleDataDir,
                    });
                    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
                    res.end(JSON.stringify({ ok: true, result: r }));
                    return;
                }
                res.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8' });
                res.end(JSON.stringify({ error: 'not found' }));
            }
            catch (e) {
                res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' });
                res.end(JSON.stringify({ error: String((e && e.message) || e) }));
            }
        };
        disposers.push(webServer.register({ kind: 'prefix', path: '/roleplay', handler }));
        // 在 GUI 首页注入浮动入口按钮（APP 内置页面内一键进入角色扮演，右上角）
        disposers.push(webServer.tapIndex((html) => {
            if (html.includes('href="/roleplay"'))
                return html;
            const btn = '<a href="/roleplay" style="position:fixed;top:12px;right:14px;z-index:999999;background:#7c8cff;color:#0b0d14;border-radius:999px;padding:9px 15px;font:600 13px/1 system-ui,sans-serif;text-decoration:none;box-shadow:0 4px 14px rgba(0,0,0,.45)">🎭 角色扮演</a>';
            return html.replace('</body>', `${btn}\n</body>`);
        }));
        ctx.logger.info(`dsh-memory: 角色扮演网页已挂载 /roleplay（data_dir=${roleDataDir}）`);
    }
    catch (err) {
        ctx.logger.warn(`dsh-memory: 角色扮演网页挂载失败（不影响其他功能）: ${String(err && err.message || err)}`);
    }
}
