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

export function kalshiMarketUrl(ticker: string): string {
  const lower = ticker.toLowerCase()
  const parts = lower.split('-')
  const marketSlug = parts.slice(0, -1).join('-')
  const series = parts[0]
  return `https://kalshi.com/markets/${series}/${marketSlug}`
}
