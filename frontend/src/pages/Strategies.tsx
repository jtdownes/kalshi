import { useState, useEffect } from 'react'
import type { Settings, Profile } from '../App'
import { centsToUSD, fmtTime, fmtTickers } from '../App'

const SUPPORTED_STRATEGY_MARKETS = [
  { value: 'KXBTC15M', label: 'Bitcoin 15 Minute' },
] as const

interface StrategyDraft {
  name: string
  min_entry_cents: number
  max_entry_cents: number
  proactive_mode: boolean
  max_open_orders: number
  max_daily_spend_cents: number
  btc_series_tickers: string[]
  exit_strategy: 'hold_to_expiration' | 'limit_sell'
  limit_sell_price_cents: number | null
  min_time_to_close_secs: number | null
  max_time_to_close_secs: number | null
}

interface Trade {
  market_ticker: string
  order_count: number
  placed_at: string
  filled_at: string | null
  filled_side: string | null
  market_close_time: string | null
  entry_price_cents: number | null
  net_profit_cents: number | null
  status: string
  outcome: string | null
  peak_price_cents: number | null
}

function formatExitStrategy(exitStrategy: StrategyDraft['exit_strategy'] | Profile['exit_strategy'] | Settings['exit_strategy']): string {
  return exitStrategy === 'limit_sell' ? 'Limit Sell' : 'Hold to Expiration'
}

function formatExitTarget(limitSellPriceCents: number | null | undefined): string {
  return limitSellPriceCents == null ? '—' : `${limitSellPriceCents}¢`
}

function normalizeStrategyMarkets(raw: string[]): string[] {
  const selected = raw.find(Boolean)
  return selected ? [selected] : [SUPPORTED_STRATEGY_MARKETS[0].value]
}

function profileToDraft(profile: Profile): StrategyDraft {
  return {
    name: profile.name,
    min_entry_cents: profile.min_entry_cents,
    max_entry_cents: profile.max_entry_cents,
    proactive_mode: profile.proactive_mode,
    max_open_orders: profile.max_open_orders,
    max_daily_spend_cents: profile.max_daily_spend_cents,
    btc_series_tickers: normalizeStrategyMarkets(profile.btc_series_tickers.split(',').map(t => t.trim()).filter(Boolean)),
    exit_strategy: profile.exit_strategy,
    limit_sell_price_cents: profile.limit_sell_price_cents,
    min_time_to_close_secs: profile.min_time_to_close_secs,
    max_time_to_close_secs: profile.max_time_to_close_secs,
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
    btc_series_tickers: normalizeStrategyMarkets(settings.btc_series_tickers),
    exit_strategy: settings.exit_strategy,
    limit_sell_price_cents: settings.limit_sell_price_cents,
    min_time_to_close_secs: settings.min_time_to_close_secs,
    max_time_to_close_secs: settings.max_time_to_close_secs,
  }
}

interface Props {
  settings: Settings | null
  profiles: Profile[]
  refresh: () => Promise<void>
}

