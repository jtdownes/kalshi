import { useState, useEffect } from 'react'
import type { Settings, Profile, StrategyRule } from '../types'
import { centsToUSD, fmtTime, fmtTickers, STRATEGY_MARKETS } from '../utils'
import RuleBuilder, { defaultRule, ruleSummary } from '../components/RuleBuilder'
import StrategyBacktest from '../components/StrategyBacktest'

const SUPPORTED_STRATEGY_MARKETS = STRATEGY_MARKETS

interface StrategyDraft {
  name: string
  max_open_orders: number
  max_daily_spend_cents: number
  btc_series_tickers: string[]
  rules: StrategyRule[]
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

function normalizeStrategyMarkets(raw: string[]): string[] {
  const selected = raw.find(Boolean)
  return selected ? [selected] : [SUPPORTED_STRATEGY_MARKETS[0].value]
}

function profileToDraft(profile: Profile): StrategyDraft {
  return {
    name: profile.name,
    max_open_orders: profile.max_open_orders,
    max_daily_spend_cents: profile.max_daily_spend_cents,
    btc_series_tickers: normalizeStrategyMarkets(profile.btc_series_tickers.split(',').map(t => t.trim()).filter(Boolean)),
    rules: profile.rules ?? [],
  }
}

function settingsToDraft(settings: Settings, name = ''): StrategyDraft {
  const rules = settings.rules && settings.rules.length ? settings.rules : [defaultRule()]
  return {
    name,
    max_open_orders: settings.max_open_orders,
    max_daily_spend_cents: settings.max_daily_spend_cents,
    btc_series_tickers: normalizeStrategyMarkets(settings.btc_series_tickers),
    rules,
  }
}

function validateRules(rules: StrategyRule[]): string | null {
  if (rules.length === 0) return 'Add at least one rule.'
  for (const r of rules) {
    if (r.conditions.length === 0) continue   // empty conditions = "always" (allowed)
    for (const c of r.conditions) {
      if (c.value == null) return 'Every condition needs a value.'
      if (c.op === 'between' && c.value2 == null) return 'Between conditions need two values.'
    }
    if (r.action.entry.type === 'limit' && r.action.entry.price_cents == null)
      return 'Limit-entry rules need a price.'
    if (r.action.entry.type === 'ask_minus' && r.action.entry.offset_cents == null)
      return '"¢ below ask" entries need an offset.'
    if (r.action.entry.type === 'ask_minus_pct' && r.action.entry.offset_pct == null)
      return '"% below ask" entries need a percentage.'
    if (r.action.exit.type === 'limit_sell' && r.action.exit.price_cents == null)
      return 'Limit-sell exits need a price.'
    if (r.action.exit.type === 'scale_out') {
      const legs = r.action.exit.legs ?? []
      if (legs.length === 0) return 'Scale-out exits need at least one rung.'
      if (legs.some(l => l.qty == null || l.price_cents == null))
        return 'Every scale-out rung needs a quantity and a price.'
      const total = legs.reduce((s, l) => s + (l.qty ?? 0), 0)
      if (total > r.action.quantity)
        return `Scale-out rungs sell ${total} contracts but the rule only buys ${r.action.quantity}.`
    }
    if (r.action.exit.stop_pct != null && (r.action.exit.stop_pct <= 0 || r.action.exit.stop_pct >= 100))
      return 'A %-stop must be between 0 and 100.'
  }
  return null
}

interface Props {
  settings: Settings | null
  profiles: Profile[]
  refresh: () => Promise<void>
}

export default function Strategies({ settings, profiles, refresh }: Props) {
  const [viewModal, setViewModal] = useState<{
    profile: Profile
    tab: 'settings' | 'trades'
    trades: Trade[]
    loadingTrades: boolean
  } | null>(null)
  const [newStrategyDraft, setNewStrategyDraft] = useState<StrategyDraft | null>(null)
  const [editingProfileId, setEditingProfileId] = useState<number | null>(null)
  // Limited edit: strategy already has orders, so only name / rule names /
  // quantities may change — structure and caps stay locked.
  const [limitedEdit,      setLimitedEdit]      = useState(false)
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

  const openViewModal = (profile: Profile) => {
    setNewStrategyDraft(null)
    setViewModal({ profile, tab: 'settings', trades: [], loadingTrades: false })
  }

  const switchToTrades = async () => {
    setViewModal(v => v ? { ...v, tab: 'trades', loadingTrades: true } : v)
    try {
      const resp = await fetch(`/api/trades?profile_id=${viewModal!.profile.id}&limit=200`)
      const trades = resp.ok ? await resp.json() : []
      setViewModal(v => v ? { ...v, trades, loadingTrades: false } : v)
    } catch {
      setViewModal(v => v ? { ...v, loadingTrades: false } : v)
    }
  }

  const saveStrategy = async (ev: React.FormEvent) => {
    ev.preventDefault()
    if (!newStrategyDraft) return
    const err = validateRules(newStrategyDraft.rules)
    if (err) { alert(err); return }
    setSaving(true)
    try {
      let resp: Response
      if (editingProfileId) {
        resp = await fetch(`/api/profiles/${editingProfileId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(newStrategyDraft),
        })
      } else {
        resp = await fetch('/api/profiles', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(newStrategyDraft),
        })
      }
      if (!resp.ok) throw new Error('Failed to save strategy')
      setNewStrategyDraft(null)
      setEditingProfileId(null)
      setLimitedEdit(false)
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
    setSaving(true)
    try {
      const resp = await fetch(`/api/profiles/${renameModal.profileId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: renameModal.name }),
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

  const deleteProfile = async (profileId: number) => {
    if (!confirm('Delete this strategy? This cannot be undone.')) return
    try {
      const resp = await fetch(`/api/profiles/${profileId}`, { method: 'DELETE' })
      if (resp.ok) {
        if (viewModal?.profile.id === profileId) setViewModal(null)
        await refresh()
      } else if (resp.status === 409) {
        const js = await resp.json().catch(() => ({}))
        alert(js.error || 'Strategy has historical runs and cannot be deleted')
      } else if (resp.status === 404) {
        alert('Strategy not found')
        await refresh()
      } else {
        const js = await resp.json().catch(() => ({}))
        throw new Error(js.error || 'Failed to delete strategy')
      }
    } catch (err: any) {
      alert(err.message || String(err))
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

  const activeRuleCount = (settings?.rules?.length) ?? 0

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
                onClick={() => { setEditingProfileId(null); setLimitedEdit(false); setNewStrategyDraft(settingsToDraft(settings)) }}
              >
                New Strategy
              </button>
            </div>
          </div>
          <div className="strategy-metrics-wrap">
            <div className="strategy-metrics strategy-metrics-compact">
              <div><span>Rules</span><strong>{activeRuleCount}</strong></div>
            </div>
          </div>
        </section>
      )}

      <section className="strategies-grid" aria-label="Saved strategies">
        {profiles.length === 0 ? (
          <div className="strategy-empty">No strategies yet</div>
        ) : profiles.map(p => {
          const isActive = p.is_active
          const ruleCount = p.rules?.length ?? 0
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
                  {(p.order_count ?? 0) === 0 && (
                    <button
                      className="btn"
                      onClick={e => { e.stopPropagation(); deleteProfile(p.id) }}
                      style={{ marginLeft: 8 }}
                      aria-label={`Delete strategy ${p.name}`}
                    >
                      Delete
                    </button>
                  )}
                </div>
              </div>

              <div className="strategy-ticket-band">
                <div className="strategy-ticket-metric">
                  <span>Rules</span>
                  <strong>{ruleCount}</strong>
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
                {(p.rules ?? []).slice(0, 2).map(r => (
                  <span key={r.id} className="strategy-chip strategy-chip-rule" title={ruleSummary(r)}>
                    {r.name || ruleSummary(r)}
                  </span>
                ))}
                {ruleCount > 2 && <span className="strategy-chip strategy-chip-dim">+{ruleCount - 2} more</span>}
                {ruleCount === 0 && <span className="strategy-chip strategy-chip-dim">No rules</span>}
              </div>
            </article>
          )
        })}
      </section>

      {/* ── Strategy view modal ── */}
      {viewModal && (
        <div className="strategy-modal-backdrop" onClick={() => setViewModal(null)}>
          <div className={`strategy-modal strategy-modal-view${viewModal.tab === 'trades' ? ' strategy-modal-view-trades' : ''}`} onClick={e => e.stopPropagation()}>
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

              {viewModal.tab === 'settings' ? (
                <>
                  <RuleBuilder rules={viewModal.profile.rules ?? []} onChange={() => {}} readOnly />
                  <StrategyBacktest
                    rules={viewModal.profile.rules ?? []}
                    series={normalizeStrategyMarkets(viewModal.profile.btc_series_tickers.split(',').map(t => t.trim()).filter(Boolean))[0]}
                  />
                </>
              ) : (
                <div className="strategy-trades-table-wrap" style={{ marginTop: 4 }}>
                  {viewModal.loadingTrades ? (
                    <div className="strategy-trades-empty">Loading trades…</div>
                  ) : viewModal.trades.length === 0 ? (
                    <div className="strategy-trades-empty">No trades recorded for this strategy yet.</div>
                  ) : (
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
                  )}
                </div>
              )}

              <div className="strategy-view-footer">
                <div className="strategy-form-buttons">
                  {viewModal.tab === 'settings' ? (
                    <>
                      <button className="btn" onClick={() => setRenameModal({ profileId: viewModal.profile.id, name: viewModal.profile.name })}>Rename</button>
                      <button
                        className="btn"
                        onClick={() => {
                          setNewStrategyDraft(profileToDraft(viewModal.profile))
                          setEditingProfileId(viewModal.profile.id)
                          // Strategies that already traded can only have names /
                          // quantities tweaked; zero-run ones are fully editable.
                          setLimitedEdit((viewModal.profile.order_count ?? 0) > 0)
                          setViewModal(null)
                        }}
                      >
                        Edit
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
                      <button className="btn" onClick={() => { setNewStrategyDraft({ ...profileToDraft(viewModal.profile), name: '' }); setEditingProfileId(null); setLimitedEdit(false); setViewModal(null) }}>Copy as Template</button>
                      <button className="btn" onClick={switchToTrades}>View Trades</button>
                    </>
                  ) : (
                    <button className="btn" onClick={() => setViewModal(v => v ? { ...v, tab: 'settings' } : v)}>← Back to Settings</button>
                  )}
                </div>
                <button className="btn" onClick={() => setViewModal(null)}>Close</button>
              </div>

            </section>
          </div>
        </div>
      )}

      {/* ── New strategy modal ── */}
      {/* Backdrop click is intentionally a no-op here: the builder holds unsaved
          work, so it only closes via Cancel or Escape (handled above). */}
      {newStrategyDraft && (
        <div className="strategy-modal-backdrop">
          <div className="strategy-modal strategy-modal-builder" onClick={e => e.stopPropagation()}>
            <section className="strategy-config-panel">
              <div className="strategy-section-head">
                <div>
                          <div className="stat-label">{editingProfileId ? 'Edit Strategy' : 'Create Strategy'}</div>
                          <h3>{editingProfileId ? 'Edit Strategy' : 'New Strategy'}</h3>
                </div>
                <p>{limitedEdit
                  ? 'This strategy has already placed orders, so its structure is locked to keep its history meaningful. You can still rename it, rename rules, and adjust order quantities. Copy as a template to change rules.'
                  : 'Build conditional rules — every matching rule fires, so you can ladder multiple entries. Parameters are locked after creation; copy as a template to iterate.'}</p>
              </div>

              <form onSubmit={saveStrategy} className="strategy-builder-form">
                <div className="strategy-builder-meta">
                  <label className="field">
                    <span>Strategy Name</span>
                    <input
                      type="text"
                      value={newStrategyDraft.name}
                      placeholder="Strategy name..."
                      onChange={e => updateDraft({ name: e.target.value })}
                    />
                  </label>
                  <label className="field">
                    <span>Market</span>
                    <select
                      value={newStrategyDraft.btc_series_tickers[0] ?? SUPPORTED_STRATEGY_MARKETS[0].value}
                      disabled={limitedEdit}
                      onChange={e => updateDraft({ btc_series_tickers: [e.target.value] })}
                    >
                      {SUPPORTED_STRATEGY_MARKETS.map(option => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </label>
                </div>

                <div className="strategy-builder-rules-head">
                  <div className="stat-label">Rules</div>
                  <small className="field-help">
                    {limitedEdit
                      ? 'Conditions and entry/exit are locked. Only rule names and quantities can change.'
                      : 'Safety caps above bound total exposure regardless of how many rules fire.'}
                  </small>
                </div>

                <RuleBuilder
                  rules={newStrategyDraft.rules}
                  onChange={rules => updateDraft({ rules })}
                  lockStructure={limitedEdit}
                />

                <StrategyBacktest
                  rules={newStrategyDraft.rules}
                  series={newStrategyDraft.btc_series_tickers[0] ?? SUPPORTED_STRATEGY_MARKETS[0].value}
                />

                <div className="strategy-form-actions field-wide">
                  <span>{limitedEdit
                    ? 'Only name, rule names, and quantities are editable here.'
                    : 'Parameters are locked after creation — copy as a template to try different rules.'}</span>
                  <div className="strategy-form-buttons">
                    <button type="button" className="btn" onClick={() => { setNewStrategyDraft(null); setEditingProfileId(null); setLimitedEdit(false) }}>Cancel</button>
                    <button type="submit" className="btn btn-active" disabled={saving}>
                      {saving ? 'Saving…' : editingProfileId ? 'Save Changes' : 'Create and Activate'}
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
