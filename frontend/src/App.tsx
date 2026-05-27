import { useState, useEffect, useCallback } from 'react'

// ── Types ──────────────────────────────────────────────────────────────────
interface Stats {
  today_spend_cents: number
  resting: number
  filled: number
  canceled: number
  wins: number
  losses: number
  win_rate: number | null
  total_pnl_cents: number
  total_orders: number
  snap_count: number
}

interface Order {
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

interface Snapshot {
  id: number
  ticker: string
  title: string
  scanned_at: string
  close_time: string | null
  yes_ask: number | null
  no_ask: number | null
  yes_bid: number | null
  no_bid: number | null
  time_to_close_secs: number | null
  strike_str: string | null
  volume: number | null
  open_interest: number | null
}

// ── Helpers ────────────────────────────────────────────────────────────────
function centsToUSD(c: number | null | undefined): string {
  if (c == null) return '—'
  return `$${(c / 100).toFixed(2)}`
}

function fmtPnL(c: number | null | undefined): string {
  if (c == null) return '—'
  const sign = c > 0 ? '+' : ''
  return `${sign}${c}¢`
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function fmtDur(secs: number | null | undefined): string {
  if (secs == null) return '—'
  if (secs < 60) return `${secs}s`
  const m = Math.floor(secs / 60)
  const s = secs % 60
  return s ? `${m}m ${s}s` : `${m}m`
}

function fmtStrike(raw: string | null | undefined): string {
  if (!raw) return '—'
  const n = parseFloat(raw)
  return isNaN(n) ? raw : `$${n.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

// ── Sub-components ───────────────────────────────────────────────────────────────
function StatCard({
  label, value, sub, color,
}: {
  label: string; value: string; sub?: string; color?: string
}) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value" style={color ? { color } : undefined}>{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}

function StatusBadge({ status, outcome }: { status: string; outcome: string | null }) {
  if (status === 'filled' && outcome === 'win') {
    return <span className="badge" style={{ color: '#00d4a0', background: 'rgba(0,212,160,0.14)' }}>WIN</span>
  }
  if (status === 'filled' && outcome === 'loss') {
    return <span className="badge" style={{ color: '#ff4444', background: 'rgba(255,68,68,0.14)' }}>LOSS</span>
  }
  const map: Record<string, [string, string, string]> = {
    resting:  ['RESTING',  '#f5c842', 'rgba(245,200,66,0.14)'],
    filled:   ['FILLED',   '#60a5fa', 'rgba(96,165,250,0.14)'],
    canceled: ['CANCELED', '#9ca3af', 'rgba(156,163,175,0.10)'],
    pending:  ['PENDING',  '#a78bfa', 'rgba(167,139,250,0.14)'],
  }
  const [label, color, bg] = map[status] ?? [status.toUpperCase(), '#9ca3af', 'rgba(156,163,175,0.10)']
  return <span className="badge" style={{ color, background: bg }}>{label}</span>
}

// ── Main ─────────────────────────────────────────────────────────────────────────
export default function App() {
  const [stats,     setStats]     = useState<Stats | null>(null)
  const [orders,    setOrders]    = useState<Order[]>([])
  const [snapshots, setSnapshots] = useState<Snapshot[]>([])
  const [tab,       setTab]       = useState<'orders' | 'snapshots'>('orders')
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [s, o, sn] = await Promise.all([
        fetch('/api/stats').then(r => { if (!r.ok) throw new Error('stats'); return r.json() }),
        fetch('/api/orders?limit=200').then(r => { if (!r.ok) throw new Error('orders'); return r.json() }),
        fetch('/api/snapshots?limit=100').then(r => { if (!r.ok) throw new Error('snapshots'); return r.json() }),
      ])
      setStats(s)
      setOrders(o)
      setSnapshots(sn)
      setLastRefresh(new Date())
    } catch (e: any) {
      setError('API unavailable — bot may be starting up')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  useEffect(() => {
    if (!autoRefresh) return
    const id = setInterval(refresh, 5_000)
    return () => clearInterval(id)
  }, [autoRefresh, refresh])

  const pnl = stats?.total_pnl_cents
  const pnlColor = pnl == null ? undefined : pnl > 0 ? '#00d4a0' : pnl < 0 ? '#ff4444' : undefined
  const wrColor = stats?.win_rate == null ? undefined : stats.win_rate >= 50 ? '#00d4a0' : '#ff4444'

  return (
    <div className="app">
      {/* Header */}
      <header className="header">
        <div className="header-left">
          <span className="header-logo">⧟</span>
          <span className="header-title">Kalshi Bot</span>
          <span className="header-sub">BTC 15-Min Longshot</span>
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

      {/* Stats */}
      <div className="stats-row">
        <StatCard label="Today Spent"  value={centsToUSD(stats?.today_spend_cents)} />
        <StatCard label="Open Orders"  value={stats?.resting  == null ? '—' : String(stats.resting)}  color="#f5c842" />
        <StatCard label="Filled"       value={stats?.filled   == null ? '—' : String(stats.filled)} />
        <StatCard label="Canceled"     value={stats?.canceled == null ? '—' : String(stats.canceled)} color="#9ca3af" />
        <StatCard label="Wins"         value={stats?.wins     == null ? '—' : String(stats.wins)}  color="#00d4a0" />
        <StatCard label="Losses"       value={stats?.losses   == null ? '—' : String(stats.losses)} color="#ff4444" />
        <StatCard
          label="Win Rate"
          value={stats?.win_rate != null ? `${stats.win_rate}%` : '—'}
          sub={stats ? `${stats.wins + stats.losses} settled` : undefined}
          color={wrColor}
        />
        <StatCard
          label="Net P&L"
          value={fmtPnL(pnl)}
          sub={pnl != null ? centsToUSD(pnl) : undefined}
          color={pnlColor}
        />
      </div>

      {/* Tabs */}
      <div className="tabs">
        <button className={`tab${tab === 'orders' ? ' active' : ''}`} onClick={() => setTab('orders')}>
          Orders <span className="tab-count">{orders.length}</span>
        </button>
        <button className={`tab${tab === 'snapshots' ? ' active' : ''}`} onClick={() => setTab('snapshots')}>
          Snapshots <span className="tab-count">{snapshots.length}</span>
        </button>
      </div>

      {/* Panel */}
      <div className="table-panel">
        <div className="table-wrap">
          {tab === 'orders' && (
            <table>
              <thead>
                <tr>
                  <th>Market</th>
                  <th>Side</th>
                  <th>Entry</th>
                  <th>Status</th>
                  <th>Placed</th>
                  <th>TTC</th>
                  <th>Payout</th>
                  <th>Net P&L</th>
                </tr>
              </thead>
              <tbody>
                {orders.length === 0 ? (
                  <tr><td colSpan={8} className="cell-empty">No orders yet</td></tr>
                ) : orders.map(o => (
                  <tr key={o.id}>
                    <td className="cell-ticker">{o.market_ticker}</td>
                    <td>
                      <span className={`badge ${o.side === 'yes' ? 'side-yes' : 'side-no'}`}>
                        {o.side.toUpperCase()}
                      </span>
                    </td>
                    <td>{o.entry_price_cents}¢</td>
                    <td><StatusBadge status={o.status} outcome={o.outcome} /></td>
                    <td className="cell-dim">{fmtTime(o.placed_at)}</td>
                    <td className="cell-dim">{fmtDur(o.time_to_close_at_placement)}</td>
                    <td className="cell-dim">{o.payout_cents != null ? `${o.payout_cents}¢` : '—'}</td>
                    <td className={o.net_profit_cents != null ? (o.net_profit_cents >= 0 ? 'cell-profit' : 'cell-loss') : 'cell-dim'}>
                      {fmtPnL(o.net_profit_cents)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {tab === 'snapshots' && (
            <table>
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th>BTC Strike</th>
                  <th>Yes Ask¢</th>
                  <th>No Ask¢</th>
                  <th>Volume</th>
                  <th>OI</th>
                  <th>TTC</th>
                  <th>Scanned</th>
                </tr>
              </thead>
              <tbody>
                {snapshots.length === 0 ? (
                  <tr><td colSpan={8} className="cell-empty">No snapshots yet</td></tr>
                ) : snapshots.map(s => (
                  <tr key={s.id}>
                    <td className="cell-ticker">{s.ticker}</td>
                    <td className="cell-dim">{fmtStrike(s.strike_str)}</td>
                    <td>{s.yes_ask ?? '—'}</td>
                    <td>{s.no_ask ?? '—'}</td>
                    <td className="cell-dim">{s.volume?.toLocaleString() ?? '—'}</td>
                    <td className="cell-dim">{s.open_interest?.toLocaleString() ?? '—'}</td>
                    <td className="cell-dim">{fmtDur(s.time_to_close_secs)}</td>
                    <td className="cell-dim">{fmtTime(s.scanned_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
