import { useEffect, useMemo, useState } from 'react'
import { NavLink } from 'react-router-dom'
import type { Snapshot, Order } from '../types'
import { fmtCents, fmtDur, fmtTime, fmtUnixTime, fmtPnL, kalshiMarketUrl, cryptoPriceForTicker } from '../utils'
import PriceActionChart from '../components/PriceActionChart'
import ScannedMarkets from '../components/ScannedMarkets'

// Factual per-market trade status, derived from the user's real orders — NOT a
// backtest. 'won'/'lost' are settled fills; 'open' is a filled position not yet
// resolved; 'resting' is a placed-but-unfilled order.
type TradeState = 'won' | 'lost' | 'open' | 'resting'

interface MarketTrade {
  ticker: string
  state: TradeState
  side: string
  net_profit_cents: number | null
}

const STATE_COLOR: Record<TradeState, string> = {
  won: '#00d4a0', lost: '#ff4444', open: '#60a5fa', resting: '#f5c842',
}
const STATE_LABEL: Record<TradeState, string> = {
  won: 'Won', lost: 'Lost', open: 'Open', resting: 'Resting',
}
// Settled (won/lost) beats an open position beats a resting order when a market
// has more than one entry order against it.
const STATE_RANK: Record<TradeState, number> = { won: 3, lost: 3, open: 2, resting: 1 }

// Classify one entry order into a trade state, or null if it doesn't count
// (canceled / pending — nothing real happened on the market).
function entryState(o: Order): TradeState | null {
  if (o.status === 'filled' && o.outcome === 'win') return 'won'
  if (o.status === 'filled' && o.outcome === 'loss') return 'lost'
  if (o.status === 'filled') return 'open'
  if (o.status === 'resting') return 'resting'
  return null
}

function TradeStatus({ trade }: { trade: MarketTrade | undefined }) {
  if (!trade) return <span className="cell-dim">—</span>
  const color = STATE_COLOR[trade.state]
  return (
    <span
      title={trade.net_profit_cents != null ? `${trade.side.toUpperCase()} · ${fmtPnL(trade.net_profit_cents)}` : trade.side.toUpperCase()}
      style={{
        fontSize: 11, fontWeight: 600, padding: '2px 7px', borderRadius: 10,
        background: color + '22', color,
      }}
    >
      {STATE_LABEL[trade.state]}
    </span>
  )
}


interface TickerSummary {
  ticker: string
  title: string
  strike_str: string | null
  yes_ask: number | null
  yes_bid: number | null
  no_ask: number | null
  volume: number | null
  open_interest: number | null
  time_to_close_secs: number | null
  scanned_at: string
  result: string | null
}

// Official settlement of a market: yes (green) / no (red), or a dash while the
// market is still open / not yet backfilled.
function MarketResult({ result }: { result: string | null | undefined }) {
  if (result !== 'yes' && result !== 'no') return <span className="cell-dim">—</span>
  const yes = result === 'yes'
  const color = yes ? '#00d4a0' : '#ff4444'
  return (
    <span style={{
      fontSize: 11, fontWeight: 700, padding: '2px 7px', borderRadius: 10,
      background: color + '22', color,
    }}>
      {yes ? 'YES' : 'NO'}
    </span>
  )
}

interface Props {
  snapshots: Snapshot[]
  orders?: Order[]
  openOrders?: Order[]
  filterFn?: (ticker: string, title: string) => boolean
}

