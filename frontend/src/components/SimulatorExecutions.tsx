import { Fragment, useState } from 'react'
import type { Snapshot, Order } from '../types'
import { fmtDur, fmtTime, kalshiMarketUrl } from '../utils'
import PriceActionChart from './PriceActionChart'

// One row of the simulator feed: either a simulated fill, or a "skipped" market
// that no rule matched. Mirrors the dicts /api/backtest/strategy emits.
export interface SimTrade {
  ticker: string
  side: 'yes' | 'no' | null
  fill_time: string | null
  fill_price: number | null
  ttc_at_fill: number | null
  exit_kind: 'limit_sell' | 'hold' | null
  exit_price: number | null
  exit_time: string | null
  pnl_cents: number | null
  qty: number
  outcome: 'sold' | 'expired' | 'won' | 'lost' | 'stopped' | 'skipped'
  event_time?: string | null
}

const OUTCOME_COLOR: Record<string, string> = {
  sold: '#00d4a0',
  won: '#00d4a0',
  expired: '#ff4444',
  lost: '#ff4444',
  stopped: '#fbbf24',
  skipped: '#64748b',
}
const OUTCOME_LABEL: Record<string, string> = {
  sold: 'Sold',
  won: 'Won',
  expired: 'Expired',
  lost: 'Lost',
  stopped: 'Stopped',
  skipped: 'Skipped',
}

function pnlColor(c: number | null | undefined): string | undefined {
  if (c == null) return undefined
  return c > 0 ? '#00d4a0' : c < 0 ? '#ff4444' : '#94a3b8'
}

// Synthetic order markers so PriceActionChart draws a Buy dot at the fill and a
// Sell dot at the limit-sell/stop exit — the same markers the Markets tab shows
// for real fills. Skipped markets have no fill, so no markers.
function markersFor(t: SimTrade): Order[] {
  if (!t.fill_time || t.fill_price == null || !t.side) return []
  const won = (t.pnl_cents ?? 0) > 0
  const orders: Order[] = [{
    market_ticker: t.ticker,
    side: t.side,
    order_role: 'entry',
    entry_price_cents: t.fill_price,
    filled_at: t.fill_time,
    placed_at: t.fill_time,
    status: 'filled',
    outcome: won ? 'win' : 'loss',
  } as unknown as Order]
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

  const filledCount = trades.filter(t => t.outcome !== 'skipped').length

  return (
    <section className="table-panel">
      <div className="snapshot-panel-head">
        <span className="section-toggle-label">Simulated Markets</span>
        <span style={{ fontSize: 11, color: '#64748b' }}>
          {trades.length.toLocaleString()} market{trades.length === 1 ? '' : 's'} · {filledCount.toLocaleString()} filled · newest first
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
              <th>Time</th>
            </tr>
          </thead>
          <tbody>
            {trades.length === 0 ? (
              <tr><td colSpan={9} className="cell-empty">No simulated markets</td></tr>
            ) : trades.map((t, i) => {
              const key = `${t.ticker}-${t.fill_time ?? t.event_time}-${t.side}-${i}`
              const isOpen = expanded === key
              const skipped = t.outcome === 'skipped'
              return (
                <Fragment key={key}>
                  <tr
                    className={`snapshot-market-row${isOpen ? ' snapshot-row-active' : ''}`}
                    onClick={() => setExpanded(isOpen ? null : key)}
                    style={skipped ? { opacity: 0.6 } : undefined}
                  >
                    <td className="cell-chevron">{isOpen ? '▾' : '▸'}</td>
                    <td className="cell-ticker">
                      <a href={kalshiMarketUrl(t.ticker)} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }} onClick={e => e.stopPropagation()}>
                        {t.ticker}
                      </a>
                    </td>
                    <td style={t.side ? { color: t.side === 'yes' ? '#3b82f6' : '#a78bfa', fontWeight: 600 } : { color: '#475569' }}>{t.side ? t.side.toUpperCase() : '—'}</td>
                    <td className="cell-dim">{t.fill_price != null ? `${t.fill_price}¢${t.qty > 1 ? ` ×${t.qty}` : ''}` : '—'}</td>
                    <td className="cell-dim">{t.exit_kind === 'limit_sell' ? `sell ${t.exit_price ?? '—'}¢` : t.exit_kind === 'hold' ? 'hold' : '—'}</td>
                    <td className="cell-dim">{fmtDur(t.ttc_at_fill)}</td>
                    <td style={{ color: pnlColor(t.pnl_cents) }}>{t.pnl_cents != null ? `${t.pnl_cents > 0 ? '+' : ''}${t.pnl_cents}¢` : '—'}</td>
                    <td>
                      <span style={{ fontSize: 11, fontWeight: 600, padding: '2px 7px', borderRadius: 10, background: OUTCOME_COLOR[t.outcome] + '22', color: OUTCOME_COLOR[t.outcome] }}>
                        {OUTCOME_LABEL[t.outcome]}
                      </span>
                    </td>
                    <td className="cell-dim">{fmtTime(t.fill_time ?? t.event_time)}</td>
                  </tr>
                  {isOpen && (
                    <tr className="snapshot-history-row">
                      <td colSpan={9} className="snapshot-history-cell">
                        <PriceActionChart
                          ticker={t.ticker}
                          globalSnapshots={globalSnapshots}
                          historyOrders={markersFor(t)}
                        />
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
