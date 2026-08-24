/**
 * verify_desensitize.ts · 自动记忆脱敏验证（GPT 审查完善）
 * ① 密钥/密码/令牌/身份证/手机号 → 替换为 [已过滤:类别]
 * ② 纯凭据消息 → 返回 null（跳过写入）
 * ③ 正常内容 → 原样保留（不误伤）
 */
import { desensitize } from '../src/hooks.ts'

let pass = 0, fail = 0
function check(name: string, ok: boolean, detail = ''): void {
  if (ok) pass++; else fail++
  console.log(`[${ok ? '✓' : '✘'}] ${name}${detail ? ' — ' + detail : ''}`)
}

// ① 各类敏感信息被替换
const r1 = desensitize('我的 API key 是 sk-abc123def456，记得别外传')
check('①a sk- 密钥被过滤', r1 !== null && r1.includes('[已过滤:API密钥]') && !r1.includes('sk-abc'), r1 ?? 'null')

const r2 = desensitize('服务器密码是 hunter2，部署时用')
check('①b 英文 password 被过滤', r2 !== null && r2.includes('[已过滤:密码]') && !r2.includes('hunter2'), r2 ?? 'null')

const r3 = desensitize('密码：abc123456，别告诉别人')
check('①c 中文密码被过滤', r3 !== null && r3.includes('[已过滤:密码]') && !r3.includes('abc123456'), r3 ?? 'null')

const r4 = desensitize('Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc')
check('①d Bearer 令牌被过滤', r4 !== null && r4.includes('[已过滤:令牌]') && !r4.includes('eyJ'), r4 ?? 'null')

const r5 = desensitize('我的身份证是 11010119900307789X，帮我查下')
check('①e 身份证号被过滤', r5 !== null && r5.includes('[已过滤:身份证号]') && !r5.includes('1101011990'), r5 ?? 'null')

const r6 = desensitize('联系我 13800138000 就行')
check('①f 手机号被过滤', r6 !== null && r6.includes('[已过滤:手机号]') && !r6.includes('13800138000'), r6 ?? 'null')

// ② 纯凭据消息 → null（跳过写入）
const r7 = desensitize('sk-abcdefgh12345678')
check('② 纯凭据消息 → null（跳过写入）', r7 === null, r7 ?? 'null')

// ③ 正常内容原样保留
const r8 = desensitize('用户喜欢猫，上次聊了冒泡排序的实现')
check('③ 正常内容不误伤', r8 === '用户喜欢猫，上次聊了冒泡排序的实现', r8 ?? 'null')

// ④ 混合：敏感片段替换但主体保留
const r9 = desensitize('密码是 123456，另外我们下周发布新版本')
check('④ 混合内容：敏感替换+主体保留', r9 !== null && r9.includes('[已过滤:密码]') && r9.includes('下周发布新版本'), r9 ?? 'null')

console.log(`\n脱敏验证: ${pass}/${pass + fail} 通过`)
process.exit(fail > 0 ? 1 : 0)
