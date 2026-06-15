import { useCallback, useEffect, useMemo, useState } from 'react'
import type { StrategyRule, Profile, Settings } from '../types'
import RuleBuilder, { defaultRule } from '../components/RuleBuilder'
import RuleBacktest, { type RuleMetrics } from '../components/RuleBacktest'
import { centsToUSD } from '../utils'

const SUPPORTED_MARKETS = [
  { value: 'KXBTC15M', label: 'Bitcoin 15 Minute' },
  { value: 'KXETH15M', label: 'Ethereum 15 Minute' },
  { value: 'KXSOL15M', label: 'Solana 15 Minute' },
] as const

const RULES_STORAGE_KEY = 'simulator.rules.v1'
const SERIES_STORAGE_KEY = 'simulator.series.v1'
const MARKET_LIMIT = 1000

// Restore the last-selected market so a refresh doesn't reset it to BTC.
function loadStoredSeries(): string {
  try {
    const raw = localStorage.getItem(SERIES_STORAGE_KEY)
    if (raw && SUPPORTED_MARKETS.some(m => m.value === raw)) return raw
  } catch {
    /* corrupt/unavailable storage — fall through to the default */
  }
  return 'KXBTC15M'
}

// Restore the rules the user was last editing so a refresh doesn't wipe them.
function loadStoredRules(): StrategyRule[] {
  try {
    const raw = localStorage.getItem(RULES_STORAGE_KEY)
    if (!raw) return [defaultRule()]
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed) && parsed.length > 0) return parsed
  } catch {
    /* corrupt/unavailable storage — fall through to a fresh rule */
  }
  return [defaultRule()]
}

function pnlColor(c: number | null | undefined): string | undefined {
  if (c == null) return undefined
  return c > 0 ? '#00d4a0' : c < 0 ? '#ff4444' : '#94a3b8'
}

// Roll the per-rule metrics into one total, recomputing the rate/ratio fields
// from raw counts. Done client-side so the total updates the instant any rule's
// result lands — no extra round-trip and no resimulating the unchanged rules.
function combineMetrics(parts: RuleMetrics[]): RuleMetrics | null {
  const live = parts.filter(m => m && m.trade_count > 0)
  if (!live.length) return null
  let trades = 0, wins = 0, losses = 0, sold = 0, expired = 0
  let pnl = 0, cost = 0, fillSum = 0
  for (const m of live) {
    trades += m.trade_count
    wins += m.win_count
    losses += m.loss_count
    sold += m.sold_count
    expired += m.expired_count
    pnl += m.total_pnl_cents
    cost += m.total_cost_cents
    fillSum += (m.avg_fill_price ?? 0) * m.trade_count
  }
  return {
    trade_count: trades,
    win_count: wins,
    loss_count: losses,
    win_rate: trades ? Math.round((wins / trades) * 1000) / 10 : null,
    total_pnl_cents: Math.round(pnl * 10) / 10,
    total_cost_cents: Math.round(cost * 10) / 10,
    roi_pct: cost ? Math.round((pnl / cost) * 1000) / 10 : null,
    avg_pnl_cents: trades ? Math.round((pnl / trades) * 10) / 10 : null,
    avg_fill_price: trades ? Math.round((fillSum / trades) * 10) / 10 : null,
    sold_count: sold,
    expired_count: expired,
  }
}

function Stat({ label, value, color, sub }: { label: string; value: string; color?: string; sub?: string }) {
  return (
    <div style={{
      background: 'rgba(255,255,255,0.03)',
      border: '1px solid rgba(255,255,255,0.07)',
      borderRadius: 8,
      padding: '8px 12px',
      minWidth: 96,
    }}>
      <div style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 800, color: color ?? '#f1f5f9', lineHeight: 1.3 }}>{value}</div>
      {sub && <div style={{ fontSize: 10, color: '#64748b' }}>{sub}</div>}
    </div>
  )
}

// Mirror of the rule validation used by the Strategies builder so a simulation
// can't be saved into a strategy the backend would reject.
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
  profiles: Profile[]
  settings: Settings | null
  refresh: () => Promise<void>
}

