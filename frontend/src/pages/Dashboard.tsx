import { useNavigate } from 'react-router-dom'
import type { Order, Trade, Position, Snapshot, Settings, Profile, Quotes } from '../App'
import { centsToUSD, fmtPnL, fmtTime, fmtDur, kalshiMarketUrl } from '../App'

function StatusBadge({ status, outcome }: { status: string; outcome: string | null }) {
  if (status === 'filled' && outcome === 'win') {
    return <span className="badge" style={{ color: '#00d4a0', background: 'rgba(0,212,160,0.14)' }}>WIN</span>
  }
  if (status === 'filled' && outcome === 'loss') {
    return <span className="badge" style={{ color: '#ff4444', background: 'rgba(255,68,68,0.14)' }}>LOSS</span>
  }
  const map: Record<string, [string, string, string]> = {
    resting:  ['RESTING',  '#f5c842', 'rgba(245,200,66,0.14)'],
    filled:   ['FILLED',   '#60a5fa', 'rgba(96,165,250,0.14)'],
    canceled: ['CANCELED', '#9ca3af', 'rgba(156,163,175,0.10)'],
    pending:  ['PENDING',  '#a78bfa', 'rgba(167,139,250,0.14)'],
  }
  const [label, color, bg] = map[status] ?? [status.toUpperCase(), '#9ca3af', 'rgba(156,163,175,0.10)']
  return <span className="badge" style={{ color, background: bg }}>{label}</span>
}

interface Props {
  orders: Order[]
  trades: Trade[]
  openOrders: Order[]
  positions: Position[] | { error: string }
  snapshots: Snapshot[]
  quotes: Quotes
  settings: Settings | null
  profiles: Profile[]
}

