import { readFileSync } from 'node:fs';
import { randomBytes, timingSafeEqual } from 'node:crypto';

export const READ_OPS = new Set(['info', 'read', 'route', 'help', 'edges', 'status']);
const READ_ACTIONS = { goal: ['list'], task: ['list', 'get', 'find', 'session'], recent: ['list'], identity: ['profile'], self_state: ['snapshot'], metacognition: ['report'], review: ['list', 'records'], protect: ['stats'], evolution: ['summary'], sustain: ['status'], maintain: ['stat'], ref: ['stat'], theory: ['check'], link: ['ls'], whitebox: ['ping'] };
export function needsConfirmation(tool, args = {}) {
  const unsafe = ['content', 'text', 'goal', 'set', 'apply', 'write', 'force', 'override', 'auto_flywheel'].some(key => args[key] !== undefined);
  if (tool === 'stg') return unsafe || !['relation', 'timeline', 'anchors', 'consistency', 'state_chain'].includes(args.op);
  if (tool === 'cg') return unsafe || !(READ_OPS.has(args.op) || READ_ACTIONS[args.op]?.includes(args.action));
  return !new Set(['mdcg_recall', 'mdcg_search', 'mdcg_get', 'mdcg_review_list', 'mdcg_review_records', 'mdcg_forgetting_history', 'mdcg_health', 'mdcg_whoami', 'mdcg_service_info', 'mdcg_rejected', 'mdcg_unresolved', 'mdcg_watermarks']).has(tool);
}
export function redact(value) {
  if (Array.isArray(value)) return value.map(redact);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.entries(value).filter(([key]) => !/^(token|secret|password|api_key|authorization|key_material|MDCG_TOKEN)$/i.test(key)).map(([key, item]) => [key, redact(item)]));
}
function reply(res, status, body, type = 'application/json; charset=utf-8') {
  res.writeHead(status, { 'Content-Type': type, 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'same-origin' });
  res.end(type.startsWith('application/json') ? JSON.stringify(body) : body);
}
async function readBody(req) {
  const chunks = []; let bytes = 0;
  for await (const chunk of req) {
    bytes += chunk.length;
    if (bytes > 131072) throw Object.assign(new Error('请求超过 128 KB'), { status: 413 });
    chunks.push(chunk);
  }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); }
  catch { throw Object.assign(new Error('请求必须是有效 JSON'), { status: 400 }); }
}
// issue #699（2026-10-28）：第 4 参改为**取值函数**。原实现由挂载点 `ctx.get('connection')` 取值，
// 而 cordis 的 `Context.get(name, strict=true)` 在服务 fiber 未就绪时返回 undefined ⇒
// 空值被闭包固化，此后每次请求都命中 503「宿主鉴权不可用」，宿主就绪也不会自愈。
// 现在改为**每次请求实时取**：服务晚到也能自愈。
// 兼容：传的不是函数（旧调用方式/直接给实例）时按常量包裹，行为与旧版一致。
export function createConsoleHandler(mdcg, config, assets, getConnection) {
  const connectionOf = typeof getConnection === 'function' ? getConnection : () => getConnection
  const csrf = randomBytes(32).toString('hex');
  let catalog = null;
  const tools = async () => catalog ?? (catalog = await mdcg.bridge.listTools());
  return async (req, res) => {
    try {
      const path = new URL(req.url, 'http://localhost').pathname;
      const connection = connectionOf()
      if (!connection || typeof connection.admit !== 'function') return reply(res, 503, { error: '宿主鉴权服务尚未就绪，请稍后重试' });
      const admission = connection.admit(req);
      if ('rejection' in admission) return reply(res, admission.rejection, { error: admission.rejection === 401 ? '未登录，请返回 DSH 登录' : '请求来源不可信' });
      if (req.method === 'GET' && assets[path]) {
        const [body, type] = assets[path]; reply(res, 200, typeof body === 'function' ? body() : body, type); return;
      }
      if (!path.startsWith('/plugins/lingshu/')) return reply(res, 404, { error: '页面不存在' });
      if (req.method === 'GET' && path === '/plugins/lingshu/meta') {
        return reply(res, 200, { ready: !!mdcg?.isReady(), csrf, identity: config.identity, memory: config.memory, capability: !!config.capability?.enabled, tools: mdcg?.isReady() ? await tools() : [] });
      }
      if (req.method !== 'POST' || path !== '/plugins/lingshu/call') return reply(res, 405, { error: '不支持的请求' });
      const origin = req.headers.origin;
      const host = req.headers.host;
      // 桌面 dsh-app 代理移除 Origin，宿主 admission 仍验证浏览器登录。
      if ((origin && new URL(origin).host !== host && origin !== 'dsh-app://app') || req.headers['sec-fetch-site'] === 'cross-site') return reply(res, 403, { error: '仅允许同源界面调用' });
      const supplied = String(req.headers['x-lingshu-csrf'] ?? '');
      if (supplied.length !== csrf.length || !timingSafeEqual(Buffer.from(supplied), Buffer.from(csrf))) return reply(res, 403, { error: '页面凭证已过期，请刷新页面' });
      if (!String(req.headers['content-type']).startsWith('application/json')) return reply(res, 415, { error: '需要 application/json' });
      const body = await readBody(req);
      if (!body || typeof body.tool !== 'string' || !body.args || typeof body.args !== 'object' || Array.isArray(body.args)) return reply(res, 400, { error: '工具参数格式不正确' });
      if (!mdcg?.isReady()) return reply(res, 503, { error: '灵枢大脑尚未就绪，请稍后重试' });
      if (!(await tools()).some(t => t.name === body.tool)) return reply(res, 400, { error: '该工具不在灵枢真实工具目录中' });
      if (needsConfirmation(body.tool, body.args) && body.confirm !== true) return reply(res, 409, { error: '此操作可能修改数据，请先确认' });
      let result;
      if (body.tool === 'cg') result = await mdcg.cg(body.args);
      else if (body.tool === 'stg') result = await mdcg.stg(body.args);
      else if (body.tool === 'mdcg_remember') {
        const { content, ...extra } = body.args;
        if (typeof content !== 'string' || !content.trim()) return reply(res, 400, { error: '记忆内容不能为空' });
        result = await mdcg.write(content, extra);
      } else {
        const raw = await mdcg.bridge.callTool(body.tool, body.args);
        const text = (raw.content ?? []).filter(c => c.type === 'text').map(c => c.text ?? '').join('');
        if (raw.isError) return reply(res, 422, { error: text || '灵枢拒绝此次操作' });
        try { result = JSON.parse(text); } catch { result = text; }
      }
      reply(res, 200, { ok: true, result: redact(result) });
    } catch (error) { reply(res, error.status ?? 500, { error: String(error.message ?? error) }); }
  };
}
export function installConsoleWeb(ctx, config, disposers, mdcg) {
  try {
    const web = ctx.get('webServer');
    if (!web) return;
    // 每次请求读已构建的静态页面，刷新即可看到更新，避免 apply 时缓存旧 CSS/JS。
    const asset = (name) => () => readFileSync(new URL(`../../web/${name}`, import.meta.url), 'utf8');
    const assets = {
      '/lingshu': [asset('index.html'), 'text/html; charset=utf-8'],
      '/lingshu/': [asset('index.html'), 'text/html; charset=utf-8'],
      '/plugins/lingshu/app.js': [asset('app.js'), 'application/javascript; charset=utf-8'],
      '/plugins/lingshu/style.css': [asset('style.css'), 'text/css; charset=utf-8'],
      '/plugins/lingshu/entry.js': [asset('entry.js'), 'application/javascript; charset=utf-8'],
    };
    // issue #699：传**取值函数**（每次请求实时取），不再把挂载瞬间的值闭包固化。
    const handler = createConsoleHandler(mdcg, config, assets, () => ctx.get('connection'));
    for (const path of ['/lingshu', '/lingshu/', '/plugins/lingshu']) disposers.push(web.register({ kind: path === '/plugins/lingshu' ? 'prefix' : 'exact', path, handler }));
    disposers.push(web.tapIndex(html => html.includes('data-lingshu-entry') ? html : html.replace('</body>', '<script data-lingshu-entry src="/plugins/lingshu/entry.js"></script></body>')));
    ctx.logger.info('dsh-memory: 极简灵枢控制台已挂载 /lingshu（复用唯一大脑桥）');
  } catch (error) { ctx.logger.warn(`dsh-memory: 控制台加载失败（不影响大脑）：${error.message}`); }
}