export default function Snapshots({ snapshots, orders = [], openOrders = [], filterFn }: Props) {
  const [allTickers, setAllTickers] = useState<TickerSummary[]>([])
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null)
  const [expandedTicker, setExpandedTicker] = useState<string | null>(null)
  const [expandedHistory, setExpandedHistory] = useState<Snapshot[]>([])
  const [expandedLoading, setExpandedLoading] = useState(false)
  const [expandedError, setExpandedError] = useState<string | null>(null)

  // ticker → the user's actual trade on that market, folded from real entry
  // orders. Settled outcomes win over open/resting when a market has several.
  const tradeByTicker = useMemo(() => {
    const map: Record<string, MarketTrade> = {}
    for (const o of orders) {
      if (o.order_role !== 'entry') continue
      const state = entryState(o)
      if (!state) continue
      const prev = map[o.market_ticker]
      if (!prev || STATE_RANK[state] > STATE_RANK[prev.state]) {
        map[o.market_ticker] = {
          ticker: o.market_ticker,
          state,
          side: o.side,
          net_profit_cents: o.net_profit_cents,
        }
      }
    }
    return map
  }, [orders])

  // ticker → official settlement result, sourced from the tickers feed so both
  // the live and historical tables can show it from one place.
  const resultByTicker = useMemo(() => {
    const map: Record<string, string> = {}
    for (const t of allTickers) if (t.result) map[t.ticker] = t.result
    return map
  }, [allTickers])

  // Fetch all distinct tickers from the DB for the historical panel
  const filteredAllTickers = useMemo(() => {
    if (!filterFn) return allTickers
    return allTickers.filter(t => filterFn(t.ticker, t.title || ''))
  }, [allTickers, filterFn])

  useEffect(() => {
    fetch('/api/snapshots/tickers')
      .then(r => r.json())
      .then((data: TickerSummary[]) => setAllTickers(data))
      .catch(() => {/* silently ignore */})
  }, [])

  const marketSnapshots = useMemo(() => {
    const latestByTicker = new Map<string, Snapshot>()
    for (const snapshot of snapshots) {
      if (!latestByTicker.has(snapshot.ticker)) latestByTicker.set(snapshot.ticker, snapshot)
    }
    let result = Array.from(latestByTicker.values())
    if (filterFn) result = result.filter(s => filterFn(s.ticker, s.title || ''))
    return result
  }, [snapshots, filterFn])

  function toggleExpanded(ticker: string) {
    if (expandedTicker === ticker) {
      setExpandedTicker(null)
      setExpandedHistory([])
      setExpandedError(null)
      return
    }
    setExpandedTicker(ticker)
    setExpandedHistory([])
    setExpandedError(null)
    setExpandedLoading(true)
    fetch(`/api/snapshots?ticker=${encodeURIComponent(ticker)}`)
      .then(r => {
        if (!r.ok) throw new Error('Failed to load snapshot history')
        return r.json()
      })
      .then((data: Snapshot[]) => {
        setExpandedHistory(data)
        setExpandedLoading(false)
      })
      .catch((err: unknown) => {
        setExpandedError(err instanceof Error ? err.message : 'Failed to load snapshot history')
        setExpandedLoading(false)
      })
  }

  return (
    <div className="snapshots-view">
      <nav className="markets-subnav" aria-label="Market category">
        {[
          { to: '/markets',         label: 'All Markets' },
          { to: '/markets/crypto',  label: 'Crypto' },
          { to: '/markets/climate', label: 'Climate' },
        ].map(item => (
          <NavLink
            key={item.to}
            to={item.to}
            end
            className={({ isActive }) => isActive ? 'subnav-link subnav-link-active' : 'subnav-link'}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <ScannedMarkets />

      <section className="table-panel">
        <div className="snapshot-panel-head">
          <span className="section-toggle-label">Live Markets</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Market</th>
                <th>Strike</th>
                <th>Live Price</th>
                <th>Result</th>
                <th className="hide-sm">Volume</th>
                <th className="hide-sm">OI</th>
                <th>My Trade</th>
                <th className="hide-sm">Scanned</th>
              </tr>
            </thead>
            <tbody>
              {marketSnapshots.length === 0 ? (
                <tr><td colSpan={8} className="cell-empty">No live snapshots</td></tr>
              ) : marketSnapshots.map(snapshot => (
                <tr 
                  key={snapshot.id} 
                  onClick={() => setSelectedTicker(snapshot.ticker)}
                  className={selectedTicker === snapshot.ticker ? 'snapshot-row-active' : ''}
                  style={{ cursor: 'pointer' }}
                >
                  <td className="cell-ticker">
                    <a href={kalshiMarketUrl(snapshot.ticker)} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                      {snapshot.ticker}
                    </a>
                  </td>
                  <td className="cell-dim">{snapshot.strike_str ?? '—'}</td>
                  <td className="cell-dim">{(() => { const p = cryptoPriceForTicker(snapshot.ticker, snapshot as unknown as Record<string, unknown>); return p != null ? `$${p.toLocaleString()}` : '—' })()}</td>
                  <td><MarketResult result={resultByTicker[snapshot.ticker]} /></td>
                  <td className="cell-dim hide-sm">{snapshot.volume != null ? snapshot.volume.toLocaleString() : '—'}</td>
                  <td className="cell-dim hide-sm">{snapshot.open_interest != null ? snapshot.open_interest.toLocaleString() : '—'}</td>
                  <td><TradeStatus trade={tradeByTicker[snapshot.ticker]} /></td>
                  <td className="cell-dim hide-sm">{fmtTime(snapshot.scanned_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {selectedTicker && (
        <section className="chart-panel">
          <PriceActionChart ticker={selectedTicker} globalSnapshots={snapshots} openOrders={openOrders} historyOrders={orders} />
        </section>
      )}

      <section className="table-panel">
        <div className="snapshot-panel-head">
          <span className="section-toggle-label">Historical Feed</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th className="cell-chevron-th" />
                <th>Market</th>
                <th>Strike</th>
                <th>Result</th>
                <th className="hide-sm">Volume</th>
                <th className="hide-sm">OI</th>
                <th>My Trade</th>
                <th className="hide-sm">Scanned</th>
              </tr>
            </thead>
            <tbody>
              {allTickers.length === 0 ? (
                <tr><td colSpan={8} className="cell-empty">Loading markets…</td></tr>
              ) : filteredAllTickers.length === 0 ? (
                <tr><td colSpan={8} className="cell-empty">No markets for this filter</td></tr>
              ) : filteredAllTickers.map(t => (
                <>
                  <tr
                    key={t.ticker}
                    className={`snapshot-market-row${expandedTicker === t.ticker ? ' snapshot-row-active' : ''}`}
                    onClick={() => toggleExpanded(t.ticker)}
                  >
                    <td className="cell-chevron">{expandedTicker === t.ticker ? '▾' : '▸'}</td>
                    <td className="cell-ticker">
                      <a href={kalshiMarketUrl(t.ticker)} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }} onClick={e => e.stopPropagation()}>
                        {t.ticker}
                      </a>
                    </td>
                    <td className="cell-dim">{t.strike_str ?? '—'}</td>
                    <td><MarketResult result={t.result} /></td>
                    <td className="cell-dim hide-sm">{t.volume != null ? t.volume.toLocaleString() : '—'}</td>
                    <td className="cell-dim hide-sm">{t.open_interest != null ? t.open_interest.toLocaleString() : '—'}</td>
                    <td><TradeStatus trade={tradeByTicker[t.ticker]} /></td>
                    <td className="cell-dim hide-sm">{fmtTime(t.scanned_at)}</td>
                  </tr>
                  {expandedTicker === t.ticker && (
                    <tr key={`${t.ticker}-history`} className="snapshot-history-row">
                      <td colSpan={8} className="snapshot-history-cell">
                        {expandedLoading ? (
                          <div className="snapshot-history-status">Loading…</div>
                        ) : expandedError ? (
                          <div className="snapshot-history-status snapshot-history-error">{expandedError}</div>
                        ) : expandedHistory.length === 0 ? (
                          <div className="snapshot-history-status">No stored snapshots for this market</div>
                        ) : (
                          <>
                            <PriceActionChart
                              ticker={t.ticker}
                              globalSnapshots={snapshots}
                              openOrders={openOrders}
                              historyOrders={orders}
                            />
                            <div className="snapshot-history-scroll">
                            <table className="snapshot-history-table">
                              <thead>
                                <tr>
                                  <th>Scanned</th>
                                  <th>Live Price</th>
                                  <th>Yes Ask</th>
                                  <th>Yes Bid</th>
                                  <th>No Ask</th>
                                  <th className="hide-sm">No Bid</th>
                                  <th className="hide-sm">Volume</th>
                                  <th className="hide-sm">OI</th>
                                  <th>TTC</th>
                                  <th className="hide-sm">Close</th>
                                </tr>
                              </thead>
                              <tbody>
                                {expandedHistory.map(snap => (
                                  <tr key={snap.id}>
                                    <td className="cell-dim">{fmtTime(snap.scanned_at)}</td>
                                    <td className="cell-dim">{(() => { const p = cryptoPriceForTicker(t.ticker, snap as unknown as Record<string, unknown>); return p != null ? `$${p.toLocaleString()}` : '—' })()}</td>
                                    <td>{fmtCents(snap.yes_ask)}</td>
                                    <td className="cell-dim">{fmtCents(snap.yes_bid)}</td>
                                    <td className="cell-dim">{fmtCents(snap.no_ask)}</td>
                                    <td className="cell-dim hide-sm">{fmtCents(snap.no_bid)}</td>
                                    <td className="cell-dim hide-sm">{snap.volume != null ? snap.volume.toLocaleString() : '—'}</td>
                                    <td className="cell-dim hide-sm">{snap.open_interest != null ? snap.open_interest.toLocaleString() : '—'}</td>
                                    <td className="cell-dim">{fmtDur(snap.time_to_close_secs)}</td>
                                    <td className="cell-dim hide-sm">{fmtUnixTime(snap.close_time)}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                          </>
                        )}
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}