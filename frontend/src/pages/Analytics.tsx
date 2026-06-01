import { useState, useCallback, useEffect } from 'react'

interface Overview {
  total_snapshots: number
  unique_markets: number
  first_snapshot: string | null
  last_snapshot: string | null
  resolved_markets: number
  yes_wins: number
  no_wins: number
}

interface EdgeCell {
  price_bucket: number
  ttc_bucket: string
  ttc_order: number
  market_count: number
  actual_win_pct: number
}

interface EVRow {
  price: number
  markets: number
  win_pct: number
  ev_cents: number
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
  return d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })
}

export default function Analytics() {
  const [overview, setOverview] = useState<Overview | null>(null)
  const [matrix, setMatrix] = useState<EdgeCell[]>([])
  const [evCurve, setEvCurve] = useState<EVRow[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [ov, mx, ev] = await Promise.all([
        fetch('/api/analytics/overview').then(r => r.json()),
        fetch('/api/analytics/edge-matrix').then(r => r.json()),
        fetch('/api/analytics/ev-curve').then(r => r.json()),
      ])
      setOverview(ov)
      setMatrix(mx)
      setEvCurve(ev)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const ttcBuckets = ['10-15m', '5-10m', '2-5m', '0-2m']
  const priceBuckets = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]

  const matrixMap: Record<string, EdgeCell> = {}
  matrix.forEach(cell => {
    matrixMap[`${cell.price_bucket}-${cell.ttc_bucket}`] = cell
  })

  const edgeColor = (priceBucket: number, winPct: number) => {
    const implied = priceBucket + 5
    const edge = winPct - implied
    if (edge > 15) return { bg: 'rgba(0,212,160,0.3)', text: '#00d4a0' }
    if (edge > 5) return { bg: 'rgba(0,212,160,0.18)', text: '#00d4a0' }
    if (edge > 0) return { bg: 'rgba(0,212,160,0.07)', text: '#6ee7b7' }
    if (edge > -5) return { bg: 'rgba(255,68,68,0.07)', text: '#fca5a5' }
    if (edge > -15) return { bg: 'rgba(255,68,68,0.18)', text: '#ff4444' }
    return { bg: 'rgba(255,68,68,0.3)', text: '#ff4444' }
  }

  return (
    <div style={{ padding: '16px 18px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <h2 style={{ margin: 0, fontSize: 20, fontWeight: 800, color: '#f1f5f9' }}>Analytics</h2>
        <button className="btn" onClick={load} disabled={loading} style={{ fontSize: 12, padding: '3px 10px' }}>
          {loading ? 'Loading...' : 'Refresh'}
        </button>
        {overview && (
          <span style={{ fontSize: 12, color: '#475569' }}>
            {fmtDate(overview.first_snapshot)} — {fmtDate(overview.last_snapshot)}
          </span>
        )}
      </div>

      {loading && !overview ? (
        <div style={{ textAlign: 'center', padding: '32px 0', color: '#475569', fontSize: 13 }}>
          Running analytics queries...
        </div>
      ) : (
        <>
          {overview && (
            <div className="stats-row" style={{ marginBottom: 18 }}>
              <div className="stat-card">
                <div className="stat-label">Total Snapshots</div>
                <div className="stat-value">{overview.total_snapshots?.toLocaleString() ?? '—'}</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">Unique Markets</div>
                <div className="stat-value">{overview.unique_markets?.toLocaleString() ?? '—'}</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">Resolved Markets</div>
                <div className="stat-value">{overview.resolved_markets?.toLocaleString() ?? '—'}</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">YES Wins</div>
                <div className="stat-value" style={{ color: '#00d4a0' }}>
                  {overview.yes_wins?.toLocaleString() ?? '—'}
                </div>
              </div>
              <div className="stat-card">
                <div className="stat-label">NO Wins</div>
                <div className="stat-value" style={{ color: '#ff4444' }}>
                  {overview.no_wins?.toLocaleString() ?? '—'}
                </div>
              </div>
              <div className="stat-card">
                <div className="stat-label">Base YES Rate</div>
                <div className="stat-value">
                  {overview.resolved_markets > 0
                    ? `${(overview.yes_wins / overview.resolved_markets * 100).toFixed(1)}%`
                    : '—'}
                </div>
                <div className="stat-sub">across all brackets</div>
              </div>
            </div>
          )}

          <div style={{
            fontSize: 12, color: '#64748b', lineHeight: 1.6,
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.06)',
            borderRadius: 8, padding: '10px 14px', marginBottom: 14,
          }}>
            <strong style={{ color: '#94a3b8' }}>Edge Matrix:</strong>{' '}
            For each YES price and time-to-close window, this shows the{' '}
            <strong style={{ color: '#f1f5f9' }}>actual historical win rate</strong>{' '}
            vs what the market price implies.
            If YES is at 20¢ the market implies 20% chance — if the actual rate is 28%, that's +8% edge.{' '}
            <span style={{ color: '#00d4a0' }}>Green</span> = underpriced (positive edge).{' '}
            <span style={{ color: '#ff4444' }}>Red</span> = overpriced (negative edge).{' '}
            n = distinct markets observed at that price/time.
          </div>

          {matrix.length > 0 && (
            <div className="table-panel" style={{ marginBottom: 18 }}>
              <div style={{ padding: '10px 12px', fontSize: 13, fontWeight: 700, color: '#f1f5f9' }}>
                Edge Matrix — Actual Win Rate vs Market Price
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>YES Price</th>
                      {ttcBuckets.map(b => <th key={b} style={{ textAlign: 'center' }}>{b} left</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {priceBuckets.map(pb => (
                      <tr key={pb}>
                        <td style={{ fontWeight: 600 }}>{pb}–{pb + 10}¢</td>
                        {ttcBuckets.map(tb => {
                          const cell = matrixMap[`${pb}-${tb}`]
                          if (!cell) {
                            return <td key={tb} style={{ textAlign: 'center', color: '#334155' }}>—</td>
                          }
                          const colors = edgeColor(pb, cell.actual_win_pct)
                          const edge = cell.actual_win_pct - (pb + 5)
                          return (
                            <td key={tb} style={{
                              textAlign: 'center', background: colors.bg, padding: '8px 10px',
                            }}>
                              <div style={{ fontWeight: 700, color: colors.text, fontSize: 15 }}>
                                {cell.actual_win_pct}%
                              </div>
                              <div style={{ fontSize: 10, color: '#64748b', marginTop: 2 }}>
                                {edge > 0 ? '+' : ''}{edge.toFixed(1)}% · n={cell.market_count}
                              </div>
                            </td>
                          )
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {evCurve.length > 0 && (
            <div className="table-panel">
              <div style={{ padding: '10px 12px' }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: '#f1f5f9', marginBottom: 4 }}>
                  Expected Value by Entry Price
                </div>
                <div style={{ fontSize: 11, color: '#64748b' }}>
                  Across every market in your data, what would you make per contract buying YES at each price?{' '}
                  <strong style={{ color: '#94a3b8' }}>EV = (win_rate × 100¢) − buy_price</strong>.{' '}
                  Positive EV = systematic edge. Does not account for Kalshi fees.
                </div>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Buy Price</th>
                      <th>Markets</th>
                      <th>Actual Win Rate</th>
                      <th>Implied Prob</th>
                      <th>EV / Contract</th>
                      <th style={{ width: 120 }}>Edge</th>
                    </tr>
                  </thead>
                  <tbody>
                    {evCurve.map(row => {
                      const positive = row.ev_cents > 0
                      const barWidth = Math.min(Math.abs(row.ev_cents) * 3, 100)
                      return (
                        <tr key={row.price}>
                          <td><strong style={{ color: '#f1f5f9' }}>{row.price}¢</strong></td>
                          <td className="cell-dim">{row.markets.toLocaleString()}</td>
                          <td style={{
                            color: positive ? '#00d4a0' : '#ff4444', fontWeight: 600,
                          }}>
                            {row.win_pct}%
                          </td>
                          <td className="cell-dim">{row.price}%</td>
                          <td style={{
                            color: positive ? '#00d4a0' : '#ff4444', fontWeight: 700,
                          }}>
                            {row.ev_cents > 0 ? '+' : ''}{row.ev_cents.toFixed(1)}¢
                          </td>
                          <td>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <div style={{
                                height: 6, borderRadius: 3,
                                width: `${barWidth}%`,
                                background: positive
                                  ? 'linear-gradient(90deg, rgba(0,212,160,0.4), #00d4a0)'
                                  : 'linear-gradient(90deg, rgba(255,68,68,0.4), #ff4444)',
                              }} />
                              <span style={{
                                fontSize: 11, fontWeight: 600,
                                color: positive ? '#00d4a0' : '#ff4444',
                                whiteSpace: 'nowrap',
                              }}>
                                {positive ? '+' : ''}{(row.win_pct - row.price).toFixed(1)}%
                              </span>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {!loading && matrix.length === 0 && evCurve.length === 0 && (
            <div style={{
              textAlign: 'center', padding: '40px 0', color: '#475569', fontSize: 13,
              background: 'rgba(255,255,255,0.03)',
              border: '1px solid rgba(255,255,255,0.07)',
              borderRadius: 8,
            }}>
              Not enough resolved markets yet. The bot needs to observe markets through their full
              lifecycle to determine outcomes. Keep collecting — patterns emerge with data.
            </div>
          )}
        </>
      )}
    </div>
  )
}
