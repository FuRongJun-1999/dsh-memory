/**
 * 会话身份五元组（端侧复算实现）——与 md_cg/session5.py 逐位一致。
 *
 * 形态：s5.<端>.<身份>.<工作区>.<创建时间>.<首条消息摘要前12位>
 * 设计出处：《会话身份五元组形态（s5）设计定稿》（设计者三项决定，2026-10-09/10）
 * 真源：md_cg/session5.py（本文件是端侧镜像，**任何改动必须两侧同改并由守卫对拍**）
 */
import { createHash } from 'node:crypto'

export const SESSION5_PREFIX = 's5'
export const SESSION5_MSG_MAX = 1024

const SEP_RE = /[\\/]+/g
const SLUG_RE = /[^A-Za-z0-9]+/g
const RUN_RE = /_+/g

/** 工作区路径 → slug（分隔符序列与其余非字母数字统一归一为单下划线）。 */
export function slugWorkspace(path: unknown): string {
  return String(path ?? '')
    .trim()
    .replace(SEP_RE, '_')
    .replace(SLUG_RE, '_')
    .replace(RUN_RE, '_')
    .replace(/^_+|_+$/g, '')
}

/** 首条用户消息原文截断 1024 字符 → sha1 前 12 位（小写 hex）。 */
export function digestMessage(firstMessage: unknown): string {
  const raw = String(firstMessage ?? '').slice(0, SESSION5_MSG_MAX)
  return createHash('sha1').update(raw, 'utf8').digest('hex').slice(0, 12)
}

/** 按五元组生成会话标识（纯函数，跨端可复算）。 */
export function makeSession5(
  harness: string, unit: string, workspace: string, startEpoch: number, firstMessage: string,
): string {
  const h = String(harness ?? '').trim().toLowerCase()
  const u = String(unit ?? '').trim().toLowerCase()
  const ws = slugWorkspace(workspace)
  const ep = Number(startEpoch)
  if (!h || !u || !ws) throw new Error('harness / unit / workspace 均不得为空')
  if (!Number.isInteger(ep) || ep <= 0 || ep > 9999999999) {
    throw new Error('startEpoch 必须是 10 位 unix 秒')
  }
  return `${SESSION5_PREFIX}.${h}.${u}.${ws}.${ep}.${digestMessage(firstMessage)}`
}

/** 是否五元组形态（只判形状，不判各段取值合法性）。 */
export function isSession5(s: unknown): boolean {
  return /^s5\.[a-z0-9_]{1,32}\.[a-z0-9_]{1,32}\.[A-Za-z0-9_]{1,64}\.\d{10}\.[0-9a-f]{12}$/.test(String(s ?? ''))
}

/** 解析五元组（失败返回 null，不猜）。 */
export function parseSession5(s: unknown): { harness: string; unit: string; workspace: string; startEpoch: number; digest: string } | null {
  const v = String(s ?? '')
  if (!isSession5(v)) return null
  const p = v.split('.')
  return { harness: p[1], unit: p[2], workspace: p[3], startEpoch: Number(p[4]), digest: p[5] }
}
