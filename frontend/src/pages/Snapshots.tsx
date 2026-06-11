import { useEffect, useMemo, useState } from 'react'
import { NavLink } from 'react-router-dom'
import type { Snapshot, Order, Profile, StrategyRule } from '../types'
import { fmtCents, fmtDur, fmtTime, fmtUnixTime, kalshiMarketUrl, cryptoPriceForTicker } from '../utils'
import PriceActionChart from '../components/PriceActionChart'
import ScannedMarkets from '../components/ScannedMarkets'

// Series the rule backtester can replay — used to show, per market, what the
// active strategy would have done (Won / Lost / Skipped / Bad data).
const BACKTESTABLE_SERIES = ['KXBTC15M', 'KXETH15M'] as const

type Outcome = 'sold' | 'expired' | 'won' | 'lost' | 'stopped' | 'skipped' | 'bad_data'

interface SimRow {
  ticker: string
  outcome: Outcome
  pnl_cents: number | null
  reason?: string | null
}

const OUTCOME_COLOR: Record<Outcome, string> = {
  sold: '#00d4a0', won: '#00d4a0',
  expired: '#ff4444', lost: '#ff4444',
  stopped: '#fbbf24', skipped: '#64748b', bad_data: '#b45309',
}
const OUTCOME_LABEL: Record<Outcome, string> = {
  sold: 'Won', won: 'Won', expired: 'Lost', lost: 'Lost',
  stopped: 'Stopped', skipped: 'Skipped', bad_data: 'Bad data',
}
// When several rules touch the same market, show the most meaningful result:
// a real fill beats a bad-data exclusion, which beats a plain skip.
const OUTCOME_RANK: Record<Outcome, number> = {
  won: 3, sold: 3, lost: 3, expired: 3, stopped: 3, bad_data: 2, skipped: 1,
}

function seriesOf(ticker: string): string {
  return ticker.split('-')[0]
}

function StrategyOutcome({ row }: { row: SimRow | undefined }) {
  if (!row) return <span className="cell-dim">—</span>
  return (
    <span
      title={row.outcome === 'bad_data' && row.reason ? row.reason
        : row.pnl_cents != null ? `${row.pnl_cents > 0 ? '+' : ''}${row.pnl_cents}¢` : undefined}
      style={{
        fontSize: 11, fontWeight: 600, padding: '2px 7px', borderRadius: 10,
        background: OUTCOME_COLOR[row.outcome] + '22', color: OUTCOME_COLOR[row.outcome],
      }}
    >
      {OUTCOME_LABEL[row.outcome]}
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
}

interface Props {
  snapshots: Snapshot[]
  orders?: Order[]
  openOrders?: Order[]
  profiles?: Profile[]
  filterFn?: (ticker: string, title: string) => boolean
}

export default function Snapshots({ snapshots, orders = [], openOrders = [], profiles = [], filterFn }: Props) {
  const [allTickers, setAllTickers] = useState<TickerSummary[]>([])
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null)
  const [expandedTicker, setExpandedTicker] = useState<string | null>(null)
  const [expandedHistory, setExpandedHistory] = useState<Snapshot[]>([])
  const [expandedLoading, setExpandedLoading] = useState(false)
  const [expandedError, setExpandedError] = useState<string | null>(null)
  // ticker → what the active strategy would have done on that market.
  const [outcomes, setOutcomes] = useState<Record<string, SimRow>>({})

  // The active strategy's rules drive the per-market outcome column. Combine
  // every active profile's rules so a market shows a trade if any of them fired.
  const activeRules = useMemo<StrategyRule[]>(() => {
    const active = profiles.filter(p => p.is_active && p.rules?.length)
    return active.flatMap(p => p.rules ?? [])
  }, [profiles])
  const rulesKey = useMemo(() => JSON.stringify(activeRules), [activeRules])

  // Backtest the active rules over each replayable series and fold the result
  // into a ticker→outcome map. The backtester already emits skipped / bad_data
  // rows for markets that didn't trade, so the whole feed gets a status.
  useEffect(() => {
    if (!activeRules.length) {
      setOutcomes({})
      return
    }
    let cancelled = false
    Promise.all(
      BACKTESTABLE_SERIES.map(series =>
        fetch('/api/backtest/strategy', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ rules: activeRules, series, market_limit: 1000 }),
        })
          .then(r => (r.ok ? r.json() : null))
          .catch(() => null),
      ),
    ).then(results => {
      if (cancelled) return
      const map: Record<string, SimRow> = {}
      for (const res of results) {
        for (const t of (res?.trades ?? []) as SimRow[]) {
          const prev = map[t.ticker]
          if (!prev || OUTCOME_RANK[t.outcome] > OUTCOME_RANK[prev.outcome]) map[t.ticker] = t
        }
      }
      setOutcomes(map)
    })
    return () => { cancelled = true }
  }, [rulesKey]) // eslint-disable-line react-hooks/exhaustive-deps

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
                <th>Yes Ask</th>
                <th>Yes Bid</th>
                <th>No Ask</th>
                <th className="hide-sm">Volume</th>
                <th className="hide-sm">OI</th>
                <th>Strategy</th>
                <th className="hide-sm">Scanned</th>
              </tr>
            </thead>
            <tbody>
              {marketSnapshots.length === 0 ? (
                <tr><td colSpan={10} className="cell-empty">No live snapshots</td></tr>
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
                  <td>{fmtCents(snapshot.yes_ask)}</td>
                  <td className="cell-dim">{fmtCents(snapshot.yes_bid)}</td>
                  <td className="cell-dim">{fmtCents(snapshot.no_ask)}</td>
                  <td className="cell-dim hide-sm">{snapshot.volume != null ? snapshot.volume.toLocaleString() : '—'}</td>
                  <td className="cell-dim hide-sm">{snapshot.open_interest != null ? snapshot.open_interest.toLocaleString() : '—'}</td>
                  <td><StrategyOutcome row={outcomes[snapshot.ticker]} /></td>
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
                <th>Yes Ask</th>
                <th>Yes Bid</th>
                <th>No Ask</th>
                <th className="hide-sm">Volume</th>
                <th className="hide-sm">OI</th>
                <th>Strategy</th>
                <th className="hide-sm">Scanned</th>
              </tr>
            </thead>
            <tbody>
              {allTickers.length === 0 ? (
                <tr><td colSpan={10} className="cell-empty">Loading markets…</td></tr>
              ) : filteredAllTickers.length === 0 ? (
                <tr><td colSpan={10} className="cell-empty">No markets for this filter</td></tr>
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
                    <td>{fmtCents(t.yes_ask)}</td>
                    <td className="cell-dim">{fmtCents(t.yes_bid)}</td>
                    <td className="cell-dim">{fmtCents(t.no_ask)}</td>
                    <td className="cell-dim hide-sm">{t.volume != null ? t.volume.toLocaleString() : '—'}</td>
                    <td className="cell-dim hide-sm">{t.open_interest != null ? t.open_interest.toLocaleString() : '—'}</td>
                    <td><StrategyOutcome row={outcomes[t.ticker]} /></td>
                    <td className="cell-dim hide-sm">{fmtTime(t.scanned_at)}</td>
                  </tr>
                  {expandedTicker === t.ticker && (
                    <tr key={`${t.ticker}-history`} className="snapshot-history-row">
                      <td colSpan={10} className="snapshot-history-cell">
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