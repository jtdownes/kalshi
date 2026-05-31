import { useState } from 'react'
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
  }
}

interface Props {
  settings: Settings | null
  profiles: Profile[]
  refresh: () => Promise<void>
}

export default function Strategies({ settings, profiles, refresh }: Props) {
  const [strategyEditor, setStrategyEditor] = useState<{ mode: 'new' | 'edit'; profileId?: number; draft: StrategyDraft } | null>(null)
  const [saving,      setSaving]      = useState(false)
  const [activating,  setActivating]  = useState(false)
  const [selectedProfile, setSelectedProfile] = useState<Profile | null>(null)
  const [profileTrades,   setProfileTrades]   = useState<Trade[]>([])
  const [loadingTrades,   setLoadingTrades]   = useState(false)

  const activeProfile = profiles.find(p => p.id === settings?.active_profile_id)
  const editingProfileId = strategyEditor?.mode === 'edit' ? strategyEditor.profileId ?? null : null
  const isEditingActive = editingProfileId != null && (profiles.find(p => p.id === editingProfileId)?.is_active ?? false)

  const updateDraft = (patch: Partial<StrategyDraft>) =>
    setStrategyEditor(e => e ? { ...e, draft: { ...e.draft, ...patch } } : e)

  const openEditor = (profile: Profile) => {
    setSelectedProfile(null)
    setStrategyEditor({ mode: 'edit', profileId: profile.id, draft: profileToDraft(profile) })
  }

  const openDetail = async (profile: Profile) => {
    setStrategyEditor(null)
    setSelectedProfile(profile)
    setLoadingTrades(true)
    setProfileTrades([])
    try {
      const resp = await fetch(`/api/trades?profile_id=${profile.id}&limit=200`)
      if (resp.ok) setProfileTrades(await resp.json())
    } finally {
      setLoadingTrades(false)
    }
  }

  const saveStrategy = async (ev: React.FormEvent) => {
    ev.preventDefault()
    if (!strategyEditor) return
    if (strategyEditor.draft.exit_strategy === 'limit_sell' && strategyEditor.draft.limit_sell_price_cents == null) {
      alert('Set a limit sell price before saving a limit sell strategy')
      return
    }
    setSaving(true)
    try {
      const resp = await fetch(
        strategyEditor.mode === 'edit' ? `/api/profiles/${strategyEditor.profileId}` : '/api/profiles',
        {
          method: strategyEditor.mode === 'edit' ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(strategyEditor.draft),
        }
      )
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
                onClick={() => setStrategyEditor({ mode: 'new', draft: settingsToDraft(settings) })}
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
              className={`strategy-card${isActive ? ' is-active' : ''}${selectedProfile?.id === p.id ? ' is-selected' : ''}`}
              role="button"
              tabIndex={0}
              onClick={() => openDetail(p)}
              onKeyDown={e => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  openDetail(p)
                }
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
              </div>

              <div className="strategy-card-foot">
                <span className="strategy-chip">{formatExitStrategy(p.exit_strategy)}</span>
                {p.limit_sell_price_cents != null && <span className="strategy-chip">Target {formatExitTarget(p.limit_sell_price_cents)}</span>}
                <span className="strategy-chip strategy-chip-dim">View trades</span>
              </div>
            </article>
          )
        })}
      </section>

      {selectedProfile && !strategyEditor && (
        <section className="strategy-detail-panel">
          <div className="strategy-section-head">
            <div>
              <div className="stat-label">Strategy Trades</div>
              <h3>{selectedProfile.name}</h3>
            </div>
            <div className="strategy-detail-actions">
              <button className="btn btn-active" onClick={() => openEditor(selectedProfile)}>Edit Strategy</button>
              <button className="btn" onClick={() => setSelectedProfile(null)}>Close</button>
            </div>
          </div>
          {loadingTrades ? (
            <div className="strategy-trades-empty">Loading trades…</div>
          ) : profileTrades.length === 0 ? (
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
                  {profileTrades.map(t => (
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
        </section>
      )}

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
            {strategyEditor.mode === 'edit' && strategyEditor.profileId != null && (
              <div className="field-wide">
                <button
                  type="button"
                  className={`strategy-status-toggle${isEditingActive ? ' is-active' : ''}`}
                  aria-pressed={isEditingActive}
                  disabled={activating}
                  onClick={() => {
                    if (isEditingActive) {
                      deactivateProfile(strategyEditor.profileId!)
                    } else {
                      activateProfile(strategyEditor.profileId!)
                    }
                  }}
                >
                  <span className="strategy-status-copy">
                    <strong>{isEditingActive ? 'Active Strategy' : 'Inactive Strategy'}</strong>
                    <small>
                      {isEditingActive
                        ? 'Running live. Click to deactivate.'
                        : activating
                          ? 'Updating...'
                          : 'Click to make this strategy live.'}
                    </small>
                  </span>
                  <span className="strategy-status-switch" aria-hidden="true">
                    <span className="strategy-status-knob" />
                  </span>
                </button>
              </div>
            )}
            <label className="field field-wide">
              <span>Strategy Name</span>
              <input
                type="text"
                value={strategyEditor.draft.name}
                placeholder="Strategy snapshot name..."
                onChange={e => updateDraft({ name: e.target.value })}
              />
            </label>
            <label className="field">
              <span>Min Entry</span>
              <input type="number" value={strategyEditor.draft.min_entry_cents}
                onChange={e => updateDraft({ min_entry_cents: parseInt(e.target.value) || 0 })} />
            </label>
            <label className="field">
              <span>Max Entry</span>
              <input type="number" value={strategyEditor.draft.max_entry_cents}
                onChange={e => updateDraft({ max_entry_cents: parseInt(e.target.value) || 0 })} />
            </label>
            <label className="field">
              <span>Max Open Orders</span>
              <input type="number" value={strategyEditor.draft.max_open_orders}
                onChange={e => updateDraft({ max_open_orders: parseInt(e.target.value) || 0 })} />
            </label>
            <label className="field">
              <span>Daily Limit</span>
              <input type="number" value={strategyEditor.draft.max_daily_spend_cents}
                onChange={e => updateDraft({ max_daily_spend_cents: parseInt(e.target.value) || 0 })} />
            </label>
            <label className="field field-wide">
              <span>Strategy Market</span>
              <select
                value={strategyEditor.draft.btc_series_tickers[0] ?? SUPPORTED_STRATEGY_MARKETS[0].value}
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
                value={strategyEditor.draft.exit_strategy}
                onChange={e => updateDraft({ exit_strategy: e.target.value as StrategyDraft['exit_strategy'] })}
              >
                <option value="hold_to_expiration">Hold to Expiration</option>
                <option value="limit_sell">Limit Sell</option>
              </select>
              <small className="field-help">Hold to expiration keeps the historical behavior. Limit sell places a sell order after the buy fills.</small>
            </label>
            {strategyEditor.draft.exit_strategy === 'limit_sell' && (
              <label className="field field-wide">
                <span>Limit Sell Price</span>
                <input
                  type="number"
                  min={1}
                  max={99}
                  value={strategyEditor.draft.limit_sell_price_cents ?? ''}
                  onChange={e => updateDraft({
                    limit_sell_price_cents: e.target.value === '' ? null : parseInt(e.target.value, 10) || null,
                  })}
                />
                <small className="field-help">When the entry fill lands, the bot places a same-market sell order at this price.</small>
              </label>
            )}
            <label className="strategy-toggle field-wide">
              <input
                type="checkbox"
                checked={strategyEditor.draft.proactive_mode}
                onChange={e => updateDraft({ proactive_mode: e.target.checked })}
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
  )
}
