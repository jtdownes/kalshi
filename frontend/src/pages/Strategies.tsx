import { useState } from 'react'
import type { Settings, Profile } from '../App'
import { centsToUSD, fmtTime, fmtTickers } from '../App'

interface StrategyDraft {
  name: string
  min_entry_cents: number
  max_entry_cents: number
  proactive_mode: boolean
  max_open_orders: number
  max_daily_spend_cents: number
  scan_interval_seconds: number
  btc_series_tickers: string[]
  exit_strategy: 'hold_to_expiration' | 'limit_sell'
  limit_sell_price_cents: number | null
}

function formatExitStrategy(exitStrategy: StrategyDraft['exit_strategy'] | Profile['exit_strategy'] | Settings['exit_strategy']): string {
  return exitStrategy === 'limit_sell' ? 'Limit Sell' : 'Hold to Expiration'
}

function formatExitTarget(limitSellPriceCents: number | null | undefined): string {
  return limitSellPriceCents == null ? '—' : `${limitSellPriceCents}¢`
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
    scan_interval_seconds: settings.scan_interval_seconds,
    btc_series_tickers: settings.btc_series_tickers,
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

  const activeProfile = profiles.find(p => p.id === settings?.active_profile_id)
  const editingProfileId = strategyEditor?.mode === 'edit' ? strategyEditor.profileId ?? null : null
  const isEditingActive = editingProfileId != null && settings?.active_profile_id === editingProfileId

  const updateDraft = (patch: Partial<StrategyDraft>) =>
    setStrategyEditor(e => e ? { ...e, draft: { ...e.draft, ...patch } } : e)

  const openEditor = (profile: Profile) =>
    setStrategyEditor({ mode: 'edit', profileId: profile.id, draft: profileToDraft(profile) })

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

  return (
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
          <div className="strategy-metrics">
            <div><span>Max Bid</span><strong>{settings.max_entry_cents}¢</strong></div>
            <div><span>Daily Limit</span><strong>{centsToUSD(settings.max_daily_spend_cents)}</strong></div>
            <div><span>Max Orders</span><strong>{settings.max_open_orders}</strong></div>
            <div><span>Mode</span><strong>{settings.proactive_mode ? 'Proactive' : 'Reactive'}</strong></div>
            <div><span>Exit</span><strong>{formatExitStrategy(settings.exit_strategy)}</strong></div>
            <div><span>Exit Target</span><strong>{formatExitTarget(settings.limit_sell_price_cents)}</strong></div>
          </div>
        </section>
      )}

      <section className="strategies-grid" aria-label="Saved strategies">
        {profiles.length === 0 ? (
          <div className="strategy-empty">No strategies yet</div>
        ) : profiles.map(p => {
          const isActive = settings?.active_profile_id === p.id
          return (
            <article
              key={p.id}
              className={`strategy-card${isActive ? ' is-active' : ''}`}
              role="button"
              tabIndex={0}
              onClick={() => openEditor(p)}
              onKeyDown={e => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  openEditor(p)
                }
              }}
            >
              <div className="strategy-card-head">
                <div>
                  <div className="strategy-name">{p.name}</div>
                  <div className="strategy-created">Created {fmtTime(p.created_at)}</div>
                </div>
                {isActive && <span className="badge badge-live">ACTIVE</span>}
              </div>
              <div className="strategy-card-stats">
                <div><span>Max Bid</span><strong>{p.max_entry_cents}¢</strong></div>
                <div><span>Limit</span><strong>{centsToUSD(p.max_daily_spend_cents)}</strong></div>
                <div><span>Orders</span><strong>{p.max_open_orders}</strong></div>
                <div><span>Runs</span><strong>{(p.order_count ?? 0).toLocaleString()}</strong></div>
                <div><span>Exit</span><strong>{formatExitStrategy(p.exit_strategy)}</strong></div>
                <div><span>Exit Target</span><strong>{formatExitTarget(p.limit_sell_price_cents)}</strong></div>
              </div>
              <div className="strategy-tickers">{fmtTickers(p.btc_series_tickers)}</div>
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
            {strategyEditor.mode === 'edit' && strategyEditor.profileId != null && (
              <div className="field-wide">
                <button
                  type="button"
                  className={`strategy-status-toggle${isEditingActive ? ' is-active' : ''}`}
                  aria-pressed={isEditingActive}
                  disabled={activating}
                  onClick={() => {
                    if (!isEditingActive) activateProfile(strategyEditor.profileId!)
                  }}
                >
                  <span className="strategy-status-copy">
                    <strong>{isEditingActive ? 'Active Strategy' : 'Inactive Strategy'}</strong>
                    <small>
                      {isEditingActive
                        ? 'This strategy is currently live.'
                        : activating
                          ? 'Activating strategy...'
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
            <label className="field">
              <span>Scan Interval</span>
              <input type="number" value={strategyEditor.draft.scan_interval_seconds}
                onChange={e => updateDraft({ scan_interval_seconds: parseInt(e.target.value) || 0 })} />
            </label>
            <label className="field field-wide">
              <span>BTC Series Tickers</span>
              <input
                type="text"
                value={strategyEditor.draft.btc_series_tickers.join(', ')}
                onChange={e => updateDraft({ btc_series_tickers: e.target.value.split(',').map(s => s.trim()).filter(Boolean) })}
              />
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
