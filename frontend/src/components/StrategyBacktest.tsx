import { useState, useEffect, useRef } from 'react'
import type { StrategyRule, Snapshot } from '../types'
import { centsToUSD } from '../utils'
import type { TtcWindow } from '../utils'
import SimulatorExecutions, { type SimTrade } from './SimulatorExecutions'

interface Metrics {
  trade_count: number
  win_count: number
  loss_count: number
  win_rate: number | null
  total_pnl_cents: number
  total_cost_cents: number
  roi_pct: number | null
  avg_pnl_cents: number | null
  avg_fill_price: number | null
  sold_count: number
  expired_count: number
  signaled_markets?: number
  no_fill_count?: number
  fill_rate?: number | null
}

interface RuleResult extends Metrics {
  rule_id: string
  rule_name: string
}

interface Result {
  summary: Metrics
  rules: RuleResult[]
  trades: SimTrade[]
}

function pnlColor(c: number | null | undefined): string | undefined {
  if (c == null) return undefined
  return c > 0 ? '#00d4a0' : c < 0 ? '#ff4444' : '#94a3b8'
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
  rules: StrategyRule[]
  series?: string
  globalSnapshots?: Snapshot[]
  defaultShowExecutions?: boolean
  // When set, scope the run to the most-recent N markets and include a
  // "skipped" row for every scoped market no rule filled (simulator feed).
  marketLimit?: number
  // Time-to-close windows to shade on each execution chart.
  ttcWindows?: TtcWindow[]
}

export default function StrategyBacktest({ rules, series = 'KXBTC15M', globalSnapshots = [], defaultShowExecutions = false, marketLimit, ttcWindows }: Props) {
  const [result, setResult] = useState<Result | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showTrades, setShowTrades] = useState(defaultShowExecutions)
  const reqId = useRef(0)

  const rulesKey = JSON.stringify(rules)

  useEffect(() => {
    const id = ++reqId.current
    const timer = setTimeout(async () => {
      setLoading(true)
      setError(null)
      try {
        const resp = await fetch('/api/backtest/strategy', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ rules, series, market_limit: marketLimit }),
        })
        if (!resp.ok) throw new Error('Backtest failed')
        const data: Result = await resp.json()
        if (id === reqId.current) setResult(data)
      } catch (e: any) {
        if (id === reqId.current) setError(e.message || 'Backtest failed')
      } finally {
        if (id === reqId.current) setLoading(false)
      }
    }, 550)
    return () => clearTimeout(timer)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rulesKey, series, marketLimit])

  const s = result?.summary
  const hasFills = !!s && s.trade_count > 0
  const hasFeed = !!result && result.trades.length > 0

  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
        <div className="stat-label" style={{ margin: 0 }}>Historical Backtest</div>
        {loading && <span style={{ fontSize: 11, color: '#64748b' }}>Simulating…</span>}
        {!loading && hasFills && (
          <span style={{ fontSize: 11, color: '#64748b' }}>
            {s!.trade_count.toLocaleString()} simulated trades
            {marketLimit ? ` across the last ${marketLimit} markets` : ' across history'}
          </span>
        )}
      </div>

      {error && (
        <div style={{ fontSize: 12, color: '#ff4444', padding: '8px 0' }}>{error}</div>
      )}

      {!error && !hasFeed && !loading && (
        <div style={{ fontSize: 12, color: '#475569', padding: '10px 0' }}>
          No historical fills yet — add an entry price (and a limit-sell or hold exit) to a rule to simulate it.
        </div>
      )}

      {hasFills && (
        <>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
            <Stat
              label="Total P&L"
              value={`${s!.total_pnl_cents >= 0 ? '+' : ''}${centsToUSD(s!.total_pnl_cents)}`}
              color={pnlColor(s!.total_pnl_cents)}
            />
            <Stat
              label="ROI"
              value={s!.roi_pct != null ? `${s!.roi_pct > 0 ? '+' : ''}${s!.roi_pct}%` : '—'}
              color={pnlColor(s!.roi_pct)}
            />
            <Stat
              label="Win Rate"
              value={s!.win_rate != null ? `${s!.win_rate}%` : '—'}
              color={s!.win_rate != null && s!.win_rate >= 50 ? '#00d4a0' : '#fbbf24'}
              sub={`${s!.win_count}W / ${s!.loss_count}L`}
            />
            <Stat label="Trades" value={s!.trade_count.toLocaleString()} sub={s!.sold_count ? `${s!.sold_count.toLocaleString()} sold` : undefined} />
            {s!.fill_rate != null && (
              <Stat
                label="Fill Rate"
                value={`${s!.fill_rate}%`}
                color={s!.fill_rate >= 90 ? '#00d4a0' : s!.fill_rate >= 70 ? '#fbbf24' : '#ff4444'}
                sub={s!.no_fill_count ? `${s!.no_fill_count.toLocaleString()} no fill` : undefined}
              />
            )}
            <Stat
              label="Avg P&L"
              value={s!.avg_pnl_cents != null ? `${s!.avg_pnl_cents > 0 ? '+' : ''}${centsToUSD(s!.avg_pnl_cents)}` : '—'}
              color={pnlColor(s!.avg_pnl_cents)}
            />
            <Stat label="Avg Fill" value={s!.avg_fill_price != null ? `${s!.avg_fill_price}¢` : '—'} />
            <Stat label="Total Cost" value={centsToUSD(s!.total_cost_cents)} />
          </div>

          {result!.rules.length > 1 && (
            <div className="table-panel" style={{ marginBottom: 10 }}>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Rule</th>
                      <th>Trades</th>
                      <th>Win %</th>
                      <th>Avg Fill</th>
                      <th>Avg P&L</th>
                      <th>ROI</th>
                      <th>Total P&L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result!.rules.map(r => (
                      <tr key={r.rule_id}>
                        <td style={{ color: '#f1f5f9', fontWeight: 600 }}>{r.rule_name || r.rule_id}</td>
                        <td>{r.trade_count.toLocaleString()}</td>
                        <td style={{ color: (r.win_rate ?? 0) >= 50 ? '#00d4a0' : '#94a3b8' }}>{r.win_rate ?? '—'}%</td>
                        <td className="cell-dim">{r.avg_fill_price ?? '—'}¢</td>
                        <td style={{ color: pnlColor(r.avg_pnl_cents) }}>{r.avg_pnl_cents != null ? `${r.avg_pnl_cents > 0 ? '+' : ''}${centsToUSD(r.avg_pnl_cents)}` : '—'}</td>
                        <td style={{ color: pnlColor(r.roi_pct) }}>{r.roi_pct != null ? `${r.roi_pct}%` : '—'}</td>
                        <td style={{ color: pnlColor(r.total_pnl_cents) }}>{r.total_pnl_cents >= 0 ? '+' : ''}{centsToUSD(r.total_pnl_cents)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

        </>
      )}

      {hasFeed && (
        <div style={{ marginTop: hasFills ? 10 : 0 }}>
          <button
            type="button"
            className="btn"
            onClick={() => setShowTrades(v => !v)}
            style={{ fontSize: 12, padding: '3px 10px', marginBottom: showTrades ? 10 : 0 }}
          >
            {showTrades ? 'Hide' : 'Show'} {marketLimit ? 'markets' : 'executions'} ({result!.trades.length})
          </button>

          {showTrades && (
            <SimulatorExecutions trades={result!.trades} globalSnapshots={globalSnapshots} ttcWindows={ttcWindows} />
          )}
        </div>
      )}
    </div>
  )
}
