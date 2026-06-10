import { useEffect, useMemo, useState } from 'react'

// Webull-style monthly P&L calendar: each day cell is tinted green/red by
// realized P&L, with the dollar amount and settled-order count. A weekly
// total column runs down the right side and the header shows month stats.

interface PnLRow {
  id: number
  market_ticker: string
  net_profit_cents: number
  settled_at: string
}

interface DayAgg {
  pnlCents: number
  orders: number
}

const WEEKDAYS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa']
const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

function localDateKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function fmtUsd(cents: number, compact = false): string {
  const sign = cents > 0 ? '+' : cents < 0 ? '-' : ''
  const abs = Math.abs(cents) / 100
  if (compact && abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}k`
  return `${sign}$${abs.toFixed(2)}`
}

function pnlColor(cents: number): string {
  return cents > 0 ? '#00d4a0' : cents < 0 ? '#ff4444' : '#94a3b8'
}

export default function PnLCalendar() {
  const [rows, setRows] = useState<PnLRow[]>([])
  const [viewYear, setViewYear] = useState(() => new Date().getFullYear())
  const [viewMonth, setViewMonth] = useState(() => new Date().getMonth())

  useEffect(() => {
    let alive = true
    const load = () =>
      fetch('/api/pnl/daily')
        .then(r => (r.ok ? r.json() : []))
        .then(data => { if (alive && Array.isArray(data)) setRows(data) })
        .catch(() => { /* silent */ })
    load()
    const id = setInterval(load, 60_000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  // Group settled orders into local-timezone days
  const dailyMap = useMemo(() => {
    const map = new Map<string, DayAgg>()
    for (const r of rows) {
      const iso = r.settled_at.endsWith('Z') ? r.settled_at : r.settled_at + 'Z'
      const key = localDateKey(new Date(iso))
      const agg = map.get(key) ?? { pnlCents: 0, orders: 0 }
      agg.pnlCents += r.net_profit_cents
      agg.orders += 1
      map.set(key, agg)
    }
    return map
  }, [rows])

  // Build the weeks of the visible month (each week = 7 cells, day or null pad)
  const weeks = useMemo(() => {
    const firstDay = new Date(viewYear, viewMonth, 1).getDay()
    const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate()
    const cells: (number | null)[] = [
      ...Array(firstDay).fill(null),
      ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
    ]
    while (cells.length % 7 !== 0) cells.push(null)
    const out: (number | null)[][] = []
    for (let i = 0; i < cells.length; i += 7) out.push(cells.slice(i, i + 7))
    return out
  }, [viewYear, viewMonth])

  const dayAgg = (day: number | null): DayAgg | null => {
    if (day == null) return null
    const key = `${viewYear}-${String(viewMonth + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
    return dailyMap.get(key) ?? null
  }

  const monthStats = useMemo(() => {
    let pnl = 0, orders = 0, green = 0, red = 0
    for (const week of weeks) for (const day of week) {
      const agg = dayAgg(day)
      if (!agg) continue
      pnl += agg.pnlCents
      orders += agg.orders
      if (agg.pnlCents > 0) green++
      else if (agg.pnlCents < 0) red++
    }
    return { pnl, orders, green, red }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [weeks, dailyMap])

  const today = new Date()
  const isCurrentMonth = today.getFullYear() === viewYear && today.getMonth() === viewMonth

  function shiftMonth(delta: number) {
    const d = new Date(viewYear, viewMonth + delta, 1)
    setViewYear(d.getFullYear())
    setViewMonth(d.getMonth())
  }

  return (
    <div className="pnl-cal">
      <div className="pnl-cal-head">
        <div className="pnl-cal-nav">
          <button className="btn" onClick={() => shiftMonth(-1)} aria-label="Previous month">‹</button>
          <span className="pnl-cal-title">{MONTHS[viewMonth]} {viewYear}</span>
          <button className="btn" onClick={() => shiftMonth(1)} aria-label="Next month">›</button>
          {!isCurrentMonth && (
            <button className="btn" onClick={() => { setViewYear(today.getFullYear()); setViewMonth(today.getMonth()) }}>
              Today
            </button>
          )}
        </div>
        <div className="pnl-cal-stats">
          <span>Month <strong style={{ color: pnlColor(monthStats.pnl) }}>{fmtUsd(monthStats.pnl)}</strong></span>
          <span className="hide-sm">Days <strong style={{ color: '#00d4a0' }}>{monthStats.green}</strong>/<strong style={{ color: '#ff4444' }}>{monthStats.red}</strong></span>
          <span className="hide-sm">Orders <strong>{monthStats.orders}</strong></span>
        </div>
      </div>

      <div className="pnl-cal-grid">
        {WEEKDAYS.map(d => <div key={d} className="pnl-cal-dow">{d}</div>)}
        <div className="pnl-cal-dow pnl-cal-weekcol">Wk</div>

        {weeks.map((week, wi) => {
          const weekPnl = week.reduce((sum, day) => sum + (dayAgg(day)?.pnlCents ?? 0), 0)
          const weekHasTrades = week.some(day => dayAgg(day) != null)
          return (
            <div key={wi} className="pnl-cal-week">
              {week.map((day, di) => {
                const agg = dayAgg(day)
                const isToday = isCurrentMonth && day === today.getDate()
                const cls = [
                  'pnl-cal-day',
                  day == null ? 'pnl-cal-empty' : '',
                  agg && agg.pnlCents > 0 ? 'pnl-cal-win' : '',
                  agg && agg.pnlCents < 0 ? 'pnl-cal-loss' : '',
                  agg && agg.pnlCents === 0 ? 'pnl-cal-flat' : '',
                  isToday ? 'pnl-cal-today' : '',
                ].filter(Boolean).join(' ')
                return (
                  <div key={di} className={cls}>
                    {day != null && (
                      <>
                        <div className="pnl-cal-daynum">{day}</div>
                        {agg && (
                          <>
                            <div className="pnl-cal-amount" style={{ color: pnlColor(agg.pnlCents) }}>
                              {fmtUsd(agg.pnlCents, true)}
                            </div>
                            <div className="pnl-cal-count">{agg.orders} {agg.orders === 1 ? 'order' : 'orders'}</div>
                          </>
                        )}
                      </>
                    )}
                  </div>
                )
              })}
              <div className="pnl-cal-day pnl-cal-weekcol">
                {weekHasTrades && (
                  <div className="pnl-cal-amount" style={{ color: pnlColor(weekPnl) }}>
                    {fmtUsd(weekPnl, true)}
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
