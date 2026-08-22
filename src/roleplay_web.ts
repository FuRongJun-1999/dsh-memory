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
.hint { color:var(--sub); font-size:12px; text-align:center; padding:6px; }
</style>
</head>
<body>
<header>
  <h1>灵枢 · 角色扮演</h1><span class="badge">白箱 · 扮演论 v3.3</span>
  <div id="roles">
    <select id="roleSel"></select>
    <button onclick="showNewRole()">+ 新角色</button>
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
<script>
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
    try { mkdirSync(join(roleDataDir, 'roleplay'), { recursive: true }); } catch { /* 忽略 */ }
    // 完整对话转录（JSONL，按角色持久化；灵枢记忆库存的是 80 字摘要，完整原文在此）
    const transcriptsDir = join(roleDataDir, 'transcripts');
    try { mkdirSync(transcriptsDir, { recursive: true }); } catch { /* 忽略 */ }
    const transcriptFile = (roleId) => join(transcriptsDir, `${roleId.replace(/[^\w.-]/g, '_')}.jsonl`);
    const readTranscript = (roleId) => {
      const f = transcriptFile(roleId);
      if (!existsSync(f)) return [];
      const out = [];
      for (const line of readFileSync(f, 'utf8').split('\n')) {
        if (!line.trim()) continue;
        try { out.push(JSON.parse(line)); } catch { /* 跳过坏行 */ }
      }
      return out;
    };
    const appendTranscript = (roleId, entry) => {
      try { appendFileSync(transcriptFile(roleId), JSON.stringify(entry) + '\n'); } catch { /* 忽略 */ }
    };
    // 稳定会话：角色+固定会话 id，让引擎的会话上下文与记忆标签跨轮连续（无限上下文）
    const sessionFor = (roleId) => `web-main:${roleId}`;

    // —— 自定义翻译（现实词 ↔ 扮演词）——
    // 翻译表写入角色 meta（_roles.json）：引擎每次 roleplay_chat 都新建引擎并重读
    // meta，因此写入立即生效（输入翻译 real→virtual + LLM 沉浸注入块都会应用）。
    const roleMetaFile = join(roleDataDir, 'roleplay', '_roles.json');
    const readRoleMeta = () => {
      try { return JSON.parse(readFileSync(roleMetaFile, 'utf8')); } catch { return {}; }
    };
    const writeRoleMeta = (meta) => {
      try {
        const tmp = roleMetaFile + '.tmp';
        writeFileSync(tmp, JSON.stringify(meta, null, 2), 'utf8');
        renameSync(tmp, roleMetaFile);
      } catch (e) { ctx.logger.warn(`dsh-memory: 角色 meta 写入失败: ${String((e && e.message) || e)}`); }
    };
    // 翻译模式（双向/仅输入）由网页层持久化
    const transSettingsFile = join(transcriptsDir, 'translate_settings.json');
    const readTransSettings = () => {
      try { return JSON.parse(readFileSync(transSettingsFile, 'utf8')); } catch { return {}; }
    };
    const writeTransSettings = (s) => {
      try { writeFileSync(transSettingsFile, JSON.stringify(s, null, 2), 'utf8'); } catch { /* 忽略 */ }
    };
    const getTranslations = (roleId) => {
      const meta = readRoleMeta();
      const t = (meta[roleId] && meta[roleId].translations) || [];
      return Array.isArray(t) ? t : [];
    };
    const setTranslations = (roleId, pairs) => {
      const meta = readRoleMeta();
      if (!meta[roleId]) meta[roleId] = { created_at: Date.now() / 1000, name: roleId };
      meta[roleId].translations = pairs;
      writeRoleMeta(meta);
    };
    // 可逆替换（长词优先，与灵枢 translate_input/translate_output 同逻辑）
    const applyTranslate = (text, pairs, dir) => {
      if (!text || !pairs.length) return text;
      const key = dir === 'out' ? 'virtual' : 'real';
      const rep = dir === 'out' ? 'real' : 'virtual';
      const sorted = pairs
        .filter((p) => p[key] && p[rep])
        .sort((a, b) => (b[key] || '').length - (a[key] || '').length);
      let out = text;
      for (const p of sorted) out = out.split(p[key]).join(p[rep]);
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
          } catch { /* 文件尚不存在 */ }
          res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
          res.end(JSON.stringify({ roles }));
          return;
        }
        if (req.method === 'POST' && url.pathname === '/roleplay/api/chat') {
          let body = '';
          for await (const chunk of req) body += chunk;
          const p = JSON.parse(body);
          const role = p.role_id || 'protocol-guide';
          appendTranscript(role, { time: Date.now(), role: 'user', text: p.message });
          const r = await bridge.callTool('roleplay_chat', {
            message: p.message, role_id: role, session_id: sessionFor(role), data_dir: roleDataDir,
          });
          const text = typeof r === 'string' ? r : (r?.content?.[0]?.text ?? JSON.stringify(r));
          let parsed;
          try { parsed = JSON.parse(text); } catch { parsed = { reply: text, route: 'raw' }; }
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
          for await (const chunk of req) body += chunk;
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
          for await (const chunk of req) body += chunk;
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
      if (html.includes('href="/roleplay"')) return html;
      const btn = '<a href="/roleplay" style="position:fixed;top:12px;right:14px;z-index:999999;background:#7c8cff;color:#0b0d14;border-radius:999px;padding:9px 15px;font:600 13px/1 system-ui,sans-serif;text-decoration:none;box-shadow:0 4px 14px rgba(0,0,0,.45)">🎭 角色扮演</a>';
      return html.replace('</body>', `${btn}\n</body>`);
    }));
    ctx.logger.info(`dsh-memory: 角色扮演网页已挂载 /roleplay（data_dir=${roleDataDir}）`);
  }
  catch (err) {
    ctx.logger.warn(`dsh-memory: 角色扮演网页挂载失败（不影响其他功能）: ${String(err && err.message || err)}`);
  }
}
