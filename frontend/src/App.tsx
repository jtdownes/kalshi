import { useState, useEffect, useCallback } from 'react'
import { Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Strategies from './pages/Strategies'

// ── Types ────────────────────────────────────────────────────────────────────────────────
export interface Position {
  ticker: string
  position_fp: string
  total_traded_dollars: string
  market_exposure_dollars: string
  realized_pnl_dollars: string
  fees_paid_dollars: string
  last_updated_ts: string
}

export interface Order {
  id: number
  kalshi_order_id: string | null
  market_ticker: string
  side: string
  entry_price_cents: number
  count: number
  status: string
  placed_at: string
  filled_at: string | null
  market_close_time: string | null
  time_to_close_at_placement: number | null
  outcome: string | null
  payout_cents: number | null
  net_profit_cents: number | null
}

export interface Snapshot {
  id: number
  ticker: string
  title: string
  scanned_at: string
  close_time: string | null
  yes_ask: number | null
  yes_bid: number | null
  no_ask: number | null
  no_bid: number | null
  time_to_close_secs: number | null
  strike_str: string | null
  volume: number | null
  open_interest: number | null
}

export interface Settings {
  min_entry_cents: number
  max_entry_cents: number
  proactive_mode: boolean
  max_open_orders: number
  max_daily_spend_cents: number
  scan_interval_seconds: number
  btc_series_tickers: string[]
  active_profile_id: number | null
  name?: string
}

export interface Profile {
  id: number
  name: string
  created_at: string
  min_entry_cents: number
  max_entry_cents: number
  proactive_mode: boolean
  max_open_orders: number
  max_daily_spend_cents: number
  scan_interval_seconds: number
  btc_series_tickers: string
  order_count: number
}

export type Quotes = Record<string, {
  yes_ask: number | null
  no_ask: number | null
  yes_bid: number | null
  no_bid: number | null
  open_interest: number | null
}>

// ── Helpers (exported for pages) ─────────────────────────────────────────────────────────
export function centsToUSD(c: number | null | undefined): string {
  if (c == null) return '—'
  return `$${(c / 100).toFixed(2)}`
}

export function fmtPnL(c: number | null | undefined): string {
  if (c == null) return '—'
  const sign = c > 0 ? '+' : ''
  return `${sign}${c}¢`
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
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

// ── Main ─────────────────────────────────────────────────────────────────────────────────
export default function App() {
  const [orders,      setOrders]      = useState<Order[]>([])
  const [positions,   setPositions]   = useState<Position[] | { error: string }>([])
  const [snapshots,   setSnapshots]   = useState<Snapshot[]>([])
  const [quotes,      setQuotes]      = useState<Quotes>({})
  const [settings,    setSettings]    = useState<Settings | null>(null)
  const [profiles,    setProfiles]    = useState<Profile[]>([])
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)
  const [loading,     setLoading]     = useState(false)
  const [error,       setError]       = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [o, pos, snap, st, pr] = await Promise.all([
        fetch('/api/orders?limit=200').then(r => { if (!r.ok) throw new Error('orders'); return r.json() }),
        fetch('/api/positions').then(r => r.json()).catch(() => []),
        fetch('/api/snapshots?limit=200').then(r => r.json()).catch(() => []),
        fetch('/api/settings').then(r => { if (!r.ok) throw new Error('settings'); return r.json() }),
        fetch('/api/profiles').then(r => { if (!r.ok) throw new Error('profiles'); return r.json() }),
      ])
      setOrders(o)
      setPositions(pos)
      setSnapshots(snap)
      setSettings(st)
      setProfiles(pr)
      setLastRefresh(new Date())
    } catch {
      setError('API unavailable — bot may be starting up')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const openOrders = orders.filter(o => o.status === 'resting')

  useEffect(() => {
    if (!autoRefresh) return
    const id = setInterval(refresh, 5_000)
    return () => clearInterval(id)
  }, [autoRefresh, refresh])

  useEffect(() => {
    const fetchQuotes = async () => {
      const posTickers = Array.isArray(positions) ? positions.map(p => p.ticker) : []
      const orderTickers = openOrders.map(o => o.market_ticker)
      const tickers = [...new Set([...posTickers, ...orderTickers])]
      if (tickers.length === 0) return
      try {
        const data = await fetch(`/api/quotes?tickers=${tickers.join(',')}`).then(r => r.json())
        if (!data.error) setQuotes(data)
      } catch { /* silent */ }
    }
    fetchQuotes()
    const id = setInterval(fetchQuotes, 2_000)
    return () => clearInterval(id)
  }, [positions, openOrders])

  return (
    <div className="app">
      <header className="header">
        <div className="header-left">
          <span className="header-logo">⧟</span>
          <span className="header-title">Kalshi Bot</span>
          <nav className="header-nav">
            <NavLink to="/" end className={({ isActive }) => isActive ? 'nav-link nav-link-active' : 'nav-link'}>
              Dashboard
            </NavLink>
            <NavLink to="/strategies" className={({ isActive }) => isActive ? 'nav-link nav-link-active' : 'nav-link'}>
              Strategies
            </NavLink>
          </nav>
        </div>
        <div className="header-right">
          {error && <span style={{ color: '#ff4444', fontSize: 12 }}>{error}</span>}
          {lastRefresh && !error && (
            <span className="last-refresh">
              {loading ? 'Refreshing…' : `Updated ${fmtTime(lastRefresh.toISOString())}`}
            </span>
          )}
          <button
            className={`btn${autoRefresh ? ' btn-active' : ''}`}
            onClick={() => setAutoRefresh(a => !a)}
          >
            {autoRefresh ? '⏸ Auto' : '▶ Auto'}
          </button>
          <button className="btn" onClick={refresh}>↻</button>
        </div>
      </header>

      <Routes>
        <Route
          path="/"
          element={
            <Dashboard
              orders={orders}
              openOrders={openOrders}
              positions={positions}
              snapshots={snapshots}
              quotes={quotes}
              settings={settings}
              profiles={profiles}
            />
          }
        />
        <Route
          path="/strategies"
          element={
            <Strategies
              settings={settings}
              profiles={profiles}
              refresh={refresh}
            />
          }
        />
      </Routes>
    </div>
  )
}
