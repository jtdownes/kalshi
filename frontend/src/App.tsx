import { useState, useEffect, useCallback } from 'react'
import { Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Strategies from './pages/Strategies'
import Snapshots from './pages/Snapshots'
import MarketsClimate from './pages/MarketsClimate'
import MarketsCrypto from './pages/MarketsCrypto'
import type { Position, Order, Trade, Snapshot, Settings, Profile, Quotes } from './types'
import { fmtTime } from './utils'
export type { Position, Order, Trade, Snapshot, Settings, Profile, Quotes }
export type { RuleField, RuleOp, RuleCondition, RuleEntry, RuleExit, RuleAction, StrategyRule } from './types'
export { centsToUSD, fmtPnL, fmtCents, fmtTime, fmtUnixTime, fmtDur, fmtTickers, kalshiMarketUrl } from './utils'

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
        </div>
        <nav className="header-nav">
          <NavLink to="/" end className={({ isActive }) => isActive ? 'nav-link nav-link-active' : 'nav-link'}>
            Dashboard
          </NavLink>
          <NavLink to="/strategies" className={({ isActive }) => isActive ? 'nav-link nav-link-active' : 'nav-link'}>
            Strategies
          </NavLink>
          <div className="nav-dropdown">
            <NavLink to="/markets" end className={({ isActive }) => isActive ? 'nav-link nav-link-active' : 'nav-link'}>
              Markets ▾
            </NavLink>
            <div className="nav-dropdown-menu">
              <NavLink to="/markets" end className={({ isActive }) => isActive ? 'nav-dropdown-item nav-dropdown-item-active' : 'nav-dropdown-item'}>
                All Markets
              </NavLink>
              <NavLink to="/markets/crypto" className={({ isActive }) => isActive ? 'nav-dropdown-item nav-dropdown-item-active' : 'nav-dropdown-item'}>
                Crypto (BTC)
              </NavLink>
              <NavLink to="/markets/climate" className={({ isActive }) => isActive ? 'nav-dropdown-item nav-dropdown-item-active' : 'nav-dropdown-item'}>
                Climate
              </NavLink>
            </div>
          </div>
        </nav>
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
          element={<Snapshots snapshots={snapshots} orders={orders} openOrders={orders.filter(o => o.status === 'resting')} />}
        />
        <Route
          path="/markets/climate"
          element={<MarketsClimate snapshots={snapshots} orders={orders} openOrders={orders.filter(o => o.status === 'resting')} />}
        />
        <Route
          path="/markets/crypto"
          element={<MarketsCrypto snapshots={snapshots} orders={orders} openOrders={orders.filter(o => o.status === 'resting')} />}
        />
      </Routes>
    </div>
  )
}
