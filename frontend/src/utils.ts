// ── Formatting helpers ────────────────────────────────────────────────────────

export function centsToUSD(c: number | null | undefined): string {
  if (c == null) return '—'
  return `$${(c / 100).toFixed(2)}`
}

export function fmtPnL(c: number | null | undefined): string {
  if (c == null) return '—'
  const sign = c > 0 ? '+' : ''
  return `${sign}${c}¢`
}

export function fmtCents(c: number | null | undefined): string {
  if (c == null) return '—'
  return c < 10 ? `${c.toFixed(1)}¢` : `${c}¢`
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function fmtUnixTime(raw: string | null | undefined): string {
  if (!raw) return '—'
  const ts = parseInt(raw, 10)
  if (isNaN(ts)) return fmtTime(raw)
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function fmtDur(secs: number | null | undefined): string {
  if (secs == null) return '—'
  if (secs < 60) return `${secs}s`
  const m = Math.floor(secs / 60)
  const s = secs % 60
  return s ? `${m}m ${s}s` : `${m}m`
}

export function fmtTickers(raw: string | string[] | null | undefined): string {
  if (!raw) return '—'
  const tickers = Array.isArray(raw) ? raw : raw.split(',')
  return tickers.map(t => t.trim()).filter(Boolean).join(', ') || '—'
}

// ── Rule helpers ──────────────────────────────────────────────────────────────

import type { StrategyRule } from './types'

export interface TtcWindow {
  minTtc: number | null  // lower bound on time-to-close (seconds), null = open
  maxTtc: number | null  // upper bound on time-to-close (seconds), null = open
}

// Derive the time-to-close window(s) a rule set allows, so a chart can shade the
// span where an entry was eligible. Values are in seconds (same as the field).
export function ttcWindowsFromRules(rules: StrategyRule[]): TtcWindow[] {
  const out: TtcWindow[] = []
  const seen = new Set<string>()
  for (const rule of rules) {
    if (rule.enabled === false) continue
    let min: number | null = null
    let max: number | null = null
    let bounded = false
    for (const c of rule.conditions || []) {
      if (c.field !== 'time_to_close') continue
      const v = c.value
      if (v == null) continue
      if (c.op === 'between') {
        if (c.value2 == null) continue
        const lo = Math.min(v, c.value2)
        const hi = Math.max(v, c.value2)
        min = min == null ? lo : Math.max(min, lo)
        max = max == null ? hi : Math.min(max, hi)
        bounded = true
      } else if (c.op === 'gt' || c.op === 'gte') {
        min = min == null ? v : Math.max(min, v)
        bounded = true
      } else if (c.op === 'lt' || c.op === 'lte') {
        max = max == null ? v : Math.min(max, v)
        bounded = true
      } else if (c.op === 'eq') {
        min = min == null ? v : Math.max(min, v)
        max = max == null ? v : Math.min(max, v)
        bounded = true
      }
    }
    if (!bounded) continue
    const key = `${min}:${max}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push({ minTtc: min, maxTtc: max })
  }
  return out
}

export function kalshiMarketUrl(ticker: string): string {
  const lower = ticker.toLowerCase()
  const parts = lower.split('-')
  const marketSlug = parts.slice(0, -1).join('-')
  const series = parts[0]
  return `https://kalshi.com/markets/${series}/${marketSlug}`
}
