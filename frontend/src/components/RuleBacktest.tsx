import { useState, useEffect, useRef } from 'react'
import type { StrategyRule, Snapshot } from '../types'
import { centsToUSD, ttcWindowsFromRules } from '../utils'
import SimulatorExecutions, { type SimTrade } from './SimulatorExecutions'

// Per-rule backtest metrics — mirrors the `summary` dict /api/backtest/strategy
// emits. A single-rule request makes `summary` describe exactly this rule.
export interface RuleMetrics {
  trade_count: number
  win_count: number
  loss_count: number
  win_rate: number | null
  total_pnl_cents: number
  total_cost_cents: number
  roi_pct: number | null
  avg_pnl_cents: number | null
  avg_fill_price: number | null
  sold_count: number
  expired_count: number
}

interface Result {
  summary: RuleMetrics
  trades: SimTrade[]
}

function pnlColor(c: number | null | undefined): string | undefined {
  if (c == null) return undefined
  return c > 0 ? '#00d4a0' : c < 0 ? '#ff4444' : '#94a3b8'
}

// Compact inline P&L chip used inside a rule card.
function Chip({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: 1,
      minWidth: 64,
    }}>
      <div style={{ fontSize: 9, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 800, color: color ?? '#f1f5f9', lineHeight: 1.2 }}>{value}</div>
    </div>
  )
}

interface Props {
  rule: StrategyRule
  series?: string
  marketLimit?: number
  globalSnapshots?: Snapshot[]
  // Reports this rule's metrics up to the parent so it can total dynamically.
  // Called with null while loading/disabled so stale numbers don't linger.
  onResult?: (ruleId: string, metrics: RuleMetrics | null) => void
}

