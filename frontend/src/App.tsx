import { useState, useEffect, useCallback } from 'react'
import { Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Strategies from './pages/Strategies'
import Snapshots from './pages/Snapshots'
import Backtest from './pages/Backtest'

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
  order_role: string
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

export interface Trade {
  market_ticker: string
  order_count: number
  placed_at: string
  filled_at: string | null
  market_close_time: string | null
  entry_price_cents: number | null
  net_profit_cents: number | null
  status: string
  outcome: string | null
  peak_price_cents: number | null
  peak_time: string | null
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
  btc_price: number | null
  volume: number | null
  open_interest: number | null
}

export interface Settings {
  min_entry_cents: number
  max_entry_cents: number
  proactive_mode: boolean
  max_open_orders: number
  max_daily_spend_cents: number
  btc_series_tickers: string[]
  exit_strategy: 'hold_to_expiration' | 'limit_sell'
  limit_sell_price_cents: number | null
  active_profile_id: number | null
  name?: string
}

export interface Profile {
  id: number
  name: string
  created_at: string
  is_active: boolean
  min_entry_cents: number
  max_entry_cents: number
  proactive_mode: boolean
  max_open_orders: number
  max_daily_spend_cents: number
  btc_series_tickers: string
  exit_strategy: 'hold_to_expiration' | 'limit_sell'
  limit_sell_price_cents: number | null
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

// ── Main ─────────────────────────────────────────────────────────────────────────────────
export default function App() {
  const [orders,      setOrders]      = useState<Order[]>([])
  const [trades,      setTrades]      = useState<Trade[]>([])
  const [positions,   setPositions]   = useState<Position[] | { error: string }>([])
  const [snapshots,   setSnapshots]   = useState<Snapshot[]>([])
  const [quotes,      setQuotes]      = useState<Quotes>({})
  const [settings,    setSettings]    = useState<Settings | null>(null)
  const [profiles,    setProfiles]    = useState<Profile[]>([])
  const [balance,     setBalance]     = useState<number | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)
  const [loading,     setLoading]     = useState(false)
  const [error,       setError]       = useState<string | null>(null)
  const [wsConnected, setWsConnected] = useState(false)
  const dashboardRefreshMs = 1000

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [o, tr, pos, snap, st, pr, bal] = await Promise.all([
        fetch('/api/orders?limit=200').then(r => { if (!r.ok) throw new Error('orders'); return r.json() }),
        fetch('/api/trades?limit=200').then(r => r.json()).catch(() => []),
        fetch('/api/positions').then(r => r.json()).catch(() => []),
        fetch('/api/snapshots?limit=200').then(r => r.json()).catch(() => []),
        fetch('/api/settings').then(r => { if (!r.ok) throw new Error('settings'); return r.json() }),
        fetch('/api/profiles').then(r => { if (!r.ok) throw new Error('profiles'); return r.json() }),
        fetch('/api/balance').then(r => r.json()).catch(() => null),
      ])
      setOrders(o)
      setTrades(tr)
      setPositions(pos)
      setSnapshots(snap)
      setSettings(st)
      setProfiles(pr)
      if (bal && !bal.error) setBalance(bal.balance ?? null)
      setLastRefresh(new Date())
    } catch {
      setError('API unavailable — bot may be starting up')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const openOrders = orders.filter(o => o.status === 'resting')

  // Periodic refresh for dashboard data not covered by the SSE stream.
  useEffect(() => {
    if (!autoRefresh) return
    const id = setInterval(async () => {
      try {
        const [o, tr, st, pr] = await Promise.all([
          fetch('/api/orders?limit=200').then(r => r.json()),
          fetch('/api/trades?limit=200').then(r => r.json()).catch(() => []),
          fetch('/api/settings').then(r => r.json()),
          fetch('/api/profiles').then(r => r.json()),
        ])
        setOrders(o)
        setTrades(tr)
        setSettings(st)
        setProfiles(pr)
        setLastRefresh(new Date())
      } catch { /* silent */ }
    }, dashboardRefreshMs)
    return () => clearInterval(id)
  }, [autoRefresh, dashboardRefreshMs])

  // Real-time positions + quotes via SSE → Kalshi WebSocket
  useEffect(() => {
    const es = new EventSource('/api/events')
    es.onmessage = (e) => {
      const msg = JSON.parse(e.data)
      if (msg.type === 'init') {
        setPositions(msg.data.positions)
        setQuotes(msg.data.quotes)
        setSnapshots(msg.data.snapshots ?? [])
        setWsConnected(msg.data.connected)
      } else if (msg.type === 'positions') {
        setPositions(msg.data)
      } else if (msg.type === 'quotes') {
        setQuotes(prev => ({ ...prev, ...msg.data }))
      } else if (msg.type === 'snapshots') {
        setSnapshots(msg.data)
      } else if (msg.type === 'status') {
        setWsConnected(msg.data.connected)
      }
    }
    es.onerror = () => setWsConnected(false)
    return () => es.close()
  }, [])

  // Open order tickers aren't in the WS subscription — poll for their quotes
  useEffect(() => {
    const tickers = [...new Set(openOrders.map(o => o.market_ticker))]
    if (tickers.length === 0) return
    const fetch_ = async () => {
      try {
        const data = await fetch(`/api/quotes?tickers=${tickers.join(',')}`).then(r => r.json())
        if (!data.error) setQuotes(prev => ({ ...prev, ...data }))
      } catch { /* silent */ }
    }
    fetch_()
    const id = setInterval(fetch_, 3_000)
    return () => clearInterval(id)
  }, [openOrders])

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
            <NavLink to="/markets" className={({ isActive }) => isActive ? 'nav-link nav-link-active' : 'nav-link'}>
              Markets
            </NavLink>
            <NavLink to="/backtest" className={({ isActive }) => isActive ? 'nav-link nav-link-active' : 'nav-link'}>
              Backtest
            </NavLink>
          </nav>
        </div>
        <div className="header-right">
          {error && <span style={{ color: '#ff4444', fontSize: 12 }}>{error}</span>}
          <span
            title={wsConnected ? 'Kalshi WS connected' : 'Kalshi WS reconnecting…'}
            style={{ fontSize: 11, color: wsConnected ? '#00d4a0' : '#f5c842', userSelect: 'none' }}
          >
            ● WS
          </span>
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
              trades={trades}
              openOrders={openOrders}
              positions={positions}
              snapshots={snapshots}
              quotes={quotes}
              settings={settings}
              profiles={profiles}
              balance={balance}
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
        <Route
          path="/markets"
          element={<Snapshots snapshots={snapshots} />}
        />
        <Route path="/backtest" element={<Backtest />} />
      </Routes>
    </div>
  )
}
