import { Fragment, useState } from 'react'
import type { Snapshot, Order } from '../types'
import { fmtCents, fmtDur, fmtTime, fmtUnixTime, kalshiMarketUrl } from '../utils'
import PriceActionChart from './PriceActionChart'

// One simulated fill produced by the backtest. Mirrors the trade dicts the
// /api/backtest/strategy endpoint emits.
export interface SimTrade {
  ticker: string
  side: 'yes' | 'no'
  fill_time: string | null
  fill_price: number
  ttc_at_fill: number | null
  exit_kind: 'limit_sell' | 'hold'
  exit_price: number | null
  exit_time: string | null
  pnl_cents: number
  qty: number
  outcome: 'sold' | 'expired' | 'won' | 'lost' | 'stopped'
}

const OUTCOME_COLOR: Record<string, string> = {
  sold: '#00d4a0',
  won: '#00d4a0',
  expired: '#ff4444',
  lost: '#ff4444',
  stopped: '#fbbf24',
}
const OUTCOME_LABEL: Record<string, string> = {
  sold: 'Sold',
  won: 'Won',
  expired: 'Expired',
  lost: 'Lost',
  stopped: 'Stopped',
}

function pnlColor(c: number | null | undefined): string | undefined {
  if (c == null) return undefined
  return c > 0 ? '#00d4a0' : c < 0 ? '#ff4444' : '#94a3b8'
}

// Synthetic order markers so PriceActionChart draws a Buy dot at the fill and a
// Sell dot at the limit-sell/stop exit — the same markers the Markets tab shows
// for real fills.
function markersFor(t: SimTrade): Order[] {
  const won = t.pnl_cents > 0
  const orders: Order[] = []
  if (t.fill_time) {
    orders.push({
      market_ticker: t.ticker,
      side: t.side,
      order_role: 'entry',
      entry_price_cents: t.fill_price,
      filled_at: t.fill_time,
      placed_at: t.fill_time,
      status: 'filled',
      outcome: won ? 'win' : 'loss',
    } as unknown as Order)
  }
  if (t.exit_time && t.exit_price != null) {
    orders.push({
      market_ticker: t.ticker,
      side: t.side,
      order_role: 'exit',
      entry_price_cents: t.exit_price,
      filled_at: t.exit_time,
      placed_at: t.exit_time,
      status: 'filled',
      outcome: won ? 'win' : 'loss',
    } as unknown as Order)
  }
  return orders
}

interface Props {
  trades: SimTrade[]
  globalSnapshots?: Snapshot[]
}

