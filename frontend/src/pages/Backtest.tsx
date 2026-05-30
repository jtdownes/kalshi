import { useState, useCallback, useEffect } from 'react'
import { kalshiMarketUrl } from '../App'

interface SweepRow {
  limit_price: number
  fill_count: number
  avg_fill_price: number | null
  avg_gain: number | null
  pct_goes_up: number | null
  avg_peak_wins: number | null
  avg_peak_all: number | null
  max_peak: number | null
  pct_gain_5: number | null
  pct_gain_10: number | null
  pct_gain_25: number | null
  pct_gain_50: number | null
}

interface DetailRow {
  ticker: string
  fill_price: number
  ttc_at_fill: number | null
  peak_ask: number | null
  gain: number | null
  post_snaps: number
  outcome: 'gain_50' | 'gain_25' | 'gain_10' | 'gain_5' | 'profit' | 'loss'
}

const OUTCOME_COLOR: Record<string, string> = {
  gain_50: '#00d4a0',
  gain_25: '#3b82f6',
  gain_10: '#a78bfa',
  gain_5: '#fbbf24',
  profit: '#94a3b8',
  loss: '#ff4444',
}

const OUTCOME_LABEL: Record<string, string> = {
  gain_50: '+50c',
  gain_25: '+25c',
  gain_10: '+10c',
  gain_5: '+5c',
  profit: 'Up',
  loss: 'Loss',
}

function fmtTtc(secs: number | null): string {
  if (secs == null) return '-'
  if (secs < 60) return `${secs}s`
  return `${Math.floor(secs / 60)}m ${secs % 60}s`
}

function Th({ label, tip }: { label: string; tip: string }) {
  return (
    <th title={tip} style={{ cursor: 'help', borderBottom: '1px dashed rgba(255,255,255,0.15)' }}>
      {label}
    </th>
  )
}

