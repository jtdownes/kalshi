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

/** Mid price (average of bid and ask) in cents. Falls back to whichever side
 *  is present if only one exists; null if both are missing. */
export function midCents(bid: number | null | undefined, ask: number | null | undefined): number | null {
  if (bid != null && ask != null) return Math.round((bid + ask) / 2 * 10) / 10
  if (bid != null) return bid
  if (ask != null) return ask
  return null
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
  return d.toLocaleString([], {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
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

import type { StrategyRule, RuleCondition } from './types'

export interface TtcWindow {
  minTtc: number | null    // lower bound on time-to-close (seconds), null = open
  maxTtc: number | null    // upper bound on time-to-close (seconds), null = open
  minCents: number | null  // lower bound on entry ask price (¢), null = open
  maxCents: number | null  // upper bound on entry ask price (¢), null = open
  minDist: number | null   // lower bound on distance_to_strike (signed USD), null = open
  maxDist: number | null   // upper bound on distance_to_strike (signed USD), null = open
}

// Collapse all of a rule's conditions on `field` into a single [min, max] range.
// Returns bounded=false if the field is never constrained. null on a bound means
// open-ended in that direction.
function fieldBounds(rule: StrategyRule, field: RuleCondition['field']):
  { min: number | null; max: number | null; bounded: boolean } {
  let min: number | null = null
  let max: number | null = null
  let bounded = false
  for (const c of rule.conditions || []) {
    if (c.field !== field) continue
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
  return { min, max, bounded }
}

// Derive the entry window(s) a rule set allows, so a chart can shade the span
// where an entry was eligible: a time-to-close span on the x-axis (seconds) and,
// when the rule gates on contract ask price, a cents band on the y-axis. The ask
// band uses whichever side the rule trades (yes_ask for yes/both, no_ask for no).
export function ttcWindowsFromRules(rules: StrategyRule[]): TtcWindow[] {
  const out: TtcWindow[] = []
  const seen = new Set<string>()
  for (const rule of rules) {
    if (rule.enabled === false) continue
    const ttc = fieldBounds(rule, 'time_to_close')
    const askField = rule.action?.side === 'no' ? 'no_ask' : 'yes_ask'
    const ask = fieldBounds(rule, askField)
    const dist = fieldBounds(rule, 'distance_to_strike')
    if (!ttc.bounded && !ask.bounded && !dist.bounded) continue
    const key = `${ttc.min}:${ttc.max}:${ask.min}:${ask.max}:${dist.min}:${dist.max}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push({
      minTtc: ttc.min, maxTtc: ttc.max,
      minCents: ask.bounded ? ask.min : null,
      maxCents: ask.bounded ? ask.max : null,
      minDist: dist.bounded ? dist.min : null,
      maxDist: dist.bounded ? dist.max : null,
    })
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

// ── Crypto asset detection ────────────────────────────────────────────────────
// Maps a Kalshi ticker prefix to the underlying crypto asset.
// Add new assets here to support them everywhere (chart label, price column, filter).

export type CryptoAsset = 'BTC' | 'ETH' | 'SOL'

interface CryptoAssetConfig {
  label: string          // human-readable name
  priceField: string     // field name on the Snapshot / SeriesData objects
  color: string          // accent color used in charts / UI
}

const CRYPTO_ASSET_MAP: Record<CryptoAsset, CryptoAssetConfig> = {
  BTC: { label: 'Bitcoin', priceField: 'btc_price', color: '#f7931a' },
  ETH: { label: 'Ethereum', priceField: 'eth_price', color: '#627eea' },
  SOL: { label: 'Solana', priceField: 'sol_price', color: '#9945ff' },
}

// Ticker-prefix → asset mapping. Extend this as new series are added.
const TICKER_PREFIX_TO_ASSET: [string, CryptoAsset][] = [
  ['KXBTC', 'BTC'],
  ['KXETH', 'ETH'],
  ['KXSOL', 'SOL'],
]

/** Returns the crypto asset for a given Kalshi ticker, or null if not a crypto market. */
export function detectCryptoAsset(ticker: string): CryptoAsset | null {
  const upper = ticker.toUpperCase()
  for (const [prefix, asset] of TICKER_PREFIX_TO_ASSET) {
    if (upper.startsWith(prefix)) return asset
  }
  return null
}

/** Returns the full config for the crypto asset corresponding to a ticker, or null. */
export function cryptoAssetConfig(ticker: string): CryptoAssetConfig | null {
  const asset = detectCryptoAsset(ticker)
  return asset ? CRYPTO_ASSET_MAP[asset] : null
}

/** Returns the price (from a snapshot-like object) for the asset detected from ticker. */
export function cryptoPriceForTicker(ticker: string, data: Record<string, unknown>): number | null {
  const cfg = cryptoAssetConfig(ticker)
  if (!cfg) return null
  const val = data[cfg.priceField]
  return typeof val === 'number' ? val : null
}

/** True when a market belongs on the Crypto page. Ticker prefix is the primary
 *  signal; title words are a fallback for series without a mapped prefix.
 *  Word-boundary match so e.g. "whether" doesn't hit "eth". */
const CRYPTO_TITLE_RE = /\b(bitcoin|btc|ethereum|eth|solana|sol)\b/i
export function isCryptoMarket(ticker: string, title: string): boolean {
  return detectCryptoAsset(ticker) != null || CRYPTO_TITLE_RE.test(title)
}

// Markets a strategy can be assigned to. Strategies store the series ticker;
// add new tradable series here (and the asset above) to expose them in the UI.
export const STRATEGY_MARKETS = [
  { value: 'KXBTC15M', label: 'Bitcoin 15 Minute' },
  { value: 'KXETH15M', label: 'Ethereum 15 Minute' },
] as const
