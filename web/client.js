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
function onFrameRef(node) {
  BRIDGE.frame = node;
  if (!node || BRIDGE.bound) return;
  BRIDGE.bound = true;
  window.addEventListener('message', (ev) => {
    const d = ev.data || {};
    if (d.__lingshu !== 'req') return;
    if (BRIDGE.frame && ev.source !== BRIDGE.frame.contentWindow) return;
    const reply = (payload) => {
      try { BRIDGE.frame.contentWindow.postMessage(Object.assign({ __lingshu: 'res', id: d.id }, payload), '*'); } catch (e) { /* frame 已卸载 */ }
    };
    fetch(d.url, { method: d.method || 'GET', body: (d.body == null ? undefined : d.body), headers: d.headers || {}, credentials: 'same-origin' })
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