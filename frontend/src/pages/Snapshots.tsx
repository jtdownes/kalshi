import { useEffect, useMemo, useState } from 'react'
import type { Snapshot } from '../App'
import { fmtCents, fmtDur, fmtTime, fmtUnixTime, kalshiMarketUrl } from '../App'

const DEFAULT_LIVE_LIMIT = 10
const LIVE_LIMIT_STORAGE_KEY = 'kalshi-snapshots-live-limit'
const DEFAULT_HISTORY_LIMIT = 200
const HISTORY_LIMIT_STORAGE_KEY = 'kalshi-snapshots-history-limit'

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
}

export default function Snapshots({ snapshots }: Props) {
  const [liveLimit, setLiveLimit] = useState(() => {
    if (typeof window === 'undefined') return DEFAULT_LIVE_LIMIT
    const stored = window.localStorage.getItem(LIVE_LIMIT_STORAGE_KEY)
    const parsed = Number.parseInt(stored ?? '', 10)
    return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_LIVE_LIMIT
  })
  const [historyLimit, setHistoryLimit] = useState(() => {
    if (typeof window === 'undefined') return DEFAULT_HISTORY_LIMIT
    const stored = window.localStorage.getItem(HISTORY_LIMIT_STORAGE_KEY)
    const parsed = Number.parseInt(stored ?? '', 10)
    return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_HISTORY_LIMIT
  })
  const [allTickers, setAllTickers] = useState<TickerSummary[]>([])
  const [expandedTicker, setExpandedTicker] = useState<string | null>(null)
  const [expandedHistory, setExpandedHistory] = useState<Snapshot[]>([])
  const [expandedLoading, setExpandedLoading] = useState(false)
  const [expandedError, setExpandedError] = useState<string | null>(null)

  useEffect(() => {
    window.localStorage.setItem(LIVE_LIMIT_STORAGE_KEY, String(liveLimit))
  }, [liveLimit])

  useEffect(() => {
    window.localStorage.setItem(HISTORY_LIMIT_STORAGE_KEY, String(historyLimit))
  }, [historyLimit])

  // Fetch all distinct tickers from the DB for the historical panel
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
    return Array.from(latestByTicker.values())
  }, [snapshots])

  const visibleLiveSnapshots = useMemo(() => marketSnapshots.slice(0, liveLimit), [liveLimit, marketSnapshots])

  function updateLiveLimit() {
    const nextValue = window.prompt('Set live snapshot limit', String(liveLimit))
    if (nextValue == null) return
    const parsed = Number.parseInt(nextValue, 10)
    if (!Number.isFinite(parsed) || parsed < 1) return
    setLiveLimit(Math.min(parsed, 500))
  }

  function updateHistoryLimit() {
    const nextValue = window.prompt('Set historical snapshot limit', String(historyLimit))
    if (nextValue == null) return
    const parsed = Number.parseInt(nextValue, 10)
    if (!Number.isFinite(parsed) || parsed < 1) return
    setHistoryLimit(Math.min(parsed, 1000))
  }

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
    fetch(`/api/snapshots?ticker=${encodeURIComponent(ticker)}&limit=${historyLimit}`)
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
      <section className="table-panel">
        <div className="snapshot-panel-head">
          <div>
            <span className="section-toggle-label">Live Markets</span>
            <span className="snapshot-panel-subtitle">One current row per market.</span>
          </div>
          <button type="button" className="tab-count-button" onClick={updateLiveLimit} title="Click to change the live snapshot limit">
            <span className="tab-count">LIMIT {liveLimit}</span>
          </button>
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
              {visibleLiveSnapshots.length === 0 ? (
                <tr><td colSpan={9} className="cell-empty">No live snapshots</td></tr>
              ) : visibleLiveSnapshots.map(snapshot => (
                <tr key={snapshot.id}>
                  <td className="cell-ticker">
                    <a href={kalshiMarketUrl(snapshot.ticker)} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                      {snapshot.ticker}
                    </a>
                  </td>
                  <td className="cell-dim">{snapshot.strike_str ?? '—'}</td>
                  <td>{fmtCents(snapshot.yes_ask)}</td>
                  <td className="cell-dim">{fmtCents(snapshot.yes_bid)}</td>
                  <td className="cell-dim">{fmtCents(snapshot.no_ask)}</td>
                  <td className="cell-dim">{snapshot.volume != null ? snapshot.volume.toLocaleString() : '—'}</td>
                  <td className="cell-dim">{snapshot.open_interest != null ? snapshot.open_interest.toLocaleString() : '—'}</td>
                  <td className="cell-dim">{fmtDur(snapshot.time_to_close_secs)}</td>
                  <td className="cell-dim">{fmtTime(snapshot.scanned_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="table-panel">
        <div className="snapshot-panel-head">
          <div>
            <span className="section-toggle-label">Historical Feed</span>
            <span className="snapshot-panel-subtitle">All markets in the database. Click a market to expand its snapshot history.</span>
          </div>
          <button type="button" className="tab-count-button" onClick={updateHistoryLimit} title="Click to change the historical snapshot limit">
            <span className="tab-count">LIMIT {historyLimit}</span>
          </button>
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
                <th>Volume</th>
                <th>OI</th>
                <th>TTC</th>
                <th>Scanned</th>
              </tr>
            </thead>
            <tbody>
              {allTickers.length === 0 ? (
                <tr><td colSpan={10} className="cell-empty">Loading markets…</td></tr>
              ) : allTickers.map(t => (
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
                    <td className="cell-dim">{t.volume != null ? t.volume.toLocaleString() : '—'}</td>
                    <td className="cell-dim">{t.open_interest != null ? t.open_interest.toLocaleString() : '—'}</td>
                    <td className="cell-dim">{fmtDur(t.time_to_close_secs)}</td>
                    <td className="cell-dim">{fmtTime(t.scanned_at)}</td>
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
                          <div className="snapshot-history-scroll">
                            <table className="snapshot-history-table">
                              <thead>
                                <tr>
                                  <th>Scanned</th>
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
                                {expandedHistory.map(snap => (
                                  <tr key={snap.id}>
                                    <td className="cell-dim">{fmtTime(snap.scanned_at)}</td>
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