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

  const updateDraft = (patch: Partial<StrategyDraft>) =>
    setStrategyEditor(e => e ? { ...e, draft: { ...e.draft, ...patch } } : e)

  const saveStrategy = async (ev: React.FormEvent) => {
    ev.preventDefault()
    if (!strategyEditor) return
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
      setStrategyEditor(null)
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
                <div><span>Max Bid</span><strong>{p.max_entry_cents}¢</strong></div>
                <div><span>Limit</span><strong>{centsToUSD(p.max_daily_spend_cents)}</strong></div>
                <div><span>Orders</span><strong>{p.max_open_orders}</strong></div>
                <div><span>Runs</span><strong>{(p.order_count ?? 0).toLocaleString()}</strong></div>
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