export default function RuleBacktest({ rule, series = 'KXBTC15M', marketLimit, globalSnapshots = [], onResult }: Props) {
  const [result, setResult] = useState<Result | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showTrades, setShowTrades] = useState(false)
  // Bumped to force a re-run of the backtest on demand (manual Run/Retry).
  const [runNonce, setRunNonce] = useState(0)
  // When off, edits to the rule no longer auto-simulate — only the Run button
  // fires a backtest. Lets you adjust many params before spending a request.
  const [auto, setAuto] = useState(true)
  const reqId = useRef(0)
  const prevNonce = useRef(runNonce)

  const ruleId = rule.id
  // Only THIS rule's shape drives the fetch — editing a sibling rule leaves
  // this key untouched, so this card keeps its result instead of resimulating.
  const ruleKey = JSON.stringify(rule)
  const disabled = rule.enabled === false

  useEffect(() => {
    if (disabled) {
      setResult(null)
      setError(null)
      setLoading(false)
      onResult?.(ruleId, null)
      return
    }
    // Was this effect fire caused by a manual Run (nonce bump) vs. a rule edit?
    const manual = runNonce !== prevNonce.current
    prevNonce.current = runNonce
    // With auto off, ignore edit-driven fires and wait for an explicit Run.
    if (!auto && !manual) return
    const id = ++reqId.current
    // A manual trigger should fire immediately; the debounce only matters for
    // the auto-runs that follow keystrokes in the rule editor.
    const delay = manual ? 0 : 450
    const timer = setTimeout(async () => {
      setLoading(true)
      setError(null)
      try {
        const resp = await fetch('/api/backtest/strategy', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ rules: [rule], series, market_limit: marketLimit }),
        })
        if (!resp.ok) throw new Error(`Backtest failed (${resp.status})`)
        const data: Result = await resp.json()
        if (id !== reqId.current) return
        setResult(data)
        onResult?.(ruleId, data.summary)
      } catch (e: any) {
        if (id !== reqId.current) return
        setError(e.message || 'Backtest failed')
        onResult?.(ruleId, null)
      } finally {
        if (id === reqId.current) setLoading(false)
      }
    }, delay)
    return () => clearTimeout(timer)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ruleKey, series, marketLimit, disabled, runNonce, auto])

  // Drop this rule's contribution to the total when the card unmounts (deleted).
  useEffect(() => () => onResult?.(ruleId, null), [ruleId]) // eslint-disable-line react-hooks/exhaustive-deps

  const ttcWindows = ttcWindowsFromRules([rule])
  const s = result?.summary
  const hasFills = !!s && s.trade_count > 0
  const hasFeed = !!result && result.trades.length > 0

  if (disabled) {
    return <div style={{ fontSize: 11, color: '#475569' }}>Rule is off — not simulated.</div>
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: hasFills ? 8 : 0 }}>
        <span style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 700 }}>
          Backtest
        </span>
        {loading && <span style={{ fontSize: 11, color: '#64748b' }}>Simulating…</span>}
        {!loading && hasFills && (
          <span style={{ fontSize: 11, color: '#64748b' }}>
            {s!.trade_count.toLocaleString()} trades
          </span>
        )}
        <button
          type="button"
          className="btn"
          onClick={() => setRunNonce(n => n + 1)}
          disabled={loading}
          style={{ fontSize: 10, padding: '2px 8px', marginLeft: 'auto' }}
          title="Re-run this rule's backtest now"
        >
          {loading ? 'Running…' : error ? 'Retry' : 'Run'}
        </button>
        <button
          type="button"
          className="btn"
          onClick={() => setAuto(v => !v)}
          aria-pressed={auto}
          style={{
            fontSize: 10,
            padding: '2px 8px',
            opacity: auto ? 1 : 0.55,
            borderColor: auto ? '#00d4a0' : undefined,
            color: auto ? '#00d4a0' : undefined,
          }}
          title={auto
            ? 'Auto-simulate on edit is ON — click to pause and adjust params freely'
            : 'Auto-simulate is OFF — edits won’t run until you press Run'}
        >
          Auto {auto ? 'On' : 'Off'}
        </button>
      </div>

      {error && <div style={{ fontSize: 12, color: '#ff4444' }}>{error}</div>}

      {!error && !loading && !hasFills && (
        <div style={{ fontSize: 11, color: '#475569' }}>
          No fills — add an entry price (and a limit-sell or hold exit) to simulate this rule.
        </div>
      )}

      {hasFills && (
        <div style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 16,
          alignItems: 'center',
          background: 'rgba(255,255,255,0.03)',
          border: '1px solid rgba(255,255,255,0.07)',
          borderRadius: 8,
          padding: '8px 12px',
        }}>
          <Chip
            label="P&L"
            value={`${s!.total_pnl_cents >= 0 ? '+' : ''}${centsToUSD(s!.total_pnl_cents)}`}
            color={pnlColor(s!.total_pnl_cents)}
          />
          <Chip
            label="ROI"
            value={s!.roi_pct != null ? `${s!.roi_pct > 0 ? '+' : ''}${s!.roi_pct}%` : '—'}
            color={pnlColor(s!.roi_pct)}
          />
          <Chip
            label="Win %"
            value={s!.win_rate != null ? `${s!.win_rate}%` : '—'}
            color={s!.win_rate != null && s!.win_rate >= 50 ? '#00d4a0' : '#fbbf24'}
          />
          <Chip label="W / L" value={`${s!.win_count} / ${s!.loss_count}`} />
          <Chip
            label="Avg P&L"
            value={s!.avg_pnl_cents != null ? `${s!.avg_pnl_cents > 0 ? '+' : ''}${centsToUSD(s!.avg_pnl_cents)}` : '—'}
            color={pnlColor(s!.avg_pnl_cents)}
          />
          <Chip label="Avg Fill" value={s!.avg_fill_price != null ? `${s!.avg_fill_price}¢` : '—'} />
        </div>
      )}

      {hasFeed && (
        <div style={{ marginTop: 8 }}>
          <button
            type="button"
            className="btn"
            onClick={() => setShowTrades(v => !v)}
            style={{ fontSize: 11, padding: '3px 10px', marginBottom: showTrades ? 8 : 0 }}
          >
            {showTrades ? 'Hide' : 'Show'} {marketLimit ? 'markets' : 'executions'} ({result!.trades.length})
          </button>
          {showTrades && (
            <SimulatorExecutions trades={result!.trades} globalSnapshots={globalSnapshots} ttcWindows={ttcWindows} />
          )}
        </div>
      )}
    </div>
  )
}