export default function SimulatorExecutions({ trades, globalSnapshots = [] }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const [history, setHistory] = useState<Snapshot[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function toggle(key: string, ticker: string) {
    if (expanded === key) {
      setExpanded(null)
      setHistory([])
      setError(null)
      return
    }
    setExpanded(key)
    setHistory([])
    setError(null)
    setLoading(true)
    fetch(`/api/snapshots?ticker=${encodeURIComponent(ticker)}`)
      .then(r => {
        if (!r.ok) throw new Error('Failed to load snapshot history')
        return r.json()
      })
      .then((data: Snapshot[]) => {
        setHistory(data)
        setLoading(false)
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Failed to load snapshot history')
        setLoading(false)
      })
  }

  return (
    <section className="table-panel">
      <div className="snapshot-panel-head">
        <span className="section-toggle-label">Simulated Executions</span>
        <span style={{ fontSize: 11, color: '#64748b' }}>
          {trades.length.toLocaleString()} fill{trades.length === 1 ? '' : 's'} · newest first
        </span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th className="cell-chevron-th" />
              <th>Market</th>
              <th>Side</th>
              <th>Fill</th>
              <th>Exit</th>
              <th>TTC</th>
              <th>P&L</th>
              <th>Outcome</th>
              <th>Filled</th>
            </tr>
          </thead>
          <tbody>
            {trades.length === 0 ? (
              <tr><td colSpan={9} className="cell-empty">No simulated executions</td></tr>
            ) : trades.map((t, i) => {
              const key = `${t.ticker}-${t.fill_time}-${t.side}-${i}`
              const isOpen = expanded === key
              return (
                <Fragment key={key}>
                  <tr
                    className={`snapshot-market-row${isOpen ? ' snapshot-row-active' : ''}`}
                    onClick={() => toggle(key, t.ticker)}
                  >
                    <td className="cell-chevron">{isOpen ? '▾' : '▸'}</td>
                    <td className="cell-ticker">
                      <a href={kalshiMarketUrl(t.ticker)} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }} onClick={e => e.stopPropagation()}>
                        {t.ticker}
                      </a>
                    </td>
                    <td style={{ color: t.side === 'yes' ? '#3b82f6' : '#a78bfa', fontWeight: 600 }}>{t.side.toUpperCase()}</td>
                    <td className="cell-dim">{t.fill_price}¢{t.qty > 1 ? ` ×${t.qty}` : ''}</td>
                    <td className="cell-dim">{t.exit_kind === 'limit_sell' ? `sell ${t.exit_price ?? '—'}¢` : 'hold'}</td>
                    <td className="cell-dim">{fmtDur(t.ttc_at_fill)}</td>
                    <td style={{ color: pnlColor(t.pnl_cents) }}>{t.pnl_cents > 0 ? '+' : ''}{t.pnl_cents}¢</td>
                    <td>
                      <span style={{ fontSize: 11, fontWeight: 600, padding: '2px 7px', borderRadius: 10, background: OUTCOME_COLOR[t.outcome] + '22', color: OUTCOME_COLOR[t.outcome] }}>
                        {OUTCOME_LABEL[t.outcome]}
                      </span>
                    </td>
                    <td className="cell-dim">{fmtTime(t.fill_time)}</td>
                  </tr>
                  {isOpen && (
                    <tr className="snapshot-history-row">
                      <td colSpan={9} className="snapshot-history-cell">
                        {loading ? (
                          <div className="snapshot-history-status">Loading…</div>
                        ) : error ? (
                          <div className="snapshot-history-status snapshot-history-error">{error}</div>
                        ) : (
                          <>
                            <PriceActionChart
                              ticker={t.ticker}
                              globalSnapshots={globalSnapshots}
                              historyOrders={markersFor(t)}
                            />
                            {history.length === 0 ? (
                              <div className="snapshot-history-status">No stored snapshots for this market</div>
                            ) : (
                              <div className="snapshot-history-scroll">
                                <table className="snapshot-history-table">
                                  <thead>
                                    <tr>
                                      <th>Scanned</th>
                                      <th>Live Price</th>
                                      <th>Yes Ask</th>
                                      <th>Yes Bid</th>
                                      <th>No Ask</th>
                                      <th>No Bid</th>
                                      <th>Volume</th>
                                      <th>OI</th>
                                      <th>TTC</th>
                                      <th>Close</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {history.map(snap => (
                                      <tr key={snap.id}>
                                        <td className="cell-dim">{fmtTime(snap.scanned_at)}</td>
                                        <td className="cell-dim">{snap.btc_price != null ? `$${snap.btc_price.toLocaleString()}` : '—'}</td>
                                        <td>{fmtCents(snap.yes_ask)}</td>
                                        <td className="cell-dim">{fmtCents(snap.yes_bid)}</td>
                                        <td className="cell-dim">{fmtCents(snap.no_ask)}</td>
                                        <td className="cell-dim">{fmtCents(snap.no_bid)}</td>
                                        <td className="cell-dim">{snap.volume != null ? snap.volume.toLocaleString() : '—'}</td>
                                        <td className="cell-dim">{snap.open_interest != null ? snap.open_interest.toLocaleString() : '—'}</td>
                                        <td className="cell-dim">{fmtDur(snap.time_to_close_secs)}</td>
                                        <td className="cell-dim">{fmtUnixTime(snap.close_time)}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            )}
                          </>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
