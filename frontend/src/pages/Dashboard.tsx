import { Fragment, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Order, Trade, Position, Snapshot, Settings, Profile, Quotes } from '../types'
import PriceActionChart from '../components/PriceActionChart'
import PnLCalendar from '../components/PnLCalendar'
import { centsToUSD, fmtCents, fmtPnL, fmtTime, fmtUnixTime, fmtDur, kalshiMarketUrl } from '../utils'

type CollapsibleSection = 'trades' | 'calendar'

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
    closed:   ['CLOSED',   '#00d4a0', 'rgba(0,212,160,0.14)'],
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
    trades: false,
    calendar: false,
  })

  const [selectedTicker, setSelectedTicker] = useState<string | null>(null)
  const [selectedTrade, setSelectedTrade] = useState<string | null>(null)

  // Wall-clock tick so the live table drops expired markets exactly on close,
  // not whenever the next snapshot poll happens to arrive.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const activeProfile = profiles.find(p => p.id === settings?.active_profile_id)
  // The dashboard tracks the market(s) of every active strategy — the bot scans
  // all is_active profiles, so the live table should reflect the union of their
  // series, not just the single `active_profile_id`. Other scanned series (e.g.
  // weather, which polls on its own slower cadence) are excluded so they don't
  // churn the live table or flip the auto-selected chart on every weather tick.
  const trackedKey = useMemo(() => {
    const series = new Set<string>()
    for (const p of profiles) {
      if (!p.is_active) continue
      for (const t of (p.btc_series_tickers ?? '').split(',').map(s => s.trim()).filter(Boolean)) {
        series.add(t)
      }
    }
    // Fall back to the legacy single-profile setting if no active profile carries series.
    if (series.size === 0) for (const t of (settings?.btc_series_tickers ?? [])) series.add(t)
    return Array.from(series).sort().join(',')
  }, [profiles, settings?.btc_series_tickers])
  const dashSnapshots = useMemo(() => {
    const series = trackedKey ? trackedKey.split(',') : []
    if (series.length === 0) return snapshots
    return snapshots.filter(s => series.some(ser => s.ticker.startsWith(ser + '-')))
  }, [snapshots, trackedKey])

  // Drop markets that have already expired. We compare the market's close_time
  // (unix seconds) against the live wall clock rather than the snapshot's stored
  // time_to_close_secs — that value is frozen at scan time, so once a 15-minute
  // contract closes the bot stops scanning it and the last snapshot keeps a small
  // positive ttc forever, leaving the dead market lingering in the live table and
  // flickering the auto-selected chart. close_time vs now expires it on the second.
  const liveSnapshots = useMemo(
    () => dashSnapshots.filter(s => {
      if (s.close_time) {
        const closeTs = parseInt(s.close_time, 10)
        if (!isNaN(closeTs)) return closeTs * 1000 > now
      }
      return s.time_to_close_secs == null || s.time_to_close_secs > 0
    }),
    [dashSnapshots, now],
  )

  const marketSnapshots = useMemo(() => {
    const latestByTicker = new Map<string, Snapshot>()
    for (const snapshot of liveSnapshots) {
      if (!latestByTicker.has(snapshot.ticker)) latestByTicker.set(snapshot.ticker, snapshot)
    }
    return Array.from(latestByTicker.values())
  }, [liveSnapshots])

  // Keep the chart on the market the user is watching, but follow contract
  // rollovers. A ticker's series is the part before the first '-'
  // (e.g. KXBTC15M-26JUN102030-30 -> KXBTC15M). While the selected contract is
  // still live we leave it alone — this is what stops the chart flipping between
  // BTC and ETH every scan tick. Once it expires (drops out of liveSnapshots) we
  // jump to the newest live contract of the *same* series, so the chart never
  // gets stuck on an expired market and never hops to the other asset on its own.
  useEffect(() => {
    if (liveSnapshots.length === 0) return
    if (selectedTicker && liveSnapshots.some(s => s.ticker === selectedTicker)) return
    const series = selectedTicker ? selectedTicker.split('-')[0] : null
    const sameSeries = series
      ? liveSnapshots.find(s => s.ticker.split('-')[0] === series)
      : null
    setSelectedTicker((sameSeries ?? liveSnapshots[0]).ticker)
  }, [liveSnapshots, selectedTicker])

  function toggleSection(section: CollapsibleSection) {
    setCollapsedSections(prev => ({ ...prev, [section]: !prev[section] }))
  }

  return (
    <div className="page-stack">
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
        const pnlColor = (v: number) => v > 0 ? '#00d4a0' : v < 0 ? '#ff4444' : undefined
        const activeStrategyCount = profiles.filter(p => p.is_active).length
        const cards: { label: string; value: string; color?: string; onClick?: () => void }[] = [
          { label: 'Portfolio Balance', value: balance != null ? `$${((balance / 100) + totalExposure + totalUnrealizedPnL).toFixed(2)}` : '—' },
          { label: 'Cash Balance',      value: balance != null ? `$${(balance / 100).toFixed(2)}` : '—' },
          { label: 'Active Strategies', value: String(activeStrategyCount), onClick: () => navigate('/strategies') },
          { label: 'Open Positions',    value: posArr.length > 0 ? `$${totalExposure.toFixed(2)}` : '—' },
          { label: 'Unrealized P&L',    value: posArr.length > 0 ? `${totalUnrealizedPnL >= 0 ? '+' : ''}$${totalUnrealizedPnL.toFixed(2)}` : '—', color: pnlColor(totalUnrealizedPnL) },
          { label: 'Realized P&L',      value: posArr.length > 0 ? `${totalRealizedPnL >= 0 ? '+' : ''}$${totalRealizedPnL.toFixed(2)}` : '—', color: pnlColor(totalRealizedPnL) },
        ]
        return (
          <div className="stats-row">
            {cards.map(c => (
              <div
                key={c.label}
                className="stat-card"
                onClick={c.onClick}
                style={c.onClick ? { cursor: 'pointer' } : undefined}
                title={c.onClick ? 'Manage strategies' : undefined}
              >
                <div className="stat-label">{c.label}</div>
                <div className="stat-value" style={c.color ? { color: c.color } : undefined}>{c.value}</div>
              </div>
            ))}
          </div>
        )
      })()}

      {/* P&L Calendar */}
      <div className="table-panel">
        <div style={{ padding: '10px', display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            type="button"
            className="section-toggle"
            onClick={() => toggleSection('calendar')}
            aria-expanded={!collapsedSections.calendar}
          >
            <span className="section-toggle-caret">{collapsedSections.calendar ? '▸' : '▾'}</span>
            <span className="section-toggle-label">P&amp;L Calendar</span>
          </button>
        </div>
        {!collapsedSections.calendar && <PnLCalendar />}
      </div>

      {/* Live Markets */}
      <div className="table-panel">
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
                <th className="hide-sm">Volume</th>
                <th className="hide-sm">OI</th>
                <th>TTC</th>
                <th className="hide-sm">Scanned</th>
              </tr>
            </thead>
            <tbody>
              {marketSnapshots.length === 0 ? (
                <tr><td colSpan={10} className="cell-empty">No live snapshots</td></tr>
              ) : marketSnapshots.map(s => (
                <tr
                  key={s.id}
                  onClick={() => setSelectedTicker(s.ticker)}
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
                  <td className="cell-dim">
                    {(() => {
                      const strike = s.strike_str != null ? parseFloat(s.strike_str) : null
                      if (strike == null) return '—'
                      const above = s.btc_price != null ? s.btc_price >= strike : null
                      return (
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                          ${strike.toLocaleString()}
                          {above != null && (
                            <span style={{ fontSize: 10, fontWeight: 700, color: above ? '#00d4a0' : '#ff4444' }}>
                              {above ? '▲' : '▼'}
                            </span>
                          )}
                        </span>
                      )
                    })()}
                  </td>
                  <td className="cell-dim">{s.btc_price != null ? `$${s.btc_price.toLocaleString()}` : '—'}</td>
                  <td>{fmtCents(s.yes_ask)}</td>
                  <td className="cell-dim">{fmtCents(s.yes_bid)}</td>
                  <td className="cell-dim">{fmtCents(s.no_ask)}</td>
                  <td className="cell-dim hide-sm">{s.volume != null ? s.volume.toLocaleString() : '—'}</td>
                  <td className="cell-dim hide-sm">{s.open_interest != null ? s.open_interest.toLocaleString() : '—'}</td>
                  <td className="cell-dim">{fmtDur(s.time_to_close_secs)}</td>
                  <td className="cell-dim hide-sm">{fmtTime(s.scanned_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Market Chart */}
      {selectedTicker && (
        <PriceActionChart ticker={selectedTicker} globalSnapshots={dashSnapshots} openOrders={openOrders} historyOrders={orders} />
      )}

      {/* Active Positions */}
      <div className="table-panel">
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
                <th className="hide-sm">Cost</th>
                <th>Ask</th>
                <th className="hide-sm">OI</th>
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
                    <td className="cell-dim hide-sm">${p.total_traded_dollars}</td>
                    <td className="cell-dim">{fmtCents(ask)}</td>
                    <td className="cell-dim hide-sm">{q?.open_interest != null ? q.open_interest.toLocaleString() : '—'}</td>
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
      <div className="table-panel">
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
                <th className="hide-sm">OI</th>
                <th>Status</th>
                <th className="hide-sm">Placed</th>
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
                    <td className="cell-dim hide-sm">{q?.open_interest != null ? q.open_interest.toLocaleString() : '—'}</td>
                    <td><StatusBadge status={o.status} outcome={o.outcome} /></td>
                    <td className="cell-dim hide-sm">{fmtTime(o.placed_at)}</td>
                    <td className="cell-dim">{fmtDur(o.time_to_close_at_placement)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Trades */}
      <div className="table-panel">
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
                <th>Qty</th>
                <th>Entry Cost</th>
                <th className="hide-sm">Exit Proceeds</th>
                <th>Status</th>
                <th>P&amp;L</th>
                <th className="hide-sm">Placed</th>
                <th className="hide-sm">Entry Fill</th>
                <th>Closed</th>
                <th className="hide-sm">Open</th>
                <th className="hide-sm">Close</th>
              </tr>
            </thead>
            <tbody>
              {trades.length === 0 ? (
                <tr><td colSpan={11} className="cell-empty">No trades yet</td></tr>
              ) : trades.map(t => {
                const isExpanded = selectedTrade === t.market_ticker
                return (
                  <Fragment key={t.market_ticker}>
                    <tr
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
                      <td className="cell-dim">{t.total_count}</td>
                      <td className="cell-dim">{centsToUSD(t.total_entry_cost_cents ?? 0)}</td>
                      <td className="cell-dim hide-sm">{t.total_close_proceeds_cents != null && t.total_close_proceeds_cents > 0 ? centsToUSD(t.total_close_proceeds_cents) : '—'}</td>
                      <td><StatusBadge status={t.status} outcome={t.outcome} /></td>
                      <td className={t.net_profit_cents != null && t.net_profit_cents > 0 ? 'cell-profit' : t.net_profit_cents != null && t.net_profit_cents < 0 ? 'cell-loss' : 'cell-dim'}>
                        {t.net_profit_cents != null ? fmtPnL(t.net_profit_cents) : '—'}
                      </td>
                      <td className="cell-dim hide-sm">{fmtTime(t.placed_at)}</td>
                      <td className="cell-dim hide-sm">
                        {t.first_entry_filled_at && t.last_entry_filled_at && t.first_entry_filled_at !== t.last_entry_filled_at
                          ? `${fmtTime(t.first_entry_filled_at)}–${fmtTime(t.last_entry_filled_at)}`
                          : fmtTime(t.first_entry_filled_at ?? t.filled_at)}
                      </td>
                      <td className="cell-dim">{fmtTime(t.closed_at)}</td>
                      <td className="cell-dim hide-sm">{tickerOpenTime(t.market_ticker)}</td>
                      <td className="cell-dim hide-sm">{fmtUnixTime(t.market_close_time)}</td>
                    </tr>
                    {isExpanded && (() => {
                      const tradeOrders = orders.filter(o => o.market_ticker === t.market_ticker).slice().sort((a, b) => {
                        const fa = a.filled_at ? new Date(a.filled_at).getTime() : Infinity
                        const fb = b.filled_at ? new Date(b.filled_at).getTime() : Infinity
                        return fa - fb
                      })
                      return (
                        <tr key={`${t.market_ticker}-detail`}>
                          <td colSpan={11} style={{ padding: '0 0 6px 0', background: 'rgba(9,13,24,0.7)' }}>
                            <div style={{ padding: '12px 12px 0' }}>
                              <PriceActionChart
                                ticker={t.market_ticker}
                                globalSnapshots={snapshots}
                                openOrders={openOrders}
                                historyOrders={orders}
                              />
                            </div>
                            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                              <thead>
                                <tr style={{ borderBottom: '1px solid #1f2637' }}>
                                  <th style={{ padding: '6px 12px', textAlign: 'left', color: '#475569', fontWeight: 700, fontSize: 10, letterSpacing: '0.05em', textTransform: 'uppercase' }}>Role</th>
                                  <th style={{ padding: '6px 12px', textAlign: 'left', color: '#475569', fontWeight: 700, fontSize: 10, letterSpacing: '0.05em', textTransform: 'uppercase' }}>Direction</th>
                                  <th style={{ padding: '6px 12px', textAlign: 'left', color: '#475569', fontWeight: 700, fontSize: 10, letterSpacing: '0.05em', textTransform: 'uppercase' }}>Price</th>
                                  <th style={{ padding: '6px 12px', textAlign: 'left', color: '#475569', fontWeight: 700, fontSize: 10, letterSpacing: '0.05em', textTransform: 'uppercase' }}>Qty</th>
                                  <th style={{ padding: '6px 12px', textAlign: 'left', color: '#475569', fontWeight: 700, fontSize: 10, letterSpacing: '0.05em', textTransform: 'uppercase' }}>Status</th>
                                  <th style={{ padding: '6px 12px', textAlign: 'left', color: '#475569', fontWeight: 700, fontSize: 10, letterSpacing: '0.05em', textTransform: 'uppercase' }}>Cash Flow</th>
                                  <th style={{ padding: '6px 12px', textAlign: 'left', color: '#475569', fontWeight: 700, fontSize: 10, letterSpacing: '0.05em', textTransform: 'uppercase' }}>P&L</th>
                                  <th style={{ padding: '6px 12px', textAlign: 'left', color: '#475569', fontWeight: 700, fontSize: 10, letterSpacing: '0.05em', textTransform: 'uppercase' }}>Placed</th>
                                  <th style={{ padding: '6px 12px', textAlign: 'left', color: '#475569', fontWeight: 700, fontSize: 10, letterSpacing: '0.05em', textTransform: 'uppercase' }}>Filled</th>
                                </tr>
                              </thead>
                              <tbody>
                                {tradeOrders.length === 0 ? (
                                  <tr><td colSpan={9} style={{ padding: '10px 12px', color: '#475569', textAlign: 'center' }}>No orders found</td></tr>
                                ) : tradeOrders.map(o => {
                                  const cashFlowCents = (o.entry_price_cents * o.count) * (o.order_role === 'entry' ? -1 : 1)
                                  return (
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
                                    <td style={{ padding: '7px 12px' }} className={cashFlowCents > 0 ? 'cell-profit' : cashFlowCents < 0 ? 'cell-loss' : 'cell-dim'}>
                                      {fmtPnL(cashFlowCents)}
                                    </td>
                                    <td style={{ padding: '7px 12px' }} className={o.net_profit_cents != null && o.net_profit_cents > 0 ? 'cell-profit' : o.net_profit_cents != null && o.net_profit_cents < 0 ? 'cell-loss' : 'cell-dim'}>
                                      {o.net_profit_cents != null ? fmtPnL(o.net_profit_cents) : '—'}
                                    </td>
                                    <td style={{ padding: '7px 12px', color: '#64748b' }}>{fmtTime(o.placed_at)}</td>
                                    <td style={{ padding: '7px 12px', color: '#64748b' }}>{fmtTime(o.filled_at)}</td>
                                  </tr>
                                  )
                                })}
                              </tbody>
                            </table>
                          </td>
                        </tr>
                      )
                    })()}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>}
      </div>

    </div>
  )
}
