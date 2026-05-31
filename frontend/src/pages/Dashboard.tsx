import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Order, Trade, Position, Snapshot, Settings, Profile, Quotes } from '../App'
import PriceActionChart from '../components/PriceActionChart'
import { centsToUSD, fmtCents, fmtPnL, fmtTime, fmtUnixTime, fmtDur, kalshiMarketUrl } from '../App'

const DEFAULT_HISTORY_LIMIT = 10
const HISTORY_LIMIT_STORAGE_KEY = 'kalshi-order-history-limit'
type CollapsibleSection = 'history' | 'trades'

function tickerOpenTime(ticker: string): string {
  const parts = ticker.split('-')
  if (parts.length < 2) return '—'
  const seg = parts[1]           // e.g. "26MAY271830"
  const hhmm = seg.slice(-4)     // "1830"
  if (!/^\d{4}$/.test(hhmm)) return '—'
  const h = parseInt(hhmm.slice(0, 2), 10)
  const m = hhmm.slice(2)
  const ampm = h >= 12 ? 'PM' : 'AM'
  const h12 = h % 12 || 12
  return `${h12}:${m} ${ampm}`
}

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
  balance: number | null
}

export default function Dashboard({ orders, trades, openOrders, positions, snapshots, quotes, settings, profiles, balance }: Props) {
  const navigate = useNavigate()
  const [collapsedSections, setCollapsedSections] = useState<Record<CollapsibleSection, boolean>>({
    history: false,
    trades: false,
  })
  const [historyLimit, setHistoryLimit] = useState(() => {
    if (typeof window === 'undefined') return DEFAULT_HISTORY_LIMIT
    const stored = window.localStorage.getItem(HISTORY_LIMIT_STORAGE_KEY)
    const parsed = Number.parseInt(stored ?? '', 10)
    return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_HISTORY_LIMIT
  })
  useEffect(() => {
    window.localStorage.setItem(HISTORY_LIMIT_STORAGE_KEY, String(historyLimit))
  }, [historyLimit])

  const [selectedTicker, setSelectedTicker] = useState<string | null>(null)
  const [pinnedTicker, setPinnedTicker] = useState<string | null>(null)
  const [selectedTrade, setSelectedTrade] = useState<string | null>(null)

  const activeProfile = profiles.find(p => p.id === settings?.active_profile_id)
  const history = orders.filter(o => o.status !== 'resting').slice(0, historyLimit)
  const marketSnapshots = useMemo(() => {
    const latestByTicker = new Map<string, Snapshot>()
    for (const snapshot of snapshots) {
      if (!latestByTicker.has(snapshot.ticker)) latestByTicker.set(snapshot.ticker, snapshot)
    }
    return Array.from(latestByTicker.values())
  }, [snapshots])

  // Auto-select the most-recently-scanned ticker unless the user has pinned one
  const mostRecentTicker = snapshots.length > 0 ? snapshots[0].ticker : null
  useEffect(() => {
    if (!pinnedTicker && mostRecentTicker) setSelectedTicker(mostRecentTicker)
  }, [mostRecentTicker, pinnedTicker])

  function updateHistoryLimit() {
    const nextValue = window.prompt('Set order history limit', String(historyLimit))
    if (nextValue == null) return

    const parsed = Number.parseInt(nextValue, 10)
    if (!Number.isFinite(parsed) || parsed < 1) return

    setHistoryLimit(Math.min(parsed, 500))
  }

  function toggleSection(section: CollapsibleSection) {
    setCollapsedSections(prev => ({ ...prev, [section]: !prev[section] }))
  }

  return (
    <div>
      {/* Portfolio Summary */}
      {(() => {
        const posArr = Array.isArray(positions) ? positions as Position[] : []
        const totalExposure = posArr.reduce((sum, p) => sum + parseFloat(p.market_exposure_dollars || '0'), 0)
        const totalRealizedPnL = posArr.reduce((sum, p) => sum + parseFloat(p.realized_pnl_dollars || '0'), 0)
        const totalUnrealizedPnL = posArr.reduce((sum, p) => {
          const contracts = Math.abs(parseFloat(p.position_fp))
          const side = parseFloat(p.position_fp) >= 0 ? 'yes' : 'no'
          const q = quotes[p.ticker]
          const bid = q ? (side === 'yes' ? q.yes_bid : q.no_bid) : null
          const exposure = parseFloat(p.market_exposure_dollars || '0')
          if (bid != null && contracts > 0) return sum + ((bid / 100) * contracts - exposure)
          return sum
        }, 0)
        return (
          <div style={{
            display: 'flex', gap: 12, margin: '16px 18px 0',
            background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 12, padding: '14px 20px', flexWrap: 'wrap',
          }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 140 }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Portfolio Balance</span>
              <span style={{ fontSize: 22, fontWeight: 800, color: '#f1f5f9' }}>
                {balance != null ? `$${((balance / 100) + totalExposure + totalUnrealizedPnL).toFixed(2)}` : '—'}
              </span>
            </div>
            <div style={{ width: 1, background: 'rgba(255,255,255,0.08)', margin: '0 4px', alignSelf: 'stretch' }} />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 120 }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Cash Balance</span>
              <span style={{ fontSize: 22, fontWeight: 800, color: '#f1f5f9' }}>
                {balance != null ? `$${(balance / 100).toFixed(2)}` : '—'}
              </span>
            </div>
            <div style={{ width: 1, background: 'rgba(255,255,255,0.08)', margin: '0 4px', alignSelf: 'stretch' }} />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 120 }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Open Positions</span>
              <span style={{ fontSize: 22, fontWeight: 800, color: '#f1f5f9' }}>
                {posArr.length > 0 ? `$${totalExposure.toFixed(2)}` : '—'}
              </span>
            </div>
            <div style={{ width: 1, background: 'rgba(255,255,255,0.08)', margin: '0 4px', alignSelf: 'stretch' }} />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 120 }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Unrealized P&L</span>
              <span style={{ fontSize: 22, fontWeight: 800, color: totalUnrealizedPnL > 0 ? '#00d4a0' : totalUnrealizedPnL < 0 ? '#ff4444' : '#f1f5f9' }}>
                {posArr.length > 0 ? `${totalUnrealizedPnL >= 0 ? '+' : ''}$${totalUnrealizedPnL.toFixed(2)}` : '—'}
              </span>
            </div>
            <div style={{ width: 1, background: 'rgba(255,255,255,0.08)', margin: '0 4px', alignSelf: 'stretch' }} />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 120 }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Realized P&L</span>
              <span style={{ fontSize: 22, fontWeight: 800, color: totalRealizedPnL > 0 ? '#00d4a0' : totalRealizedPnL < 0 ? '#ff4444' : '#f1f5f9' }}>
                {posArr.length > 0 ? `${totalRealizedPnL >= 0 ? '+' : ''}$${totalRealizedPnL.toFixed(2)}` : '—'}
              </span>
            </div>
          </div>
        )
      })()}

      {/* Active Strategy Widget */}
      {settings && (
        <section className="strategy-active-panel" style={{ margin: '16px 18px 0' }}>
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

      {/* Live Markets */}
      <div className="table-panel" style={{ marginTop: 16, marginLeft: 18, marginRight: 18 }}>
        <div className="snapshot-panel-head">
          <span className="section-toggle-label">Live Markets</span>
          <span className="tab-count">{marketSnapshots.length}</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Market</th>
                <th>Strike</th>
                <th>Live Price</th>
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
              {marketSnapshots.length === 0 ? (
                <tr><td colSpan={10} className="cell-empty">No live snapshots</td></tr>
              ) : marketSnapshots.map(s => (
                <tr
                  key={s.id}
                  onClick={() => { setPinnedTicker(s.ticker); setSelectedTicker(s.ticker) }}
                  style={{ cursor: 'pointer', background: selectedTicker === s.ticker ? 'rgba(0,212,160,0.07)' : undefined }}
                >
                  <td className="cell-ticker" style={{ color: selectedTicker === s.ticker ? '#00d4a0' : undefined }}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                      {s.ticker}
                      <a
                        href={kalshiMarketUrl(s.ticker)}
                        target="_blank"
                        rel="noreferrer"
                        onClick={e => e.stopPropagation()}
                        style={{ color: '#64748b', lineHeight: 1, textDecoration: 'none', fontSize: 11 }}
                        title="Open on Kalshi"
                      >↗</a>
                    </span>
                  </td>
                  <td className="cell-dim">{s.strike_str ?? '—'}</td>
                  <td className="cell-dim">{s.btc_price != null ? `$${s.btc_price.toLocaleString()}` : '—'}</td>
                  <td>{fmtCents(s.yes_ask)}</td>
                  <td className="cell-dim">{fmtCents(s.yes_bid)}</td>
                  <td className="cell-dim">{fmtCents(s.no_ask)}</td>
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

      {/* Market Chart */}
      {selectedTicker && (
        <div style={{ marginTop: 8, marginLeft: 18, marginRight: 18 }}>
          <PriceActionChart ticker={selectedTicker} globalSnapshots={snapshots} openOrders={openOrders} historyOrders={orders} />
        </div>
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
                    <td className="cell-dim">{fmtCents(ask)}</td>
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
                <th>Direction</th>
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
                <tr><td colSpan={9} className="cell-empty">No open orders</td></tr>
              ) : openOrders.map(o => {
                const q = quotes[o.market_ticker]
                const ask = q ? (o.side === 'yes' ? q.yes_ask : q.no_ask) : null
                const isBuy = o.order_role === 'entry'
                return (
                  <tr key={o.id}>
                    <td className="cell-ticker">
                      <a href={kalshiMarketUrl(o.market_ticker)} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                        {o.market_ticker}
                      </a>
                    </td>
                    <td><span className={`badge ${isBuy ? 'side-buy' : 'side-sell'}`}>{isBuy ? 'BUY' : 'SELL'}</span></td>
                    <td><span className={`badge ${o.side === 'yes' ? 'side-yes' : 'side-no'}`}>{o.side.toUpperCase()}</span></td>
                    <td>{o.entry_price_cents}¢</td>
                    <td className="cell-dim">{fmtCents(ask)}</td>
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
          <button
            type="button"
            className="section-toggle"
            onClick={() => toggleSection('history')}
            aria-expanded={!collapsedSections.history}
          >
            <span className="section-toggle-caret">{collapsedSections.history ? '▸' : '▾'}</span>
            <span className="section-toggle-label">Order History</span>
          </button>
          <button type="button" className="tab-count-button" onClick={updateHistoryLimit} title="Click to change the order history limit">
            <span className="tab-count">LIMIT {historyLimit}</span>
          </button>
        </div>
        {!collapsedSections.history && <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Market</th>
                <th>Side</th>
                <th>Direction</th>
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
                <tr><td colSpan={9} className="cell-empty">No order history</td></tr>
              ) : history.map(o => (
                <tr key={o.id}>
                  <td className="cell-ticker">
                    <a href={kalshiMarketUrl(o.market_ticker)} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                      {o.market_ticker}
                    </a>
                  </td>
                  <td><span className={`badge ${o.order_role === 'entry' ? 'side-buy' : 'side-sell'}`}>{o.order_role === 'entry' ? 'BUY' : 'SELL'}</span></td>
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
        </div>}
      </div>

      {/* Trades */}
      <div className="table-panel" style={{ marginTop: 16, marginLeft: 18, marginRight: 18, marginBottom: 32 }}>
        <div style={{ padding: '10px', display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            type="button"
            className="section-toggle"
            onClick={() => toggleSection('trades')}
            aria-expanded={!collapsedSections.trades}
          >
            <span className="section-toggle-caret">{collapsedSections.trades ? '▸' : '▾'}</span>
            <span className="section-toggle-label">Trades</span>
          </button>
          <span className="tab-count">{trades.length}</span>
        </div>
        {!collapsedSections.trades && <div className="table-wrap">
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
                <th>Open</th>
                <th>Close</th>
              </tr>
            </thead>
            <tbody>
              {trades.length === 0 ? (
                <tr><td colSpan={11} className="cell-empty">No trades yet</td></tr>
              ) : trades.map(t => {
                const isExpanded = selectedTrade === t.market_ticker
                return (
                  <>
                    <tr
                      key={t.market_ticker}
                      onClick={() => setSelectedTrade(prev => prev === t.market_ticker ? null : t.market_ticker)}
                      style={{ cursor: 'pointer', background: isExpanded ? 'rgba(96,165,250,0.07)' : undefined }}
                    >
                      <td className="cell-ticker" style={{ color: isExpanded ? '#60a5fa' : undefined }}>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                          <span style={{ fontSize: 10, color: '#64748b' }}>{isExpanded ? '▾' : '▸'}</span>
                          <a href={kalshiMarketUrl(t.market_ticker)} target="_blank" rel="noreferrer"
                            style={{ color: 'inherit', textDecoration: 'none' }}
                            onClick={e => e.stopPropagation()}>
                            {t.market_ticker}
                          </a>
                        </span>
                      </td>
                      <td className="cell-dim">{t.order_count}</td>
                      <td className="cell-dim">{t.entry_price_cents != null ? `${t.entry_price_cents}¢` : '—'}</td>
                      <td className={t.peak_price_cents != null && t.entry_price_cents != null && t.peak_price_cents > t.entry_price_cents ? 'cell-profit' : 'cell-dim'}>
                        {fmtCents(t.peak_price_cents)}
                      </td>
                      <td className="cell-dim">{fmtTime(t.peak_time)}</td>
                      <td><StatusBadge status={t.status} outcome={t.outcome} /></td>
                      <td className={t.net_profit_cents != null && t.net_profit_cents > 0 ? 'cell-profit' : t.net_profit_cents != null && t.net_profit_cents < 0 ? 'cell-loss' : 'cell-dim'}>
                        {t.net_profit_cents != null ? fmtPnL(t.net_profit_cents) : '—'}
                      </td>
                      <td className="cell-dim">{fmtTime(t.placed_at)}</td>
                      <td className="cell-dim">{fmtTime(t.filled_at)}</td>
                      <td className="cell-dim">{tickerOpenTime(t.market_ticker)}</td>
                      <td className="cell-dim">{fmtUnixTime(t.market_close_time)}</td>
                    </tr>
                    {isExpanded && (() => {
                      const tradeOrders = orders.filter(o => o.market_ticker === t.market_ticker)
                      return (
                        <tr key={`${t.market_ticker}-detail`}>
                          <td colSpan={11} style={{ padding: '0 0 6px 0', background: 'rgba(9,13,24,0.7)' }}>
                            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                              <thead>
                                <tr style={{ borderBottom: '1px solid #1f2637' }}>
                                  <th style={{ padding: '6px 12px', textAlign: 'left', color: '#475569', fontWeight: 700, fontSize: 10, letterSpacing: '0.05em', textTransform: 'uppercase' }}>Role</th>
                                  <th style={{ padding: '6px 12px', textAlign: 'left', color: '#475569', fontWeight: 700, fontSize: 10, letterSpacing: '0.05em', textTransform: 'uppercase' }}>Direction</th>
                                  <th style={{ padding: '6px 12px', textAlign: 'left', color: '#475569', fontWeight: 700, fontSize: 10, letterSpacing: '0.05em', textTransform: 'uppercase' }}>Entry</th>
                                  <th style={{ padding: '6px 12px', textAlign: 'left', color: '#475569', fontWeight: 700, fontSize: 10, letterSpacing: '0.05em', textTransform: 'uppercase' }}>Qty</th>
                                  <th style={{ padding: '6px 12px', textAlign: 'left', color: '#475569', fontWeight: 700, fontSize: 10, letterSpacing: '0.05em', textTransform: 'uppercase' }}>Status</th>
                                  <th style={{ padding: '6px 12px', textAlign: 'left', color: '#475569', fontWeight: 700, fontSize: 10, letterSpacing: '0.05em', textTransform: 'uppercase' }}>Payout</th>
                                  <th style={{ padding: '6px 12px', textAlign: 'left', color: '#475569', fontWeight: 700, fontSize: 10, letterSpacing: '0.05em', textTransform: 'uppercase' }}>P&L</th>
                                  <th style={{ padding: '6px 12px', textAlign: 'left', color: '#475569', fontWeight: 700, fontSize: 10, letterSpacing: '0.05em', textTransform: 'uppercase' }}>Placed</th>
                                  <th style={{ padding: '6px 12px', textAlign: 'left', color: '#475569', fontWeight: 700, fontSize: 10, letterSpacing: '0.05em', textTransform: 'uppercase' }}>Filled</th>
                                </tr>
                              </thead>
                              <tbody>
                                {tradeOrders.length === 0 ? (
                                  <tr><td colSpan={9} style={{ padding: '10px 12px', color: '#475569', textAlign: 'center' }}>No orders found</td></tr>
                                ) : tradeOrders.map(o => (
                                  <tr key={o.id} style={{ borderBottom: '1px solid #111827' }}>
                                    <td style={{ padding: '7px 12px' }}>
                                      <span className={`badge ${o.order_role === 'entry' ? 'side-buy' : 'side-sell'}`}>
                                        {o.order_role === 'entry' ? 'BUY' : 'SELL'}
                                      </span>
                                    </td>
                                    <td style={{ padding: '7px 12px' }}>
                                      <span className={`badge ${o.side === 'yes' ? 'side-yes' : 'side-no'}`}>
                                        {o.side.toUpperCase()}
                                      </span>
                                    </td>
                                    <td style={{ padding: '7px 12px', color: '#94a3b8' }}>{o.entry_price_cents}¢</td>
                                    <td style={{ padding: '7px 12px', color: '#94a3b8' }}>{o.count}</td>
                                    <td style={{ padding: '7px 12px' }}><StatusBadge status={o.status} outcome={o.outcome} /></td>
                                    <td style={{ padding: '7px 12px', color: '#94a3b8' }}>{o.payout_cents != null ? `${o.payout_cents}¢` : '—'}</td>
                                    <td style={{ padding: '7px 12px' }} className={o.net_profit_cents != null && o.net_profit_cents > 0 ? 'cell-profit' : o.net_profit_cents != null && o.net_profit_cents < 0 ? 'cell-loss' : 'cell-dim'}>
                                      {o.net_profit_cents != null ? fmtPnL(o.net_profit_cents) : '—'}
                                    </td>
                                    <td style={{ padding: '7px 12px', color: '#64748b' }}>{fmtTime(o.placed_at)}</td>
                                    <td style={{ padding: '7px 12px', color: '#64748b' }}>{fmtTime(o.filled_at)}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </td>
                        </tr>
                      )
                    })()}
                  </>
                )
              })}
            </tbody>
          </table>
        </div>}
      </div>

    </div>
  )
}
