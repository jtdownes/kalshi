import { useEffect, useMemo, useState } from 'react'
import type { Snapshot } from '../App'
import { fmtCents, fmtDur, fmtTime, fmtUnixTime, kalshiMarketUrl } from '../App'

const DEFAULT_LIVE_LIMIT = 10
const LIVE_LIMIT_STORAGE_KEY = 'kalshi-snapshots-live-limit'
const DEFAULT_HISTORY_LIMIT = 200
const HISTORY_LIMIT_STORAGE_KEY = 'kalshi-snapshots-history-limit'

interface Props {
  snapshots: Snapshot[]
}

function snapshotLabel(snapshot: Snapshot | null | undefined): string {
  if (!snapshot) return 'No market selected'
  return snapshot.title || snapshot.ticker
}

export default function Snapshots({ snapshots }: Props) {
  const [selectedTicker, setSelectedTicker] = useState('')
  const [history, setHistory] = useState<Snapshot[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState<string | null>(null)
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

  useEffect(() => {
    window.localStorage.setItem(LIVE_LIMIT_STORAGE_KEY, String(liveLimit))
  }, [liveLimit])

  useEffect(() => {
    window.localStorage.setItem(HISTORY_LIMIT_STORAGE_KEY, String(historyLimit))
  }, [historyLimit])

  const marketSnapshots = useMemo(() => {
    const latestByTicker = new Map<string, Snapshot>()
    for (const snapshot of snapshots) {
      if (!latestByTicker.has(snapshot.ticker)) latestByTicker.set(snapshot.ticker, snapshot)
    }
    return Array.from(latestByTicker.values())
  }, [snapshots])

  useEffect(() => {
    if (marketSnapshots.length === 0) {
      setSelectedTicker('')
      return
    }

    const selectedStillVisible = selectedTicker && marketSnapshots.some(snapshot => snapshot.ticker === selectedTicker)
    if (selectedStillVisible) return

    const nextTicker = marketSnapshots[0].ticker
    setSelectedTicker(nextTicker)
  }, [marketSnapshots, selectedTicker])

  useEffect(() => {
    if (!selectedTicker) {
      setHistory([])
      setHistoryError(null)
      return
    }

    let cancelled = false
    const fetchHistory = async () => {
      setHistoryLoading(true)
      setHistoryError(null)
      try {
        const response = await fetch(`/api/snapshots?ticker=${encodeURIComponent(selectedTicker)}&limit=${historyLimit}`)
        if (!response.ok) throw new Error('Failed to load snapshot history')
        const data = await response.json()
        if (!cancelled) setHistory(data)
      } catch (error) {
        if (!cancelled) {
          setHistory([])
          setHistoryError(error instanceof Error ? error.message : 'Failed to load snapshot history')
        }
      } finally {
        if (!cancelled) setHistoryLoading(false)
      }
    }

    fetchHistory()
    return () => {
      cancelled = true
    }
  }, [historyLimit, selectedTicker])

  const visibleLiveSnapshots = useMemo(() => marketSnapshots.slice(0, liveLimit), [liveLimit, marketSnapshots])
  const selectedSnapshot = useMemo(
    () => marketSnapshots.find(snapshot => snapshot.ticker === selectedTicker) ?? history[0] ?? null,
    [history, marketSnapshots, selectedTicker],
  )

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

  function inspectTicker(ticker: string) {
    const nextTicker = ticker.trim().toUpperCase()
    if (!nextTicker) return
    setSelectedTicker(nextTicker)
  }

  return (
    <div className="snapshots-view">
      <section className="table-panel">
        <div className="snapshot-panel-head">
          <div>
            <span className="section-toggle-label">Live Markets</span>
            <span className="snapshot-panel-subtitle">One current row per market. Click a market to load its historical snapshots.</span>
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
                <tr
                  key={snapshot.id}
                  className={`snapshot-market-row${snapshot.ticker === selectedTicker ? ' snapshot-row-active' : ''}`}
                  onClick={() => inspectTicker(snapshot.ticker)}
                >
                  <td className="cell-ticker">
                    <a href={kalshiMarketUrl(snapshot.ticker)} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }} onClick={event => event.stopPropagation()}>
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
            <span className="snapshot-panel-subtitle">{selectedTicker ? `${selectedTicker} · ${snapshotLabel(selectedSnapshot)}` : 'Choose a market from the live list above.'}</span>
          </div>
          <button type="button" className="tab-count-button" onClick={updateHistoryLimit} title="Click to change the historical snapshot limit">
            <span className="tab-count">LIMIT {historyLimit}</span>
          </button>
        </div>
        <div className="table-wrap">
          <table>
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
              {!selectedTicker ? (
                <tr><td colSpan={9} className="cell-empty">Select a market to inspect its history</td></tr>
              ) : historyLoading ? (
                <tr><td colSpan={9} className="cell-empty">Loading snapshot history…</td></tr>
              ) : historyError ? (
                <tr><td colSpan={9} className="cell-empty" style={{ color: '#ff4444' }}>{historyError}</td></tr>
              ) : history.length === 0 ? (
                <tr><td colSpan={9} className="cell-empty">No stored snapshots for this market</td></tr>
              ) : history.map(snapshot => (
                <tr key={snapshot.id}>
                  <td className="cell-dim">{fmtTime(snapshot.scanned_at)}</td>
                  <td>{fmtCents(snapshot.yes_ask)}</td>
                  <td className="cell-dim">{fmtCents(snapshot.yes_bid)}</td>
                  <td className="cell-dim">{fmtCents(snapshot.no_ask)}</td>
                  <td className="cell-dim">{fmtCents(snapshot.no_bid)}</td>
                  <td className="cell-dim">{snapshot.volume != null ? snapshot.volume.toLocaleString() : '—'}</td>
                  <td className="cell-dim">{snapshot.open_interest != null ? snapshot.open_interest.toLocaleString() : '—'}</td>
                  <td className="cell-dim">{fmtDur(snapshot.time_to_close_secs)}</td>
                  <td className="cell-dim">{fmtUnixTime(snapshot.close_time)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}