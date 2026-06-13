import { useCallback, useEffect, useMemo, useState } from 'react'
import type { StrategyRule, Profile } from '../types'
import RuleBuilder, { defaultRule } from '../components/RuleBuilder'
import RuleBacktest, { type RuleMetrics } from '../components/RuleBacktest'
import { centsToUSD } from '../utils'

const SUPPORTED_MARKETS = [
  { value: 'KXBTC15M', label: 'Bitcoin 15 Minute' },
  { value: 'KXETH15M', label: 'Ethereum 15 Minute' },
  { value: 'KXSOL15M', label: 'Solana 15 Minute' },
] as const

const RULES_STORAGE_KEY = 'simulator.rules.v1'
const MARKET_LIMIT = 1000

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

interface Props {
  profiles: Profile[]
}

export default function Simulator({ profiles }: Props) {
  const [rules, setRules] = useState<StrategyRule[]>(loadStoredRules)
  const [series, setSeries] = useState<string>('KXBTC15M')
  // Per-rule metrics keyed by rule id, fed up from each RuleBacktest card.
  const [ruleMetrics, setRuleMetrics] = useState<Record<string, RuleMetrics | null>>({})

  // Persist rules on every change so they survive a page refresh.
  useEffect(() => {
    try {
      localStorage.setItem(RULES_STORAGE_KEY, JSON.stringify(rules))
    } catch {
      /* storage full/unavailable — non-fatal, just won't persist */
    }
  }, [rules])

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
    </div>
  )
}
