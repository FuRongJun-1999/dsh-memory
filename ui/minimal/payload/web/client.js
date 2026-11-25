const React = require('react');
const PANEL_HTML = __PANEL_HTML__;   // build-ui.mjs 打包时内联（index.html + style.css + 桥 + app.js）
function Icon({size=16}) {
  return React.createElement('svg', {width:size,height:size,viewBox:'0 0 24 24',fill:'none',stroke:'currentColor',strokeWidth:1.5,'aria-hidden':true}, React.createElement('path',{d:'M12 3v18M5 7l14 10M19 7L5 17'}));
}
// issue #791：桌面版（dsh-app://）下 iframe 子 frame 拿不到 x-dsh-desktop-renderer ⇒ 403 白屏。
// 改法：面板用 srcdoc 内嵌同一份 UI，页面里的 fetch 全部经 postMessage 由**主 frame** 代发
// （主 frame 的请求带 marker，能过 host 的 web-document 门）；/lingshu 直连路由保持不变。
// 桥的状态必须在**模块级**：ref 每次渲染都是新函数，若状态写在 Panel 内会重复绑 listener（复核 0077）。
const BRIDGE = { frame: null, bound: false };
const ALLOWED_BRIDGE_METHODS = new Set(['GET', 'POST']);
function onFrameRef(node) {
  BRIDGE.frame = node;
  if (!node || BRIDGE.bound) return;
  BRIDGE.bound = true;
  window.addEventListener('message', (ev) => {
    const d = ev.data;
    if (!d || typeof d !== 'object' || d.__lingshu !== 'req') return;
    if (!BRIDGE.frame || !BRIDGE.frame.contentWindow || ev.source !== BRIDGE.frame.contentWindow) return;
    const reply = (payload) => {
      try {
        if (!BRIDGE.frame || !BRIDGE.frame.contentWindow) return;
        BRIDGE.frame.contentWindow.postMessage(Object.assign({ __lingshu: 'res', id: d.id }, payload), '*');
      } catch (e) { /* frame 已卸载 */ }
    };
    const baseOrigin = window.location && window.location.origin;
    if (!baseOrigin || baseOrigin === 'null') {
      reply({ error: 'invalid_origin' });
      return;
    }
    let targetUrl;
    try {
      targetUrl = new URL(String(d.url || ''), baseOrigin);
    } catch (e) {
      reply({ error: 'invalid_url' });
      return;
    }
    if (
      targetUrl.origin !== baseOrigin
      || targetUrl.username
      || targetUrl.password
      || !targetUrl.pathname.startsWith('/plugins/lingshu/')
      || /%2e/i.test(targetUrl.pathname)
      || targetUrl.pathname.includes('\\')
    ) {
      reply({ error: 'url_not_allowed' });
      return;
    }
    const method = String(d.method || 'GET').toUpperCase();
    if (!ALLOWED_BRIDGE_METHODS.has(method)) {
      reply({ error: 'method_not_allowed' });
      return;
    }
    const headers = (d.headers && typeof d.headers === 'object' && !Array.isArray(d.headers)) ? d.headers : {};
    const body = (method === 'GET' || d.body == null) ? undefined : d.body;
    fetch(targetUrl.pathname + targetUrl.search, { method, body, headers, credentials: 'same-origin' })
      .then(async (r) => reply({ ok: r.ok, status: r.status, text: await r.text() }))
      .catch((e) => reply({ error: String((e && e.message) || e) }));
  });
}
function Panel() {
  return React.createElement('iframe', {
    title: '灵枢 · 认知工作台',
    srcDoc: PANEL_HTML,
    ref: onFrameRef,
    style: {width:'100%',height:'100%',border:0,display:'block',background:'#f8f9f7'},
  });
}
module.exports = {
  inject:['slots'],
  apply(ctx) {
    ctx.slots.inject('main',()=>ctx.slots.register({name:'main',key:'lingshu'},Panel));
    ctx.slots.inject('sidebar.panellist',()=>ctx.slots.register({name:'sidebar.panellist',id:'lingshu',order:20,label:'灵枢'},Icon));
  },
};