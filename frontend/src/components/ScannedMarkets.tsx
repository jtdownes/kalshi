import { useEffect, useState } from 'react'

interface SeriesRow {
  series_ticker: string
  label: string | null
  look_ahead_seconds: number
  interval_seconds: number
  enabled: boolean
  added_at: string
  market_count?: number
}

function fmtLookAhead(s: number): string {
  if (s >= 3600) return `${Math.round(s / 3600)}h`
  if (s >= 60) return `${Math.round(s / 60)}m`
  return `${s}s`
}

export default function ScannedMarkets() {
  const [rows, setRows]       = useState<SeriesRow[]>([])
  const [ticker, setTicker]   = useState('')
  const [cadence, setCadence] = useState<'fast' | 'slow'>('slow')
  const [busy, setBusy]       = useState(false)
  const [msg, setMsg]         = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)

  const load = () =>
    fetch('/api/scanned-series').then(r => r.json()).then(setRows).catch(() => {/* silent */})
  useEffect(() => { load() }, [])

  const add = async (e: React.FormEvent) => {
    e.preventDefault()
    const t = ticker.trim().toUpperCase()
    if (!t) return
    setBusy(true); setMsg(null)
    try {
      const r = await fetch('/api/scanned-series', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ series_ticker: t, interval_seconds: cadence === 'fast' ? 1 : 30 }),
      })
      const data = await r.json()
      if (!r.ok) {
        setMsg({ kind: 'err', text: data.error || 'Failed to add market' })
      } else {
        setMsg({ kind: 'ok', text: `Added ${data.series_ticker} — ${data.market_count} open markets, look-ahead ${fmtLookAhead(data.look_ahead_seconds)}` })
        setTicker(''); load()
      }
    } catch (err) {
      setMsg({ kind: 'err', text: String(err) })
    } finally {
      setBusy(false)
    }
  }

  const toggle = async (s: string, enabled: boolean) => {
    await fetch(`/api/scanned-series/${s}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    })
    load()
  }

  const remove = async (s: string) => {
    if (!confirm(`Stop scanning ${s}? Snapshots already collected are kept.`)) return
    await fetch(`/api/scanned-series/${s}`, { method: 'DELETE' })
    load()
  }

  return (
    <section className="table-panel" style={{ marginBottom: 16 }}>
      <div className="snapshot-panel-head">
        <span className="section-toggle-label">Scanned Markets</span>
      </div>
      <div style={{ padding: '12px 16px' }}>
        <form onSubmit={add} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 10 }}>
          <input
            className="rule-input"
            placeholder="Series ticker (e.g. KXHIGHLAX)"
            value={ticker}
            onChange={e => setTicker(e.target.value)}
            style={{ flex: '1 1 220px', textTransform: 'uppercase' }}
          />
          <select className="rule-input" value={cadence} onChange={e => setCadence(e.target.value as 'fast' | 'slow')}>
            <option value="fast">Fast — poll every 1s (15-min markets)</option>
            <option value="slow">Slow — poll every 30s (daily / weather)</option>
          </select>
          <button type="submit" className="btn btn-active" disabled={busy}>{busy ? 'Adding…' : '+ Add market'}</button>
        </form>
        <div style={{ fontSize: 11, color: '#64748b', marginBottom: 10 }}>
          The scanner validates the series against Kalshi and auto-sizes the look-ahead to cover its markets
          (daily markets close ~24h out, so they need a long horizon — handled for you).
        </div>
        {msg && (
          <div style={{ fontSize: 12, marginBottom: 10, color: msg.kind === 'ok' ? '#00d4a0' : '#ff4444' }}>{msg.text}</div>
        )}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Series</th><th>Label</th><th>Look-ahead</th><th>Poll</th><th>Status</th><th />
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr><td colSpan={6} className="cell-empty">No markets configured</td></tr>
              ) : rows.map(r => (
                <tr key={r.series_ticker}>
                  <td className="cell-ticker">{r.series_ticker}</td>
                  <td className="cell-dim">{r.label || '—'}</td>
                  <td className="cell-dim">{fmtLookAhead(r.look_ahead_seconds)}</td>
                  <td className="cell-dim">{r.interval_seconds}s</td>
                  <td>
                    <button
                      className={`btn${r.enabled ? ' btn-active' : ''}`}
                      style={{ fontSize: 11, padding: '2px 10px' }}
                      onClick={() => toggle(r.series_ticker, !r.enabled)}
                    >
                      {r.enabled ? 'On' : 'Off'}
                    </button>
                  </td>
                  <td>
                    <button
                      className="btn"
                      style={{ fontSize: 11, padding: '2px 10px' }}
                      onClick={() => remove(r.series_ticker)}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  )
}
