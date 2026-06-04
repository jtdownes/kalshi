import { useState, useEffect, useRef } from 'react'
import type { StrategyRule } from '../App'
import { centsToUSD, kalshiMarketUrl } from '../App'

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
}

interface RuleResult extends Metrics {
  rule_id: string
  rule_name: string
}

interface Trade {
  ticker: string
  side: 'yes' | 'no'
  fill_price: number
  ttc_at_fill: number | null
  exit_kind: 'limit_sell' | 'hold'
  exit_price: number | null
  pnl_cents: number
  qty: number
  outcome: 'sold' | 'expired' | 'won' | 'lost'
}

interface Result {
  summary: Metrics
  rules: RuleResult[]
  trades: Trade[]
}

const OUTCOME_COLOR: Record<string, string> = {
  sold: '#00d4a0',
  won: '#00d4a0',
  expired: '#ff4444',
  lost: '#ff4444',
}
const OUTCOME_LABEL: Record<string, string> = {
  sold: 'Sold',
  won: 'Won',
  expired: 'Expired',
  lost: 'Lost',
}

function fmtTtc(secs: number | null): string {
  if (secs == null) return '—'
  if (secs < 60) return `${secs}s`
  return `${Math.floor(secs / 60)}m ${secs % 60}s`
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
}

export default function StrategyBacktest({ rules, series = 'KXBTC15M' }: Props) {
  const [result, setResult] = useState<Result | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showTrades, setShowTrades] = useState(false)
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
          body: JSON.stringify({ rules, series }),
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
  }, [rulesKey, series])

  const s = result?.summary
  const hasFills = !!s && s.trade_count > 0

  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
        <div className="stat-label" style={{ margin: 0 }}>Historical Backtest</div>
        {loading && <span style={{ fontSize: 11, color: '#64748b' }}>Simulating…</span>}
        {!loading && hasFills && (
          <span style={{ fontSize: 11, color: '#64748b' }}>
            {s!.trade_count.toLocaleString()} simulated trades across history
          </span>
        )}
      </div>

      <div style={{
        fontSize: 11,
        color: '#64748b',
        lineHeight: 1.55,
        background: 'rgba(255,255,255,0.02)',
        border: '1px solid rgba(255,255,255,0.06)',
        borderRadius: 8,
        padding: '8px 12px',
        marginBottom: 10,
      }}>
        Replays these rules against every 1-second snapshot we have recorded. An entry counts as filled the first time
        a market's ask reaches your price while the conditions hold. Limit-sell exits fill when the bid later reaches your
        sell price; positions that never sell before the contract closes are counted as a <strong style={{ color: '#94a3b8' }}>full loss</strong> (conservative).
      </div>

      {error && (
        <div style={{ fontSize: 12, color: '#ff4444', padding: '8px 0' }}>{error}</div>
      )}

      {!error && !hasFills && !loading && (
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
            <Stat
              label="Avg P&L"
              value={s!.avg_pnl_cents != null ? `${s!.avg_pnl_cents > 0 ? '+' : ''}${s!.avg_pnl_cents}¢` : '—'}
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
                        <td style={{ color: pnlColor(r.avg_pnl_cents) }}>{r.avg_pnl_cents != null ? `${r.avg_pnl_cents > 0 ? '+' : ''}${r.avg_pnl_cents}¢` : '—'}</td>
                        <td style={{ color: pnlColor(r.roi_pct) }}>{r.roi_pct != null ? `${r.roi_pct}%` : '—'}</td>
                        <td style={{ color: pnlColor(r.total_pnl_cents) }}>{r.total_pnl_cents >= 0 ? '+' : ''}{centsToUSD(r.total_pnl_cents)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <button
            type="button"
            className="btn"
            onClick={() => setShowTrades(v => !v)}
            style={{ fontSize: 12, padding: '3px 10px', marginBottom: showTrades ? 10 : 0 }}
          >
            {showTrades ? 'Hide' : 'Show'} top trades ({result!.trades.length})
          </button>

          {showTrades && result!.trades.length > 0 && (
            <div className="table-panel">
              <div className="table-wrap bt-trades-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Market</th>
                      <th>Side</th>
                      <th>Fill</th>
                      <th>TTC at Fill</th>
                      <th>Exit</th>
                      <th>P&L</th>
                      <th>Outcome</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result!.trades.map((t, i) => (
                      <tr key={`${t.ticker}-${t.side}-${i}`}>
                        <td className="cell-ticker">
                          <a href={kalshiMarketUrl(t.ticker)} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>{t.ticker}</a>
                        </td>
                        <td style={{ color: t.side === 'yes' ? '#3b82f6' : '#a78bfa', fontWeight: 600 }}>{t.side.toUpperCase()}</td>
                        <td className="cell-dim">{t.fill_price}¢{t.qty > 1 ? ` ×${t.qty}` : ''}</td>
                        <td className="cell-dim">{fmtTtc(t.ttc_at_fill)}</td>
                        <td className="cell-dim">{t.exit_kind === 'limit_sell' ? `sell ${t.exit_price}¢` : 'hold'}</td>
                        <td style={{ color: pnlColor(t.pnl_cents) }}>{t.pnl_cents > 0 ? '+' : ''}{t.pnl_cents}¢</td>
                        <td>
                          <span style={{ fontSize: 11, fontWeight: 600, padding: '2px 7px', borderRadius: 10, background: OUTCOME_COLOR[t.outcome] + '22', color: OUTCOME_COLOR[t.outcome] }}>
                            {OUTCOME_LABEL[t.outcome]}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