export default function Dashboard({ orders, trades, openOrders, positions, snapshots, quotes, settings, profiles }: Props) {
  const navigate = useNavigate()
  const activeProfile = profiles.find(p => p.id === settings?.active_profile_id)
  const history = orders.filter(o => o.status !== 'resting')

  return (
    <div>
      {/* Active Strategy Widget */}
      {settings && (
        <section className="strategy-active-panel" style={{ margin: '0 18px' }}>
          <div className="strategy-active-main">
            <div className="stat-label">Active Strategy</div>
            <h2>{activeProfile?.name || settings.name || 'Current settings'}</h2>
            <p>
              This is the live bot configuration. Head to Strategies to create, edit, or switch strategies.
            </p>
            <div className="strategy-primary-actions">
              <button className="btn btn-active" onClick={() => navigate('/strategies')}>
                Manage Strategies →
              </button>
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

      {/* Active Positions */}
      <div className="table-panel" style={{ marginTop: 16, marginLeft: 18, marginRight: 18 }}>
        <div style={{ padding: '10px', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontWeight: 600, fontSize: 13 }}>Active Positions</span>
          <span className="tab-count">{Array.isArray(positions) ? positions.length : 0}</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Market</th>
                <th>Side</th>
                <th>Contracts</th>
                <th>Fill</th>
                <th>Cost</th>
                <th>Ask</th>
                <th>OI</th>
                <th>Realized P&L</th>
                <th>Unr. P&L</th>
              </tr>
            </thead>
            <tbody>
              {!Array.isArray(positions) ? (
                <tr><td colSpan={9} className="cell-empty" style={{ color: '#ff4444' }}>Error: {(positions as any).error}</td></tr>
              ) : positions.length === 0 ? (
                <tr><td colSpan={9} className="cell-empty">No active positions</td></tr>
              ) : (positions as Position[]).map(p => {
                const contracts = parseFloat(p.position_fp)
                const absContracts = Math.abs(contracts)
                const side = contracts >= 0 ? 'yes' : 'no'
                const pnl = parseFloat(p.realized_pnl_dollars)
                const q = quotes[p.ticker]
                const ask = q ? (side === 'yes' ? q.yes_ask : q.no_ask) : null
                const bid = q ? (side === 'yes' ? q.yes_bid : q.no_bid) : null
                const exposure = parseFloat(p.market_exposure_dollars)
                const fillPrice = absContracts > 0 ? (exposure / absContracts) * 100 : null
                const unrealizedPnL = bid != null && absContracts > 0
                  ? (bid / 100) * absContracts - exposure
                  : null
                return (
                  <tr key={p.ticker}>
                    <td className="cell-ticker">
                      <a href={kalshiMarketUrl(p.ticker)} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                        {p.ticker}
                      </a>
                    </td>
                    <td><span className={`badge ${side === 'yes' ? 'side-yes' : 'side-no'}`}>{side.toUpperCase()}</span></td>
                    <td>{absContracts}</td>
                    <td className="cell-dim">{fillPrice != null ? `${fillPrice.toFixed(1)}¢` : '—'}</td>
                    <td className="cell-dim">${p.total_traded_dollars}</td>
                    <td className="cell-dim">{ask != null ? `${ask}¢` : '—'}</td>
                    <td className="cell-dim">{q?.open_interest != null ? q.open_interest.toLocaleString() : '—'}</td>
                    <td className={pnl > 0 ? 'cell-profit' : pnl < 0 ? 'cell-loss' : 'cell-dim'}>
                      {pnl > 0 ? '+' : ''}${p.realized_pnl_dollars}
                    </td>
                    <td className={unrealizedPnL != null && unrealizedPnL > 0 ? 'cell-profit' : unrealizedPnL != null && unrealizedPnL < 0 ? 'cell-loss' : 'cell-dim'}>
                      {unrealizedPnL != null
                        ? `${unrealizedPnL > 0 ? '+' : unrealizedPnL < 0 ? '-' : ''}$${Math.abs(unrealizedPnL).toFixed(2)}`
                        : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Open Orders */}
      <div className="table-panel" style={{ marginTop: 16, marginLeft: 18, marginRight: 18 }}>
        <div style={{ padding: '10px', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontWeight: 600, fontSize: 13 }}>Open Orders</span>
          <span className="tab-count">{openOrders.length}</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Market</th>
                <th>Side</th>
                <th>Entry</th>
                <th>Ask</th>
                <th>OI</th>
                <th>Status</th>
                <th>Placed</th>
                <th>TTC</th>
              </tr>
            </thead>
            <tbody>
              {openOrders.length === 0 ? (
                <tr><td colSpan={8} className="cell-empty">No open orders</td></tr>
              ) : openOrders.map(o => {
                const q = quotes[o.market_ticker]
                const ask = q ? (o.side === 'yes' ? q.yes_ask : q.no_ask) : null
                return (
                  <tr key={o.id}>
                    <td className="cell-ticker">
                      <a href={kalshiMarketUrl(o.market_ticker)} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                        {o.market_ticker}
                      </a>
                    </td>
                    <td><span className={`badge ${o.side === 'yes' ? 'side-yes' : 'side-no'}`}>{o.side.toUpperCase()}</span></td>
                    <td>{o.entry_price_cents}¢</td>
                    <td className="cell-dim">{ask != null ? `${ask}¢` : '—'}</td>
                    <td className="cell-dim">{q?.open_interest != null ? q.open_interest.toLocaleString() : '—'}</td>
                    <td><StatusBadge status={o.status} outcome={o.outcome} /></td>
                    <td className="cell-dim">{fmtTime(o.placed_at)}</td>
                    <td className="cell-dim">{fmtDur(o.time_to_close_at_placement)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Order History */}
      <div className="table-panel" style={{ marginTop: 16, marginLeft: 18, marginRight: 18 }}>
        <div style={{ padding: '10px', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontWeight: 600, fontSize: 13 }}>Order History</span>
          <span className="tab-count">{history.length}</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Market</th>
                <th>Side</th>
                <th>Entry</th>
                <th>Qty</th>
                <th>Result</th>
                <th>P&L</th>
                <th>Placed</th>
                <th>Filled</th>
              </tr>
            </thead>
            <tbody>
              {history.length === 0 ? (
                <tr><td colSpan={8} className="cell-empty">No order history</td></tr>
              ) : history.map(o => (
                <tr key={o.id}>
                  <td className="cell-ticker">
                    <a href={kalshiMarketUrl(o.market_ticker)} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                      {o.market_ticker}
                    </a>
                  </td>
                  <td><span className={`badge ${o.side === 'yes' ? 'side-yes' : 'side-no'}`}>{o.side.toUpperCase()}</span></td>
                  <td>{o.entry_price_cents}¢</td>
                  <td>{o.count}</td>
                  <td><StatusBadge status={o.status} outcome={o.outcome} /></td>
                  <td className={o.net_profit_cents != null && o.net_profit_cents > 0 ? 'cell-profit' : o.net_profit_cents != null && o.net_profit_cents < 0 ? 'cell-loss' : 'cell-dim'}>
                    {o.net_profit_cents != null ? fmtPnL(o.net_profit_cents) : '—'}
                  </td>
                  <td className="cell-dim">{fmtTime(o.placed_at)}</td>
                  <td className="cell-dim">{fmtTime(o.filled_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Trades */}
      <div className="table-panel" style={{ marginTop: 16, marginLeft: 18, marginRight: 18 }}>
        <div style={{ padding: '10px', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontWeight: 600, fontSize: 13 }}>Trades</span>
          <span className="tab-count">{trades.length}</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Market</th>
                <th>Orders</th>
                <th>Entry</th>
                <th>Peak</th>
                <th>Peak Time</th>
                <th>Status</th>
                <th>P&amp;L</th>
                <th>Placed</th>
                <th>Filled</th>
              </tr>
            </thead>
            <tbody>
              {trades.length === 0 ? (
                <tr><td colSpan={9} className="cell-empty">No trades yet</td></tr>
              ) : trades.map(t => (
                <tr key={t.market_ticker}>
                  <td className="cell-ticker">
                    <a href={kalshiMarketUrl(t.market_ticker)} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                      {t.market_ticker}
                    </a>
                  </td>
                  <td className="cell-dim">{t.order_count}</td>
                  <td className="cell-dim">{t.entry_price_cents != null ? `${t.entry_price_cents}¢` : '—'}</td>
                  <td className={t.peak_price_cents != null && t.entry_price_cents != null && t.peak_price_cents > t.entry_price_cents ? 'cell-profit' : 'cell-dim'}>
                    {t.peak_price_cents != null ? `${t.peak_price_cents}¢` : '—'}
                  </td>
                  <td className="cell-dim">{fmtTime(t.peak_time)}</td>
                  <td><StatusBadge status={t.status} outcome={t.outcome} /></td>
                  <td className={t.net_profit_cents != null && t.net_profit_cents > 0 ? 'cell-profit' : t.net_profit_cents != null && t.net_profit_cents < 0 ? 'cell-loss' : 'cell-dim'}>
                    {t.net_profit_cents != null ? fmtPnL(t.net_profit_cents) : '—'}
                  </td>
                  <td className="cell-dim">{fmtTime(t.placed_at)}</td>
                  <td className="cell-dim">{fmtTime(t.filled_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Market Snapshots */}
      <div className="table-panel" style={{ marginTop: 16, marginLeft: 18, marginRight: 18, marginBottom: 32 }}>
        <div style={{ padding: '10px', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontWeight: 600, fontSize: 13 }}>Market Snapshots</span>
          <span className="tab-count">{snapshots.length}</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Market</th>
                <th>Strike</th>
                <th>Yes Ask</th>
                <th>Yes Bid</th>
                <th>No Ask</th>
                <th>Volume</th>
                <th>OI</th>
                <th>TTC</th>
                <th>Scanned</th>
              </tr>
            </thead>
            <tbody>
              {snapshots.length === 0 ? (
                <tr><td colSpan={9} className="cell-empty">No snapshots</td></tr>
              ) : snapshots.map(s => (
                <tr key={s.id}>
                  <td className="cell-ticker">
                    <a href={kalshiMarketUrl(s.ticker)} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                      {s.ticker}
                    </a>
                  </td>
                  <td className="cell-dim">{s.strike_str ?? '—'}</td>
                  <td>{s.yes_ask != null ? `${s.yes_ask}¢` : '—'}</td>
                  <td className="cell-dim">{s.yes_bid != null ? `${s.yes_bid}¢` : '—'}</td>
                  <td className="cell-dim">{s.no_ask != null ? `${s.no_ask}¢` : '—'}</td>
                  <td className="cell-dim">{s.volume != null ? s.volume.toLocaleString() : '—'}</td>
                  <td className="cell-dim">{s.open_interest != null ? s.open_interest.toLocaleString() : '—'}</td>
                  <td className="cell-dim">{fmtDur(s.time_to_close_secs)}</td>
                  <td className="cell-dim">{fmtTime(s.scanned_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