export default function Strategies({ settings, profiles, refresh }: Props) {
  const [viewModal,        setViewModal]        = useState<{ profile: Profile; trades: Trade[]; loading: boolean } | null>(null)
  const [newStrategyDraft, setNewStrategyDraft] = useState<StrategyDraft | null>(null)
  const [renameModal,      setRenameModal]      = useState<{ profileId: number; name: string } | null>(null)
  const [saving,           setSaving]           = useState(false)
  const [activating,       setActivating]       = useState(false)

  // Escape closes the topmost open modal first
  useEffect(() => {
    if (!viewModal && !newStrategyDraft && !renameModal) return
    const handler = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      if (renameModal)      { setRenameModal(null);      return }
      if (newStrategyDraft) { setNewStrategyDraft(null); return }
      if (viewModal)        { setViewModal(null);        return }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [viewModal, newStrategyDraft, renameModal])

  const activeProfile = profiles.find(p => p.id === settings?.active_profile_id)

  const updateDraft = (patch: Partial<StrategyDraft>) =>
    setNewStrategyDraft(d => d ? { ...d, ...patch } : d)

  const openViewModal = async (profile: Profile) => {
    setNewStrategyDraft(null)
    setViewModal({ profile, trades: [], loading: true })
    try {
      const resp = await fetch(`/api/trades?profile_id=${profile.id}&limit=200`)
      const trades = resp.ok ? await resp.json() : []
      setViewModal(v => v ? { ...v, trades, loading: false } : v)
    } catch {
      setViewModal(v => v ? { ...v, loading: false } : v)
    }
  }

  const saveStrategy = async (ev: React.FormEvent) => {
    ev.preventDefault()
    if (!newStrategyDraft) return
    if (newStrategyDraft.exit_strategy === 'limit_sell' && newStrategyDraft.limit_sell_price_cents == null) {
      alert('Set a limit sell price before saving a limit sell strategy')
      return
    }
    setSaving(true)
    try {
      const resp = await fetch('/api/profiles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newStrategyDraft),
      })
      if (!resp.ok) throw new Error('Failed to save strategy')
      setNewStrategyDraft(null)
      await refresh()
    } catch (err: any) {
      alert(err.message)
    } finally {
      setSaving(false)
    }
  }

  const saveRename = async (ev: React.FormEvent) => {
    ev.preventDefault()
    if (!renameModal) return
    const profile = profiles.find(p => p.id === renameModal.profileId)
    if (!profile) return
    setSaving(true)
    try {
      const resp = await fetch(`/api/profiles/${renameModal.profileId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...profileToDraft(profile), name: renameModal.name }),
      })
      if (!resp.ok) throw new Error('Failed to rename strategy')
      setRenameModal(null)
      if (viewModal?.profile.id === renameModal.profileId) {
        setViewModal(v => v ? { ...v, profile: { ...v.profile, name: renameModal.name } } : v)
      }
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
      if (viewModal?.profile.id === profileId)
        setViewModal(v => v ? { ...v, profile: { ...v.profile, is_active: true } } : v)
      await refresh()
    } catch (err: any) {
      alert(err.message)
    } finally {
      setActivating(false)
    }
  }

  const deactivateProfile = async (profileId: number) => {
    setActivating(true)
    try {
      const resp = await fetch(`/api/profiles/${profileId}/deactivate`, { method: 'POST' })
      if (!resp.ok) throw new Error('Failed to deactivate strategy')
      if (viewModal?.profile.id === profileId)
        setViewModal(v => v ? { ...v, profile: { ...v.profile, is_active: false } } : v)
      await refresh()
    } catch (err: any) {
      alert(err.message)
    } finally {
      setActivating(false)
    }
  }

  return (
    <div className="strategies-view">
      {settings && (
        <section className="strategy-active-panel">
          <div className="strategy-active-main">
            <div className="stat-label">Active Strategy</div>
            <h2>{activeProfile?.name || settings.name || 'Current settings'}</h2>
            <div className="strategy-primary-actions">
              <button
                className="btn btn-active"
                onClick={() => setNewStrategyDraft(settingsToDraft(settings))}
              >
                New Strategy
              </button>
            </div>
          </div>
          <div className="strategy-metrics-wrap">
            <div className="strategy-metrics strategy-metrics-compact">
              <div><span>Max Bid</span><strong>{settings.max_entry_cents}¢</strong></div>
              <div><span>Daily Limit</span><strong>{centsToUSD(settings.max_daily_spend_cents)}</strong></div>
              <div><span>Mode</span><strong>{settings.proactive_mode ? 'Proactive' : 'Reactive'}</strong></div>
              <div><span>Exit</span><strong>{formatExitStrategy(settings.exit_strategy)}</strong></div>
            </div>
          </div>
        </section>
      )}

      <section className="strategies-grid" aria-label="Saved strategies">
        {profiles.length === 0 ? (
          <div className="strategy-empty">No strategies yet</div>
        ) : profiles.map(p => {
          const isActive = p.is_active
          return (
            <article
              key={p.id}
              className={`strategy-card${isActive ? ' is-active' : ''}${viewModal?.profile.id === p.id ? ' is-selected' : ''}`}
              role="button"
              tabIndex={0}
              onClick={() => openViewModal(p)}
              onKeyDown={e => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openViewModal(p) }
              }}
            >
              <div className="strategy-card-head">
                <div className="strategy-title-block">
                  <div className="strategy-name">{p.name}</div>
                  <div className="strategy-created">Created {fmtTime(p.created_at)}</div>
                </div>
                <div className="strategy-card-head-right">
                  {isActive && <span className="badge badge-live">ACTIVE</span>}
                  <span className="strategy-chip strategy-chip-dim">{fmtTickers(p.btc_series_tickers)}</span>
                </div>
              </div>

              <div className="strategy-ticket-band">
                <div className="strategy-ticket-metric">
                  <span>Daily Spend Ceiling</span>
                  <strong>{centsToUSD(p.max_daily_spend_cents)}</strong>
                </div>
                <div className="strategy-ticket-metric">
                  <span>Max Entry</span>
                  <strong>{p.max_entry_cents}¢</strong>
                </div>
                <div className="strategy-ticket-metric">
                  <span>Historical Runs</span>
                  <strong>{(p.order_count ?? 0).toLocaleString()}</strong>
                </div>
                {(() => {
                  const wins = p.win_count ?? 0
                  const losses = p.loss_count ?? 0
                  const resolved = wins + losses
                  const rate = resolved > 0 ? Math.round((wins / resolved) * 100) : null
                  return (
                    <div className="strategy-ticket-metric">
                      <span>Win Rate</span>
                      <strong style={{ color: rate == null ? undefined : rate >= 50 ? '#00d4a0' : '#ff4444' }}>
                        {rate == null ? '—' : `${rate}%`}
                        {resolved > 0 && <span style={{ fontWeight: 400, fontSize: 11, color: '#64748b', marginLeft: 5 }}>{wins}W / {losses}L</span>}
                      </strong>
                    </div>
                  )
                })()}
                <div className="strategy-ticket-metric">
                  <span>Total Spent</span>
                  <strong>{centsToUSD(p.total_spend_cents ?? 0)}</strong>
                </div>
                <div className="strategy-ticket-metric">
                  <span>Total P&amp;L</span>
                  <strong style={{ color: (p.total_profit_cents ?? 0) > 0 ? '#00d4a0' : (p.total_profit_cents ?? 0) < 0 ? '#ff4444' : undefined }}>
                    {(p.total_profit_cents ?? 0) >= 0 ? '+' : ''}{centsToUSD(p.total_profit_cents ?? 0)}
                  </strong>
                </div>
              </div>

              <div className="strategy-card-foot">
                <span className="strategy-chip">{formatExitStrategy(p.exit_strategy)}</span>
                {p.limit_sell_price_cents != null && <span className="strategy-chip">Target {formatExitTarget(p.limit_sell_price_cents)}</span>}
                {(p.min_time_to_close_secs != null || p.max_time_to_close_secs != null) && (
                  <span className="strategy-chip">
                    TTC {p.min_time_to_close_secs != null ? `${p.min_time_to_close_secs / 60}` : '0'}–{p.max_time_to_close_secs != null ? `${p.max_time_to_close_secs / 60}m` : '∞'}
                  </span>
                )}
                <span className="strategy-chip strategy-chip-dim">View details</span>
              </div>
            </article>
          )
        })}
      </section>

      {/* ── Strategy view modal ── */}
      {viewModal && (
        <div className="strategy-modal-backdrop" onClick={() => setViewModal(null)}>
          <div className="strategy-modal strategy-modal-view" onClick={e => e.stopPropagation()}>
            <section className="strategy-config-panel">

              <div className="strategy-section-head">
                <div>
                  <div className="stat-label">Strategy</div>
                  <h3>
                    {viewModal.profile.name}
                    {viewModal.profile.is_active && (
                      <span className="badge badge-live" style={{ marginLeft: 10, verticalAlign: 'middle' }}>ACTIVE</span>
                    )}
                  </h3>
                  <div style={{ color: '#64748b', fontSize: 12, marginTop: 4 }}>
                    Created {fmtTime(viewModal.profile.created_at)} · {fmtTickers(viewModal.profile.btc_series_tickers)}
                  </div>
                </div>
              </div>

              <div className="strategy-form strategy-form-readonly">
                <label className="field">
                  <span>Min Entry</span>
                  <input type="number" value={viewModal.profile.min_entry_cents} readOnly />
                </label>
                <label className="field">
                  <span>Max Entry</span>
                  <input type="number" value={viewModal.profile.max_entry_cents} readOnly />
                </label>
                <label className="field">
                  <span>Max Open Orders</span>
                  <input type="number" value={viewModal.profile.max_open_orders} readOnly />
                </label>
                <label className="field">
                  <span>Daily Limit (¢)</span>
                  <input type="number" value={viewModal.profile.max_daily_spend_cents} readOnly />
                </label>
                <label className="field field-wide">
                  <span>Exit Strategy</span>
                  <input type="text" value={formatExitStrategy(viewModal.profile.exit_strategy)} readOnly />
                </label>
                {viewModal.profile.limit_sell_price_cents != null && (
                  <label className="field field-wide">
                    <span>Limit Sell Price</span>
                    <input type="text" value={`${viewModal.profile.limit_sell_price_cents}¢`} readOnly />
                  </label>
                )}
                <label className="field">
                  <span>Min Time to Close (min)</span>
                  <input type="text" value={viewModal.profile.min_time_to_close_secs != null ? String(viewModal.profile.min_time_to_close_secs / 60) : 'Any'} readOnly />
                </label>
                <label className="field">
                  <span>Max Time to Close (min)</span>
                  <input type="text" value={viewModal.profile.max_time_to_close_secs != null ? String(viewModal.profile.max_time_to_close_secs / 60) : 'Any'} readOnly />
                </label>
                <label className="strategy-toggle field-wide strategy-toggle-readonly">
                  <input type="checkbox" checked={viewModal.profile.proactive_mode} readOnly onChange={() => {}} />
                  <span>
                    <strong>Proactive Mode</strong>
                    <small>Place orders before price hits target</small>
                  </span>
                </label>
              </div>

              <div className="stat-label" style={{ marginTop: 22, marginBottom: 10 }}>Trade History</div>
              {viewModal.loading ? (
                <div className="strategy-trades-empty">Loading trades…</div>
              ) : viewModal.trades.length === 0 ? (
                <div className="strategy-trades-empty">No trades recorded for this strategy yet.</div>
              ) : (
                <div className="strategy-trades-table-wrap">
                  <table className="strategy-trades-table">
                    <thead>
                      <tr>
                        <th>Market</th>
                        <th>Orders</th>
                        <th>Status</th>
                        <th>Outcome</th>
                        <th>Avg Entry</th>
                        <th>P&amp;L</th>
                        <th>Placed</th>
                      </tr>
                    </thead>
                    <tbody>
                      {viewModal.trades.map(t => (
                        <tr key={t.market_ticker}>
                          <td className="trade-ticker">{t.market_ticker}</td>
                          <td>{t.order_count}</td>
                          <td><span className={`trade-status trade-status-${t.status}`}>{t.status}</span></td>
                          <td>
                            {t.outcome
                              ? <span className={`outcome-chip outcome-${t.outcome}`}>{t.outcome}</span>
                              : <span className="outcome-chip outcome-none">—</span>}
                          </td>
                          <td>{t.entry_price_cents != null ? `${t.entry_price_cents}¢` : '—'}</td>
                          <td className={t.net_profit_cents != null ? (t.net_profit_cents >= 0 ? 'pnl-pos' : 'pnl-neg') : ''}>
                            {t.net_profit_cents != null ? centsToUSD(t.net_profit_cents) : '—'}
                          </td>
                          <td>{fmtTime(t.placed_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <div className="strategy-view-footer">
                <div className="strategy-form-buttons">
                  <button
                    className="btn"
                    onClick={() => setRenameModal({ profileId: viewModal.profile.id, name: viewModal.profile.name })}
                  >
                    Rename
                  </button>
                  <button
                    className={`btn${viewModal.profile.is_active ? '' : ' btn-active'}`}
                    disabled={activating}
                    onClick={() => viewModal.profile.is_active
                      ? deactivateProfile(viewModal.profile.id)
                      : activateProfile(viewModal.profile.id)
                    }
                  >
                    {activating ? 'Updating…' : viewModal.profile.is_active ? 'Deactivate' : 'Activate'}
                  </button>
                  <button
                    className="btn"
                    onClick={() => {
                      setNewStrategyDraft({ ...profileToDraft(viewModal.profile), name: '' })
                      setViewModal(null)
                    }}
                  >
                    Copy as Template
                  </button>
                </div>
                <button className="btn" onClick={() => setViewModal(null)}>Close</button>
              </div>

            </section>
          </div>
        </div>
      )}

      {/* ── New strategy modal ── */}
      {newStrategyDraft && (
        <div className="strategy-modal-backdrop" onClick={() => setNewStrategyDraft(null)}>
          <div className="strategy-modal" onClick={e => e.stopPropagation()}>
            <section className="strategy-config-panel">
              <div className="strategy-section-head">
                <div>
                  <div className="stat-label">Create Strategy</div>
                  <h3>New Strategy</h3>
                </div>
                <p>Snapshot the current bot settings as a named strategy — parameters are locked after creation.</p>
              </div>

              <form onSubmit={saveStrategy} className="strategy-form">
                <label className="field field-wide">
                  <span>Strategy Name</span>
                  <input
                    type="text"
                    value={newStrategyDraft.name}
                    placeholder="Strategy snapshot name..."
                    onChange={e => updateDraft({ name: e.target.value })}
                  />
                </label>
                <label className="field">
                  <span>Min Entry</span>
                  <input type="number" value={newStrategyDraft.min_entry_cents}
                    onChange={e => updateDraft({ min_entry_cents: parseInt(e.target.value) || 0 })} />
                </label>
                <label className="field">
                  <span>Max Entry</span>
                  <input type="number" value={newStrategyDraft.max_entry_cents}
                    onChange={e => updateDraft({ max_entry_cents: parseInt(e.target.value) || 0 })} />
                </label>
                <label className="field">
                  <span>Max Open Orders</span>
                  <input type="number" value={newStrategyDraft.max_open_orders}
                    onChange={e => updateDraft({ max_open_orders: parseInt(e.target.value) || 0 })} />
                </label>
                <label className="field">
                  <span>Daily Limit</span>
                  <input type="number" value={newStrategyDraft.max_daily_spend_cents}
                    onChange={e => updateDraft({ max_daily_spend_cents: parseInt(e.target.value) || 0 })} />
                </label>
                <label className="field field-wide">
                  <span>Strategy Market</span>
                  <select
                    value={newStrategyDraft.btc_series_tickers[0] ?? SUPPORTED_STRATEGY_MARKETS[0].value}
                    onChange={e => updateDraft({ btc_series_tickers: [e.target.value] })}
                  >
                    {SUPPORTED_STRATEGY_MARKETS.map(option => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                  <small className="field-help">Strategies now bind to a supported market feed instead of free-typing a series ticker.</small>
                </label>
                <label className="field field-wide">
                  <span>Exit Strategy</span>
                  <select
                    value={newStrategyDraft.exit_strategy}
                    onChange={e => updateDraft({ exit_strategy: e.target.value as StrategyDraft['exit_strategy'] })}
                  >
                    <option value="hold_to_expiration">Hold to Expiration</option>
                    <option value="limit_sell">Limit Sell</option>
                  </select>
                  <small className="field-help">Hold to expiration keeps the historical behavior. Limit sell places a sell order after the buy fills.</small>
                </label>
                {newStrategyDraft.exit_strategy === 'limit_sell' && (
                  <label className="field field-wide">
                    <span>Limit Sell Price</span>
                    <input
                      type="number"
                      min={1}
                      max={99}
                      value={newStrategyDraft.limit_sell_price_cents ?? ''}
                      onChange={e => updateDraft({
                        limit_sell_price_cents: e.target.value === '' ? null : parseInt(e.target.value, 10) || null,
                      })}
                    />
                    <small className="field-help">When the entry fill lands, the bot places a same-market sell order at this price.</small>
                  </label>
                )}
                <label className="field">
                  <span>Min Time to Close (min)</span>
                  <input
                    type="number"
                    min={0}
                    step={0.5}
                    placeholder="Any"
                    value={newStrategyDraft.min_time_to_close_secs != null ? newStrategyDraft.min_time_to_close_secs / 60 : ''}
                    onChange={e => updateDraft({ min_time_to_close_secs: e.target.value ? Math.round(parseFloat(e.target.value) * 60) : null })}
                  />
                  <small className="field-help">Skip markets with less time remaining.</small>
                </label>
                <label className="field">
                  <span>Max Time to Close (min)</span>
                  <input
                    type="number"
                    min={0}
                    step={0.5}
                    placeholder="Any"
                    value={newStrategyDraft.max_time_to_close_secs != null ? newStrategyDraft.max_time_to_close_secs / 60 : ''}
                    onChange={e => updateDraft({ max_time_to_close_secs: e.target.value ? Math.round(parseFloat(e.target.value) * 60) : null })}
                  />
                  <small className="field-help">Skip markets with more time remaining. Set to 5 for time-decay plays.</small>
                </label>
                <label className="strategy-toggle field-wide">
                  <input
                    type="checkbox"
                    checked={newStrategyDraft.proactive_mode}
                    onChange={e => updateDraft({ proactive_mode: e.target.checked })}
                  />
                  <span>
                    <strong>Proactive Mode</strong>
                    <small>Place orders before price hits target</small>
                  </span>
                </label>
                <div className="strategy-form-actions field-wide">
                  <span>Parameters are locked after creation — create a new strategy to try different settings.</span>
                  <div className="strategy-form-buttons">
                    <button type="button" className="btn" onClick={() => setNewStrategyDraft(null)}>Cancel</button>
                    <button type="submit" className="btn btn-active" disabled={saving}>
                      {saving ? 'Saving…' : 'Create and Activate'}
                    </button>
                  </div>
                </div>
              </form>
            </section>
          </div>
        </div>
      )}

      {/* ── Rename modal ── */}
      {renameModal && (
        <div className="strategy-modal-backdrop" onClick={() => setRenameModal(null)}>
          <div className="strategy-modal strategy-modal-sm" onClick={e => e.stopPropagation()}>
            <section className="strategy-config-panel">
              <div className="strategy-section-head" style={{ marginBottom: 16 }}>
                <div className="stat-label">Rename Strategy</div>
              </div>
              <form onSubmit={saveRename} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <label className="field">
                  <span>Strategy Name</span>
                  <input
                    type="text"
                    autoFocus
                    value={renameModal.name}
                    onChange={e => setRenameModal(r => r ? { ...r, name: e.target.value } : r)}
                  />
                </label>
                <div className="strategy-form-actions" style={{ borderTop: '1px solid #242435', paddingTop: 14 }}>
                  <span />
                  <div className="strategy-form-buttons">
                    <button type="button" className="btn" onClick={() => setRenameModal(null)}>Cancel</button>
                    <button type="submit" className="btn btn-active" disabled={saving}>
                      {saving ? 'Saving…' : 'Save Name'}
                    </button>
                  </div>
                </div>
              </form>
            </section>
          </div>
        </div>
      )}
    </div>
  )
}