export default function Backtest() {
  const [sweep, setSweep] = useState<SweepRow[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedPrice, setSelectedPrice] = useState<number | null>(null)
  const [detail, setDetail] = useState<DetailRow[]>([])
  const [detailLoading, setDetailLoading] = useState(false)

  const runSweep = useCallback(async () => {
    setLoading(true)
    setSelectedPrice(null)
    setDetail([])
    try {
      const response = await fetch('/api/backtest?min_limit=1&max_limit=50')
      setSweep(await response.json())
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    runSweep()
  }, [runSweep])

  const loadDetail = useCallback(async (price: number) => {
    if (selectedPrice === price) {
      setSelectedPrice(null)
      setDetail([])
      return
    }
    setDetailLoading(true)
    setSelectedPrice(price)
    try {
      const response = await fetch(`/api/backtest?limit_price=${price}&detail=true`)
      setDetail(await response.json())
    } finally {
      setDetailLoading(false)
    }
  }, [selectedPrice])

  const maxAvgPeakWins = Math.max(...sweep.map(row => row.avg_peak_wins ?? 0), 1)

  const outcomeCounts = detail.reduce((acc, row) => {
    acc[row.outcome] = (acc[row.outcome] ?? 0) + 1
    return acc
  }, {} as Record<string, number>)

  return (
    <div style={{ padding: '16px 18px' }}>
      <div style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
          <h2 style={{ margin: 0, fontSize: 20, fontWeight: 800, color: '#f1f5f9' }}>
            Strategy Backtester
          </h2>
          <button className="btn" onClick={runSweep} disabled={loading} style={{ fontSize: 12, padding: '3px 10px' }}>
            {loading ? 'Loading...' : 'Refresh'}
          </button>
          {!loading && sweep.length > 0 && (
            <span style={{ fontSize: 12, color: '#475569' }}>
              {sweep.reduce((sum, row) => sum + row.fill_count, 0).toLocaleString()} simulated fills | limit prices 1-50c
            </span>
          )}
        </div>

        <div style={{
          fontSize: 12,
          color: '#64748b',
          lineHeight: 1.6,
          background: 'rgba(255,255,255,0.03)',
          border: '1px solid rgba(255,255,255,0.06)',
          borderRadius: 8,
          padding: '10px 14px',
        }}>
          <strong style={{ color: '#94a3b8' }}>How to read this:</strong>{' '}
          For each limit price (1-50c), we find every market in history where the YES ask touched that price.
          We treat that as your fill. Then we track the highest YES ask reached after your fill - that is the peak.
          All gain columns are <strong style={{ color: '#f1f5f9' }}>relative to what you paid</strong>, not absolute prices.
          So "+10c" means the price went at least 10 cents above your fill - for example, filled at 4c and peaked at 14c.
          <br />
          <strong style={{ color: '#94a3b8' }}>Most fills expire at 0.</strong>{' '}
          These are 15-minute BTC contracts. When they touch low prices, they are usually about to resolve NO.
          The "Avg Peak (wins only)" column filters out the losers so you can see the upside on trades that actually moved.
        </div>
      </div>

      {sweep.length > 0 && (
        <div style={{
          background: 'rgba(255,255,255,0.03)',
          border: '1px solid rgba(255,255,255,0.07)',
          borderRadius: 10,
          padding: '14px 16px',
          marginBottom: 14,
        }}>
          <div style={{ fontSize: 11, color: '#64748b', marginBottom: 8, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Avg peak price on winning trades, by limit price - click to see individual markets
          </div>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 90 }}>
            {sweep.map(row => {
              const height = row.avg_peak_wins ? Math.round((row.avg_peak_wins / maxAvgPeakWins) * 74) + 2 : 2
              const isSelected = selectedPrice === row.limit_price
              return (
                <div
                  key={row.limit_price}
                  onClick={() => loadDetail(row.limit_price)}
                  title={`${row.limit_price}c limit -> avg peak on wins: ${row.avg_peak_wins ?? '-'}c | ${row.pct_goes_up ?? 0}% go up`}
                  style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3, cursor: 'pointer' }}
                >
                  <div style={{
                    width: '100%',
                    height,
                    background: isSelected ? '#00d4a0' : 'rgba(59,130,246,0.7)',
                    borderRadius: '2px 2px 0 0',
                    transition: 'background 0.12s',
                    minHeight: 2,
                  }} />
                  {row.limit_price % 5 === 0 && (
                    <span style={{ fontSize: 9, color: isSelected ? '#00d4a0' : '#64748b' }}>
                      {row.limit_price}c
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {loading ? (
        <div style={{ textAlign: 'center', padding: '32px 0', color: '#475569', fontSize: 13 }}>
          Running backtest across limit prices 1-50c...
        </div>
      ) : sweep.length > 0 && (
        <div className="table-panel" style={{ marginBottom: 14 }}>
          <div style={{ padding: '10px 12px', fontSize: 12, color: '#64748b' }}>
            Click any row to see the individual markets for that limit price.
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <Th label="Limit" tip="The limit order price you placed. Your actual fill may be lower." />
                  <Th label="Avg Fill" tip="Average actual price paid at fill (<= limit, since the ask may be below your limit at trigger time)." />
                  <Th label="Fills" tip="Number of unique markets that touched this price in our historical data." />
                  <Th label="% Go Up" tip="Percentage of fills where the price went higher at any point after your fill." />
                  <Th label="Avg Peak (wins)" tip="Average highest price after fill, counting only trades where it actually went up." />
                  <Th label="Avg Peak (all)" tip="Average highest price after fill, including trades that expired at 0." />
                  <Th label="Avg Gain" tip="Average peak minus fill price across all trades, including losers." />
                  <Th label="+5c" tip="Percent of fills where price rose at least 5 cents above your fill price." />
                  <Th label="+10c" tip="Percent of fills where price rose at least 10 cents above your fill price." />
                  <Th label="+25c" tip="Percent of fills where price rose at least 25 cents above your fill price." />
                  <Th label="+50c" tip="Percent of fills where price rose at least 50 cents above your fill price." />
                </tr>
              </thead>
              <tbody>
                {sweep.map(row => {
                  const isSelected = selectedPrice === row.limit_price
                  const gainColor = (row.avg_gain ?? 0) > 0 ? '#00d4a0' : '#ff4444'
                  return (
                    <tr key={row.limit_price} onClick={() => loadDetail(row.limit_price)} style={{ cursor: 'pointer', background: isSelected ? 'rgba(0,212,160,0.07)' : undefined }}>
                      <td><strong style={{ color: isSelected ? '#00d4a0' : '#f1f5f9' }}>{row.limit_price}c</strong></td>
                      <td className="cell-dim">{row.avg_fill_price ?? '-'}c</td>
                      <td>{row.fill_count.toLocaleString()}</td>
                      <td style={{ color: (row.pct_goes_up ?? 0) > 15 ? '#fbbf24' : '#94a3b8' }}>{row.pct_goes_up ?? '-'}%</td>
                      <td><strong style={{ color: '#3b82f6' }}>{row.avg_peak_wins ?? '-'}c</strong></td>
                      <td className="cell-dim">{row.avg_peak_all ?? '-'}c</td>
                      <td style={{ color: gainColor }}>{row.avg_gain != null ? `${row.avg_gain > 0 ? '+' : ''}${row.avg_gain}c` : '-'}</td>
                      <td style={{ color: (row.pct_gain_5 ?? 0) > 10 ? '#fbbf24' : '#64748b' }}>{row.pct_gain_5 ?? '-'}%</td>
                      <td style={{ color: (row.pct_gain_10 ?? 0) > 5 ? '#a78bfa' : '#64748b' }}>{row.pct_gain_10 ?? '-'}%</td>
                      <td style={{ color: (row.pct_gain_25 ?? 0) > 3 ? '#3b82f6' : '#64748b' }}>{row.pct_gain_25 ?? '-'}%</td>
                      <td style={{ color: (row.pct_gain_50 ?? 0) > 1 ? '#00d4a0' : '#64748b' }}>{row.pct_gain_50 ?? '-'}%</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {selectedPrice !== null && (
        <div className="table-panel">
          <div style={{ padding: '10px 12px', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 700, fontSize: 13, color: '#f1f5f9' }}>{selectedPrice}c limit - each market</span>
            {detailLoading ? (
              <span style={{ fontSize: 12, color: '#64748b' }}>Loading...</span>
            ) : (
              <>
                <span className="tab-count">{detail.length}</span>
                {(['gain_50', 'gain_25', 'gain_10', 'gain_5', 'profit', 'loss'] as const).map(key => (
                  outcomeCounts[key] ? (
                    <span key={key} style={{ fontSize: 11, fontWeight: 600, padding: '2px 7px', borderRadius: 10, background: OUTCOME_COLOR[key] + '22', color: OUTCOME_COLOR[key] }}>
                      {OUTCOME_LABEL[key]} x{outcomeCounts[key]}
                    </span>
                  ) : null
                ))}
              </>
            )}
          </div>
          {!detailLoading && detail.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Market</th>
                    <th>Fill Price</th>
                    <th title="Time remaining on the contract when you filled">TTC at Fill</th>
                    <th title="Highest YES ask seen after your fill">Peak Ask</th>
                    <th title="Peak minus fill price - your best possible gain if you sold at the top">Gain</th>
                    <th title="Number of snapshots recorded after this fill">Snaps</th>
                    <th>Outcome</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.map(row => (
                    <tr key={row.ticker}>
                      <td className="cell-ticker">
                        <a href={kalshiMarketUrl(row.ticker)} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>{row.ticker}</a>
                      </td>
                      <td className="cell-dim">{row.fill_price}c</td>
                      <td className="cell-dim">{fmtTtc(row.ttc_at_fill)}</td>
                      <td><strong>{row.peak_ask ?? '-'}c</strong></td>
                      <td style={{ color: (row.gain ?? 0) > 0 ? '#00d4a0' : '#ff4444' }}>{row.gain != null ? `${row.gain > 0 ? '+' : ''}${row.gain}c` : '-'}</td>
                      <td className="cell-dim">{row.post_snaps}</td>
                      <td>
                        <span style={{ fontSize: 11, fontWeight: 600, padding: '2px 7px', borderRadius: 10, background: OUTCOME_COLOR[row.outcome] + '22', color: OUTCOME_COLOR[row.outcome] }}>
                          {OUTCOME_LABEL[row.outcome]}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
