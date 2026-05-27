import { useState, useEffect, useCallback } from 'react'

// ── Types ────────────────────────────────────────────────────────────────────────────────
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

interface Settings {
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

interface Profile {
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
}

interface StrategyDraft {
  name: string
  min_entry_cents: number
  max_entry_cents: number
  proactive_mode: boolean
  max_open_orders: number
  max_daily_spend_cents: number
  scan_interval_seconds: number
  btc_series_tickers: string[]
}

// ── Helpers ──────────────────────────────────────────────────────────────────────────────
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

function fmtTickers(raw: string | string[] | null | undefined): string {
  if (!raw) return '—'
  const tickers = Array.isArray(raw) ? raw : raw.split(',')
  return tickers.map(t => t.trim()).filter(Boolean).join(', ') || '—'
}

function profileToDraft(profile: Profile): StrategyDraft {
  return {
    name: profile.name,
    min_entry_cents: profile.min_entry_cents,
    max_entry_cents: profile.max_entry_cents,
    proactive_mode: profile.proactive_mode,
    max_open_orders: profile.max_open_orders,
    max_daily_spend_cents: profile.max_daily_spend_cents,
    scan_interval_seconds: profile.scan_interval_seconds,
    btc_series_tickers: profile.btc_series_tickers.split(',').map(t => t.trim()).filter(Boolean),
  }
}

function settingsToDraft(settings: Settings, name = ''): StrategyDraft {
  return {
    name,
    min_entry_cents: settings.min_entry_cents,
    max_entry_cents: settings.max_entry_cents,
    proactive_mode: settings.proactive_mode,
    max_open_orders: settings.max_open_orders,
    max_daily_spend_cents: settings.max_daily_spend_cents,
    scan_interval_seconds: settings.scan_interval_seconds,
    btc_series_tickers: settings.btc_series_tickers,
  }
}

// ── Sub-components ───────────────────────────────────────────────────────────────────────
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

// ── Main ─────────────────────────────────────────────────────────────────────────────────
export default function App() {
  const [stats,     setStats]     = useState<Stats | null>(null)
  const [orders,    setOrders]    = useState<Order[]>([])
  const [snapshots, setSnapshots] = useState<Snapshot[]>([])
  const [settings,  setSettings]  = useState<Settings | null>(null)
  const [profiles,  setProfiles]  = useState<Profile[]>([])
  const [tab,       setTab]       = useState<'orders' | 'snapshots' | 'strategies'>('orders')
  const [selectedProfile, setSelectedProfile] = useState<number | 'all'>('all')
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [activating, setActivating] = useState(false)
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState<string | null>(null)
  const [saving,    setSaving]    = useState(false)
  const [strategyEditor, setStrategyEditor] = useState<{ mode: 'new' | 'edit'; profileId?: number; draft: StrategyDraft } | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    const profileQuery = selectedProfile !== 'all' ? `?profile_id=${selectedProfile}` : ''
    const profileParam = selectedProfile !== 'all' ? `&profile_id=${selectedProfile}` : ''
    try {
      const [s, o, sn, st, pr] = await Promise.all([
        fetch(`/api/stats${profileQuery}`).then(r => { if (!r.ok) throw new Error('stats'); return r.json() }),
        fetch(`/api/orders?limit=200${profileParam}`).then(r => { if (!r.ok) throw new Error('orders'); return r.json() }),
        fetch('/api/snapshots?limit=100').then(r => { if (!r.ok) throw new Error('snapshots'); return r.json() }),
        fetch('/api/settings').then(r => { if (!r.ok) throw new Error('settings'); return r.json() }),
        fetch('/api/profiles').then(r => { if (!r.ok) throw new Error('profiles'); return r.json() }),
      ])
      setStats(s)
      setOrders(o)
      setSnapshots(sn)
      setSettings(st)
      setProfiles(pr)
      setLastRefresh(new Date())
    } catch (e: any) {
      setError('API unavailable — bot may be starting up')
    } finally {
      setLoading(false)
    }
  }, [selectedProfile])

  useEffect(() => { refresh() }, [refresh])

  useEffect(() => {
    if (!autoRefresh || tab === 'strategies') return
    const id = setInterval(refresh, 5_000)
    return () => clearInterval(id)
  }, [autoRefresh, refresh, tab])

  const saveStrategy = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!strategyEditor) return
    setSaving(true)
    try {
      const resp = await fetch(strategyEditor.mode === 'edit' ? `/api/profiles/${strategyEditor.profileId}` : '/api/profiles', {
        method: strategyEditor.mode === 'edit' ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(strategyEditor.draft)
      })
      if (!resp.ok) throw new Error('Failed to save strategy')
      setStrategyEditor(null)
      await refresh()
    } catch (err: any) {
      alert(err.message)
    } finally {
      setSaving(false)
    }
  }

  const activateProfile = async (profileId: number) => {
    setActivating(true)
    try {
      const resp = await fetch(`/api/profiles/${profileId}/activate`, { method: 'POST' })
      if (!resp.ok) throw new Error('Failed to activate strategy')
      setStrategyEditor(null)
      await refresh()
    } catch (err: any) {
      alert(err.message)
    } finally {
      setActivating(false)
    }
  }

  const pnl = stats?.total_pnl_cents
  const pnlColor = pnl == null ? undefined : pnl > 0 ? '#00d4a0' : pnl < 0 ? '#ff4444' : undefined
  const wrColor = stats?.win_rate == null ? undefined : stats.win_rate >= 50 ? '#00d4a0' : '#ff4444'
  const activeProfile = profiles.find(p => p.id === settings?.active_profile_id)
  const updateStrategyDraft = (patch: Partial<StrategyDraft>) => {
    setStrategyEditor(editor => editor ? { ...editor, draft: { ...editor.draft, ...patch } } : editor)
  }

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
        <button className={`tab${tab === 'strategies' ? ' active' : ''}`} onClick={() => setTab('strategies')}>
          Strategies <span className="tab-count">{profiles.length}</span>
        </button>
      </div>

      <div style={{ padding: '0 16px 12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span className="stat-label">Filter Stats by Profile:</span>
        <select 
          className="btn" 
          style={{ background: 'rgba(255,255,255,0.05)', padding: '4px 12px' }}
          value={selectedProfile}
          onChange={(e) => setSelectedProfile(e.target.value === 'all' ? 'all' : parseInt(e.target.value))}
        >
          <option value="all">All Strategies</option>
          {profiles.map(p => (
            <option key={p.id} value={p.id}>{p.name} {settings?.active_profile_id === p.id ? '(Active)' : ''}</option>
          ))}
        </select>
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

          {tab === 'strategies' && (
            <div className="strategies-view">
              {settings && (
                <section className="strategy-active-panel">
                  <div className="strategy-active-main">
                    <div className="stat-label">Active Strategy</div>
                    <h2>{activeProfile?.name || settings.name || 'Current settings'}</h2>
                    <p>
                      This is the live bot configuration. Create a new strategy from it, edit saved strategies,
                      or activate an older strategy from the cards below.
                    </p>
                    <div className="strategy-primary-actions">
                      <button
                        className="btn btn-active"
                        onClick={() => setStrategyEditor({ mode: 'new', draft: settingsToDraft(settings, '') })}
                      >
                        New Strategy
                      </button>
                      {activeProfile && (
                        <button
                          className="btn"
                          onClick={() => setStrategyEditor({ mode: 'edit', profileId: activeProfile.id, draft: profileToDraft(activeProfile) })}
                        >
                          Edit Active
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="strategy-metrics">
                    <div>
                      <span>Entry</span>
                      <strong>{settings.min_entry_cents}–{settings.max_entry_cents}¢</strong>
                    </div>
                    <div>
                      <span>Daily Limit</span>
                      <strong>{centsToUSD(settings.max_daily_spend_cents)}</strong>
                    </div>
                    <div>
                      <span>Max Orders</span>
                      <strong>{settings.max_open_orders}</strong>
                    </div>
                    <div>
                      <span>Mode</span>
                      <strong>{settings.proactive_mode ? 'Proactive' : 'Reactive'}</strong>
                    </div>
                  </div>
                </section>
              )}

              <section className="strategies-grid" aria-label="Saved strategies">
                {profiles.length === 0 ? (
                  <div className="strategy-empty">No strategies yet</div>
                ) : profiles.map(p => {
                  const isActive = settings?.active_profile_id === p.id
                  return (
                    <article key={p.id} className={`strategy-card${isActive ? ' is-active' : ''}`}>
                      <div className="strategy-card-head">
                        <div>
                          <div className="strategy-name">{p.name}</div>
                          <div className="strategy-created">Created {fmtTime(p.created_at)}</div>
                        </div>
                        {isActive && <span className="badge badge-live">ACTIVE</span>}
                      </div>
                      <div className="strategy-card-stats">
                        <div><span>Entry</span><strong>{p.min_entry_cents}–{p.max_entry_cents}¢</strong></div>
                        <div><span>Limit</span><strong>{centsToUSD(p.max_daily_spend_cents)}</strong></div>
                        <div><span>Orders</span><strong>{p.max_open_orders}</strong></div>
                        <div><span>Mode</span><strong>{p.proactive_mode ? 'Proactive' : 'Reactive'}</strong></div>
                      </div>
                      <div className="strategy-tickers">{fmtTickers(p.btc_series_tickers)}</div>
                      <div className="strategy-card-actions">
                        <button
                          className="btn"
                          onClick={() => setStrategyEditor({ mode: 'edit', profileId: p.id, draft: profileToDraft(p) })}
                        >
                          Edit
                        </button>
                        <button
                          className={`btn strategy-activate${isActive ? ' is-current' : ' btn-active'}`}
                          disabled={isActive || activating}
                          onClick={() => activateProfile(p.id)}
                        >
                          {isActive ? 'Active' : activating ? 'Activating…' : 'Activate'}
                        </button>
                      </div>
                    </article>
                  )
                })}
              </section>

              {strategyEditor && (
                <section className="strategy-config-panel">
                  <div className="strategy-section-head">
                    <div>
                      <div className="stat-label">{strategyEditor.mode === 'edit' ? 'Edit Strategy' : 'Create Strategy'}</div>
                      <h3>{strategyEditor.mode === 'edit' ? strategyEditor.draft.name : 'New Strategy'}</h3>
                    </div>
                    <p>{strategyEditor.mode === 'edit' ? 'Save changes to this strategy. If it is active, the live bot settings update too.' : 'Create a strategy from the current bot settings and make it active.'}</p>
                  </div>

                  <form onSubmit={saveStrategy} className="strategy-form">
                    <label className="field field-wide">
                      <span>Strategy Name</span>
                      <input
                        type="text"
                        value={strategyEditor.draft.name}
                        placeholder="Strategy snapshot name..."
                        onChange={e => updateStrategyDraft({ name: e.target.value })}
                      />
                    </label>

                    <label className="field">
                      <span>Min Entry</span>
                      <input
                        type="number"
                        value={strategyEditor.draft.min_entry_cents}
                        onChange={e => updateStrategyDraft({ min_entry_cents: parseInt(e.target.value) || 0 })}
                      />
                    </label>
                    <label className="field">
                      <span>Max Entry</span>
                      <input
                        type="number"
                        value={strategyEditor.draft.max_entry_cents}
                        onChange={e => updateStrategyDraft({ max_entry_cents: parseInt(e.target.value) || 0 })}
                      />
                    </label>
                    <label className="field">
                      <span>Max Open Orders</span>
                      <input
                        type="number"
                        value={strategyEditor.draft.max_open_orders}
                        onChange={e => updateStrategyDraft({ max_open_orders: parseInt(e.target.value) || 0 })}
                      />
                    </label>
                    <label className="field">
                      <span>Daily Limit</span>
                      <input
                        type="number"
                        value={strategyEditor.draft.max_daily_spend_cents}
                        onChange={e => updateStrategyDraft({ max_daily_spend_cents: parseInt(e.target.value) || 0 })}
                      />
                    </label>
                    <label className="field">
                      <span>Scan Interval</span>
                      <input
                        type="number"
                        value={strategyEditor.draft.scan_interval_seconds}
                        onChange={e => updateStrategyDraft({ scan_interval_seconds: parseInt(e.target.value) || 0 })}
                      />
                    </label>
                    <label className="field field-wide">
                      <span>BTC Series Tickers</span>
                      <input
                        type="text"
                        value={strategyEditor.draft.btc_series_tickers.join(', ')}
                        onChange={e => updateStrategyDraft({ btc_series_tickers: e.target.value.split(',').map(s => s.trim()).filter(Boolean) })}
                      />
                    </label>

                    <label className="strategy-toggle field-wide">
                      <input
                        type="checkbox"
                        checked={strategyEditor.draft.proactive_mode}
                        onChange={e => updateStrategyDraft({ proactive_mode: e.target.checked })}
                      />
                      <span>
                        <strong>Proactive Mode</strong>
                        <small>Place orders before price hits target</small>
                      </span>
                    </label>

                    <div className="strategy-form-actions field-wide">
                      <span>{strategyEditor.mode === 'edit' ? 'This edits the selected saved strategy.' : 'New strategies are activated immediately after saving.'}</span>
                      <div className="strategy-form-buttons">
                        <button type="button" className="btn" onClick={() => setStrategyEditor(null)}>Cancel</button>
                        <button type="submit" className="btn btn-active" disabled={saving}>
                          {saving ? 'Saving…' : strategyEditor.mode === 'edit' ? 'Save Strategy' : 'Create and Activate'}
                        </button>
                      </div>
                    </div>
                  </form>
                </section>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
