import { useEffect, useMemo, useState } from 'react'
import type { StrategyRule, Profile } from '../types'
import RuleBuilder, { defaultRule } from '../components/RuleBuilder'
import StrategyBacktest from '../components/StrategyBacktest'
import { ttcWindowsFromRules } from '../utils'

const SUPPORTED_MARKETS = [
  { value: 'KXBTC15M', label: 'Bitcoin 15 Minute' },
] as const

const RULES_STORAGE_KEY = 'simulator.rules.v1'

// Restore the rules the user was last editing so a refresh doesn't wipe them.
function loadStoredRules(): StrategyRule[] {
  try {
    const raw = localStorage.getItem(RULES_STORAGE_KEY)
    if (!raw) return [defaultRule()]
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed) && parsed.length > 0) return parsed
  } catch {
    /* corrupt/unavailable storage — fall through to a fresh rule */
  }
  return [defaultRule()]
}

interface Props {
  profiles: Profile[]
}

export default function Simulator({ profiles }: Props) {
  const [rules, setRules] = useState<StrategyRule[]>(loadStoredRules)
  const [series, setSeries] = useState<string>('KXBTC15M')

  // Persist rules on every change so they survive a page refresh.
  useEffect(() => {
    try {
      localStorage.setItem(RULES_STORAGE_KEY, JSON.stringify(rules))
    } catch {
      /* storage full/unavailable — non-fatal, just won't persist */
    }
  }, [rules])

  const ttcWindows = useMemo(() => ttcWindowsFromRules(rules), [rules])

  const handleLoadFrom = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const profileId = Number(e.target.value)
    if (!profileId) return
    const profile = profiles.find(p => p.id === profileId)
    if (profile?.rules?.length) {
      setRules(profile.rules)
    }
    // Reset the select back to placeholder
    e.target.value = ''
  }

  return (
    <div className="strategies-view">
      <section className="strategy-active-panel">
        <div className="strategy-active-main">
          <div className="stat-label">Rule Simulator</div>
          <h2 style={{ margin: '2px 0 6px' }}>Build and backtest rules without saving</h2>
          <div style={{ fontSize: 12, color: '#64748b', marginBottom: 8 }}>
            Edit rules freely — the backtest updates automatically. Nothing here affects your live strategies.
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          {profiles.length > 0 && (
            <select
              className="select"
              defaultValue=""
              onChange={handleLoadFrom}
              style={{ minWidth: 180 }}
            >
              <option value="" disabled>Load from strategy…</option>
              {profiles.map(p => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          )}
          <select
            className="select"
            value={series}
            onChange={e => setSeries(e.target.value)}
          >
            {SUPPORTED_MARKETS.map(m => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
          <button
            className="btn"
            onClick={() => setRules([defaultRule()])}
          >
            Reset Rules
          </button>
        </div>
      </section>

      <div style={{ padding: '0 18px 32px' }}>
        <RuleBuilder rules={rules} onChange={setRules} />
        <StrategyBacktest rules={rules} series={series} defaultShowExecutions marketLimit={1000} ttcWindows={ttcWindows} />
      </div>
    </div>
  )
}
