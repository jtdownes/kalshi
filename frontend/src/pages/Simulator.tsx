import { useState } from 'react'
import type { StrategyRule, Profile } from '../types'
import RuleBuilder, { defaultRule } from '../components/RuleBuilder'
import StrategyBacktest from '../components/StrategyBacktest'

const SUPPORTED_MARKETS = [
  { value: 'KXBTC15M', label: 'Bitcoin 15 Minute' },
] as const

interface Props {
  profiles: Profile[]
}

export default function Simulator({ profiles }: Props) {
  const [rules, setRules] = useState<StrategyRule[]>([defaultRule()])
  const [series, setSeries] = useState<string>('KXBTC15M')

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
        <StrategyBacktest rules={rules} series={series} defaultShowExecutions />
      </div>
    </div>
  )
}
