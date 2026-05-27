import { useState, useEffect, useCallback } from 'react'

// ── Types ────────────────────────────────────────────────────────────────────────────────
interface Position {
  ticker: string
  position_fp: string
  total_traded_dollars: string
  market_exposure_dollars: string
  realized_pnl_dollars: string
  fees_paid_dollars: string
  last_updated_ts: string
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

function fmtTickers(raw: string | string[] | null | undefined): string {
  if (!raw) return '—'
  const tickers = Array.isArray(raw) ? raw : raw.split(',')
  return tickers.map(t => t.trim()).filter(Boolean).join(', ') || '—'
}

function kalshiMarketUrl(ticker: string): string {
  const lower = ticker.toLowerCase()
  const parts = lower.split('-')
  const marketSlug = parts.slice(0, -1).join('-')
  const series = parts[0]
  return `https://kalshi.com/markets/${series}/${marketSlug}`
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
  const [orders,    setOrders]    = useState<Order[]>([])
  const [positions, setPositions] = useState<Position[] | { error: string }>([])
  const [quotes,    setQuotes]    = useState<Record<string, { yes_ask: number|null, no_ask: number|null, yes_bid: number|null, no_bid: number|null, open_interest: number|null }>>({})
  const [settings,  setSettings]  = useState<Settings | null>(null)
  const [profiles,  setProfiles]  = useState<Profile[]>([])
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
    try {
      const [o, pos, st, pr] = await Promise.all([
        fetch('/api/orders?limit=200').then(r => { if (!r.ok) throw new Error('orders'); return r.json() }),
        fetch('/api/positions').then(r => r.json()).catch(() => []),
        fetch('/api/settings').then(r => { if (!r.ok) throw new Error('settings'); return r.json() }),
        fetch('/api/profiles').then(r => { if (!r.ok) throw new Error('profiles'); return r.json() }),
      ])
      setOrders(o)
      setPositions(pos)
      setSettings(st)
      setProfiles(pr)
      setLastRefresh(new Date())
    } catch (e: any) {
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

      {/* Strategies */}
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

      {/* Active Positions */}
      <div className="table-panel" style={{ marginTop: 16, marginLeft: 18, marginRight: 18 }}>
        <div style={{ padding: '10px', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontWeight: 600, fontSize: 13 }}>Active Positions</span>
          <span className="tab-count">{Array.isArray(positions) ? positions.length : 0}</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Market</th>
                <th>Side</th>
                <th>Contracts</th>
                <th>Cost</th>
                <th>Ask</th>
                <th>OI</th>
                <th>Realized P&L</th>
              </tr>
            </thead>
            <tbody>
              {!Array.isArray(positions) ? (
                <tr><td colSpan={6} className="cell-empty" style={{ color: '#ff4444' }}>Error: {(positions as any).error}</td></tr>
              ) : positions.length === 0 ? (
                <tr><td colSpan={7} className="cell-empty">No active positions</td></tr>
              ) : (positions as Position[]).map(p => {
                const contracts = parseFloat(p.position_fp)
                const side = contracts >= 0 ? 'yes' : 'no'
                const pnl = parseFloat(p.realized_pnl_dollars)
                const q = quotes[p.ticker]
                const ask = q ? (side === 'yes' ? q.yes_ask : q.no_ask) : null
                return (
                  <tr key={p.ticker}>
                    <td className="cell-ticker">
                      <a href={kalshiMarketUrl(p.ticker)} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                        {p.ticker}
                      </a>
                    </td>
                    <td>
                      <span className={`badge ${side === 'yes' ? 'side-yes' : 'side-no'}`}>
                        {side.toUpperCase()}
                      </span>
                    </td>
                    <td>{Math.abs(contracts)}</td>
                    <td className="cell-dim">${p.total_traded_dollars}</td>
                    <td className="cell-dim">{ask != null ? `${ask}¢` : '—'}</td>
                    <td className="cell-dim">{q?.open_interest != null ? q.open_interest.toLocaleString() : '—'}</td>
                    <td className={pnl > 0 ? 'cell-profit' : pnl < 0 ? 'cell-loss' : 'cell-dim'}>
                      {pnl > 0 ? '+' : ''}${p.realized_pnl_dollars}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Open Orders */}
      <div className="table-panel" style={{ marginTop: 16, marginLeft: 18, marginRight: 18 }}>
        <div style={{ padding: '10px', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontWeight: 600, fontSize: 13 }}>Open Orders</span>
          <span className="tab-count">{openOrders.length}</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Market</th>
                <th>Side</th>
                <th>Entry</th>
                <th>Ask</th>
                <th>OI</th>
                <th>Status</th>
                <th>Placed</th>
                <th>TTC</th>
              </tr>
            </thead>
            <tbody>
              {openOrders.length === 0 ? (
                <tr><td colSpan={8} className="cell-empty">No open orders</td></tr>
              ) : openOrders.map(o => {
                const q = quotes[o.market_ticker]
                const ask = q ? (o.side === 'yes' ? q.yes_ask : q.no_ask) : null
                return (
                <tr key={o.id}>
                  <td className="cell-ticker">
                    <a href={kalshiMarketUrl(o.market_ticker)} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                      {o.market_ticker}
                    </a>
                  </td>
                  <td>
                    <span className={`badge ${o.side === 'yes' ? 'side-yes' : 'side-no'}`}>
                      {o.side.toUpperCase()}
                    </span>
                  </td>
                  <td>{o.entry_price_cents}¢</td>
                  <td className="cell-dim">{ask != null ? `${ask}¢` : '—'}</td>
                  <td className="cell-dim">{q?.open_interest != null ? q.open_interest.toLocaleString() : '—'}</td>
                  <td><StatusBadge status={o.status} outcome={o.outcome} /></td>
                  <td className="cell-dim">{fmtTime(o.placed_at)}</td>
                  <td className="cell-dim">{fmtDur(o.time_to_close_at_placement)}</td>
                </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Order History */}
      {(() => {
        const history = orders.filter(o => o.status !== 'resting')
        return (
          <div className="table-panel" style={{ marginTop: 16, marginLeft: 18, marginRight: 18, marginBottom: 32 }}>
            <div style={{ padding: '10px', display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontWeight: 600, fontSize: 13 }}>Order History</span>
              <span className="tab-count">{history.length}</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Market</th>
                    <th>Side</th>
                    <th>Entry</th>
                    <th>Qty</th>
                    <th>Result</th>
                    <th>P&L</th>
                    <th>Placed</th>
                    <th>Filled</th>
                  </tr>
                </thead>
                <tbody>
                  {history.length === 0 ? (
                    <tr><td colSpan={8} className="cell-empty">No order history</td></tr>
                  ) : history.map(o => (
                    <tr key={o.id}>
                      <td className="cell-ticker">
                        <a href={kalshiMarketUrl(o.market_ticker)} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                          {o.market_ticker}
                        </a>
                      </td>
                      <td>
                        <span className={`badge ${o.side === 'yes' ? 'side-yes' : 'side-no'}`}>
                          {o.side.toUpperCase()}
                        </span>
                      </td>
                      <td>{o.entry_price_cents}¢</td>
                      <td>{o.count}</td>
                      <td><StatusBadge status={o.status} outcome={o.outcome} /></td>
                      <td className={o.net_profit_cents != null && o.net_profit_cents > 0 ? 'cell-profit' : o.net_profit_cents != null && o.net_profit_cents < 0 ? 'cell-loss' : 'cell-dim'}>
                        {o.net_profit_cents != null ? fmtPnL(o.net_profit_cents) : '—'}
                      </td>
                      <td className="cell-dim">{fmtTime(o.placed_at)}</td>
                      <td className="cell-dim">{fmtTime(o.filled_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
      })()}
    </div>
  )
}