export default function Simulator({ profiles, settings, refresh }: Props) {
  const [rules, setRules] = useState<StrategyRule[]>(loadStoredRules)
  const [series, setSeries] = useState<string>(loadStoredSeries)
  // Per-rule metrics keyed by rule id, fed up from each RuleBacktest card.
  const [ruleMetrics, setRuleMetrics] = useState<Record<string, RuleMetrics | null>>({})
  // Save-as-strategy modal state
  const [saveModal, setSaveModal] = useState<{ name: string } | null>(null)
  const [saving, setSaving] = useState(false)

  // Persist rules on every change so they survive a page refresh.
  useEffect(() => {
    try {
      localStorage.setItem(RULES_STORAGE_KEY, JSON.stringify(rules))
    } catch {
      /* storage full/unavailable — non-fatal, just won't persist */
    }
  }, [rules])

  // Persist the selected market too, so a refresh keeps it.
  useEffect(() => {
    try {
      localStorage.setItem(SERIES_STORAGE_KEY, series)
    } catch {
      /* storage full/unavailable — non-fatal */
    }
  }, [series])

  // Stable so RuleBacktest's reporting effect doesn't refire on every render.
  const handleRuleResult = useCallback((ruleId: string, metrics: RuleMetrics | null) => {
    setRuleMetrics(prev => {
      if (prev[ruleId] === metrics) return prev
      return { ...prev, [ruleId]: metrics }
    })
  }, [])

  // Total only reflects rules that still exist (deleted ids are ignored even if
  // a stale entry lingers in the map).
  const total = useMemo(() => {
    const parts = rules
      .map(r => ruleMetrics[r.id])
      .filter((m): m is RuleMetrics => !!m)
    return combineMetrics(parts)
  }, [rules, ruleMetrics])

  const handleLoadFrom = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const profileId = Number(e.target.value)
    if (!profileId) return
    const profile = profiles.find(p => p.id === profileId)
    if (profile?.rules?.length) {
      setRules(profile.rules)
    }
    // Reset the select back to placeholder
    e.target.value = ''
  }

  const saveAsStrategy = async (ev: React.FormEvent) => {
    ev.preventDefault()
    if (!saveModal || !settings) return
    const name = saveModal.name.trim()
    if (!name) { alert('Give the strategy a name.'); return }
    const err = validateRules(rules)
    if (err) { alert(err); return }
    setSaving(true)
    try {
      const resp = await fetch('/api/profiles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          // Inherit exposure caps from current settings; the simulator doesn't
          // tune them, and they can be adjusted later on the Strategies page.
          max_open_orders: settings.max_open_orders,
          max_daily_spend_cents: settings.max_daily_spend_cents,
          btc_series_tickers: [series],
          rules,
          activate: false,
        }),
      })
      if (!resp.ok) throw new Error('Failed to save strategy')
      setSaveModal(null)
      await refresh()
    } catch (err: any) {
      alert(err.message || String(err))
    } finally {
      setSaving(false)
    }
  }

  const renderRuleFooter = useCallback(
    (rule: StrategyRule) => (
      <RuleBacktest
        rule={rule}
        series={series}
        marketLimit={MARKET_LIMIT}
        onResult={handleRuleResult}
      />
    ),
    [series, handleRuleResult],
  )

  return (
    <div className="strategies-view">
      <section className="strategy-active-panel">
        <div className="strategy-active-main">
          <div className="stat-label">Rule Simulator</div>
          <h2 style={{ margin: '2px 0 6px' }}>Build and backtest rules without saving</h2>
          <div style={{ fontSize: 12, color: '#64748b', marginBottom: 8 }}>
            Each rule backtests on its own — edit one and only that rule re-runs. The total below sums them live.
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          {profiles.length > 0 && (
            <select
              className="select"
              defaultValue=""
              onChange={handleLoadFrom}
              style={{ minWidth: 180 }}
            >
              <option value="" disabled>Load from strategy…</option>
              {profiles.map(p => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          )}
          <select
            className="select"
            value={series}
            onChange={e => setSeries(e.target.value)}
          >
            {SUPPORTED_MARKETS.map(m => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
          <button
            className="btn"
            onClick={() => setRules([defaultRule()])}
          >
            Reset Rules
          </button>
          {settings && (
            <button
              className="btn btn-active"
              onClick={() => setSaveModal({ name: '' })}
            >
              Save as Strategy
            </button>
          )}
        </div>
      </section>

      <RuleBuilder rules={rules} onChange={setRules} renderRuleFooter={renderRuleFooter} />

      <section style={{ marginTop: 16 }}>
        <div className="stat-label" style={{ marginBottom: 8 }}>
          Combined Total <span style={{ color: '#64748b', fontWeight: 500 }}>— last {MARKET_LIMIT} markets</span>
        </div>
        {total ? (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            <Stat
              label="Total P&L"
              value={`${total.total_pnl_cents >= 0 ? '+' : ''}${centsToUSD(total.total_pnl_cents)}`}
              color={pnlColor(total.total_pnl_cents)}
            />
            <Stat
              label="ROI"
              value={total.roi_pct != null ? `${total.roi_pct > 0 ? '+' : ''}${total.roi_pct}%` : '—'}
              color={pnlColor(total.roi_pct)}
            />
            <Stat
              label="Win Rate"
              value={total.win_rate != null ? `${total.win_rate}%` : '—'}
              color={total.win_rate != null && total.win_rate >= 50 ? '#00d4a0' : '#fbbf24'}
              sub={`${total.win_count}W / ${total.loss_count}L`}
            />
            <Stat label="Trades" value={total.trade_count.toLocaleString()} sub={total.sold_count ? `${total.sold_count.toLocaleString()} sold` : undefined} />
            <Stat
              label="Avg P&L"
              value={total.avg_pnl_cents != null ? `${total.avg_pnl_cents > 0 ? '+' : ''}${centsToUSD(total.avg_pnl_cents)}` : '—'}
              color={pnlColor(total.avg_pnl_cents)}
            />
            <Stat label="Avg Fill" value={total.avg_fill_price != null ? `${total.avg_fill_price}¢` : '—'} />
            <Stat label="Total Cost" value={centsToUSD(total.total_cost_cents)} />
          </div>
        ) : (
          <div style={{ fontSize: 12, color: '#475569', padding: '8px 0' }}>
            No fills across any rule yet — add an entry price to a rule to start simulating.
          </div>
        )}
      </section>

      {saveModal && (
        <div className="strategy-modal-backdrop" onClick={() => !saving && setSaveModal(null)}>
          <div className="strategy-modal strategy-modal-sm" onClick={e => e.stopPropagation()}>
            <section className="strategy-config-panel">
              <div className="strategy-section-head" style={{ marginBottom: 16 }}>
                <div className="stat-label">Save as Strategy</div>
                <p style={{ color: '#64748b', fontSize: 12, margin: '4px 0 0' }}>
                  Saves these {rules.length} rule{rules.length === 1 ? '' : 's'} on {series} as a new,
                  inactive strategy. Activate it later from the Strategies page.
                </p>
              </div>
              <form onSubmit={saveAsStrategy} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <label className="field">
                  <span>Strategy Name</span>
                  <input
                    type="text"
                    autoFocus
                    value={saveModal.name}
                    placeholder="Strategy name..."
                    onChange={e => setSaveModal(s => s ? { ...s, name: e.target.value } : s)}
                  />
                </label>
                <div className="strategy-form-actions" style={{ borderTop: '1px solid #242435', paddingTop: 14 }}>
                  <span />
                  <div className="strategy-form-buttons">
                    <button type="button" className="btn" onClick={() => setSaveModal(null)} disabled={saving}>Cancel</button>
                    <button type="submit" className="btn btn-active" disabled={saving}>
                      {saving ? 'Saving…' : 'Save Strategy'}
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
