import type {
  StrategyRule, RuleCondition, RuleField, RuleOp, RuleAction,
} from '../App'

// ── Field / operator metadata ────────────────────────────────────────────────
type Unit = 'time' | '¢' | '$' | ''

const FIELD_META: Record<RuleField, { label: string; unit: Unit }> = {
  time_to_close:      { label: 'Time to close',           unit: 'time' },
  distance_to_strike: { label: 'Distance to strike',      unit: '$' },
  yes_ask:            { label: 'YES ask',                 unit: '¢' },
  yes_bid:            { label: 'YES bid',                 unit: '¢' },
  no_ask:             { label: 'NO ask',                  unit: '¢' },
  no_bid:             { label: 'NO bid',                  unit: '¢' },
  btc_price:          { label: 'BTC price',               unit: '$' },
  spread:             { label: 'Spread (ask−bid)',        unit: '¢' },
  volume:             { label: 'Volume',                  unit: '' },
  open_interest:      { label: 'Open interest',           unit: '' },
  prior_resolution:   { label: 'Prior window (1=YES 0=NO)',  unit: '' },
  prev2_resolution:   { label: '2nd prior window (1=YES 0=NO)', unit: '' },
  btc_volatility:     { label: 'BTC volatility (recent σ)',  unit: '$' },
  btc_range:          { label: 'BTC range (recent hi−lo)',   unit: '$' },
  btc_drift:          { label: 'BTC drift (recent net move)', unit: '$' },
  strike_crossings:   { label: 'Strike crossings (whole market)',  unit: '' },
  buffer_ratio:       { label: 'Buffer ÷ volatility',        unit: '' },
}
const FIELD_ORDER = Object.keys(FIELD_META) as RuleField[]

const OP_LABELS: Record<RuleOp, string> = {
  lt: '<', lte: '≤', gt: '>', gte: '≥', eq: '=', between: 'between',
}
const OP_ORDER = Object.keys(OP_LABELS) as RuleOp[]

// ── Factories ────────────────────────────────────────────────────────────────
const newId = () =>
  (typeof crypto !== 'undefined' && crypto.randomUUID)
    ? crypto.randomUUID()
    : `r${Date.now()}${Math.floor(Math.random() * 1e6)}`

const defaultCondition = (): RuleCondition => ({ field: 'time_to_close', op: 'lt', value: null })

export const defaultRule = (): StrategyRule => ({
  id: newId(),
  name: '',
  enabled: true,
  conditions: [defaultCondition()],
  action: {
    side: 'yes',
    entry: { type: 'limit', price_cents: null },
    quantity: 1,
    exit: { type: 'hold' },
    cancel_sibling_on_fill: false,
  },
})

// ── Time-unit display helpers ────────────────────────────────────────────────
// time_to_close is stored in seconds. Show minutes when it divides evenly,
// otherwise seconds; the unit dropdown lets the user switch.
function timeUnitOf(secs: number | null | undefined): 'min' | 'sec' {
  if (secs == null) return 'min'
  return secs % 60 === 0 ? 'min' : 'sec'
}
function secsToDisplay(secs: number | null | undefined, unit: 'min' | 'sec'): number | '' {
  if (secs == null) return ''
  return unit === 'min' ? secs / 60 : secs
}
function displayToSecs(val: number, unit: 'min' | 'sec'): number {
  return unit === 'min' ? Math.round(val * 60) : Math.round(val)
}

// ── Plain-English summary ─────────────────────────────────────────────────────
function fmtFieldValue(c: RuleCondition): string {
  const meta = FIELD_META[c.field]
  const isResolution = c.field === 'prior_resolution' || c.field === 'prev2_resolution'
  const v = (n: number | null | undefined) => {
    if (n == null) return '?'
    if (isResolution) return n === 1 ? 'YES' : n === 0 ? 'NO' : String(n)
    if (meta.unit === 'time') {
      const u = timeUnitOf(n)
      return `${secsToDisplay(n, u)}${u === 'min' ? 'm' : 's'}`
    }
    if (meta.unit === '$') return `$${n}`
    if (meta.unit === '¢') return `${n}¢`
    return String(n)
  }
  if (c.op === 'between') return `${meta.label} between ${v(c.value)} and ${v(c.value2)}`
  return `${meta.label} ${OP_LABELS[c.op]} ${v(c.value)}`
}

export function ruleSummary(rule: StrategyRule): string {
  const conds = rule.conditions.length
    ? rule.conditions.map(fmtFieldValue).join('  AND  ')
    : 'always'
  const a = rule.action
  const sideTxt = a.side === 'both' ? 'YES & NO' : a.side.toUpperCase()
  const entryTxt = a.entry.type === 'ask'
    ? 'at current ask'
    : `at ${a.entry.price_cents ?? '?'}¢`
  const exitTxt = a.exit.type === 'limit_sell'
    ? `, sell @ ${a.exit.price_cents ?? '?'}¢`
    : ''
  const stopTxt = a.exit.stop_cents != null
    ? `, stop @ ${a.exit.stop_cents}¢`
    : ''
  const ocoTxt = a.side === 'both' && a.cancel_sibling_on_fill
    ? ' (first fill cancels the other)'
    : ''
  return `IF ${conds} → buy ${sideTxt} ${entryTxt} ×${a.quantity}${exitTxt}${stopTxt}${ocoTxt}`
}

// ── Component ─────────────────────────────────────────────────────────────────
interface Props {
  rules: StrategyRule[]
  onChange: (rules: StrategyRule[]) => void
  readOnly?: boolean
  /**
   * Limited-edit mode: rule names and quantities stay editable, but the rule
   * structure (conditions, side, entry/exit, add/remove/reorder) is locked.
   * Used when editing a strategy that already has historical orders.
   */
  lockStructure?: boolean
}

export default function RuleBuilder({ rules, onChange, readOnly = false, lockStructure = false }: Props) {
  // Structural controls are locked in both read-only and limited-edit modes.
  const structLocked = readOnly || lockStructure
  const patchRule = (i: number, patch: Partial<StrategyRule>) =>
    onChange(rules.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))

  const patchCondition = (ri: number, ci: number, patch: Partial<RuleCondition>) =>
    patchRule(ri, {
      conditions: rules[ri].conditions.map((c, idx) => (idx === ci ? { ...c, ...patch } : c)),
    })

  const addCondition = (ri: number) =>
    patchRule(ri, { conditions: [...rules[ri].conditions, defaultCondition()] })

  const removeCondition = (ri: number, ci: number) =>
    patchRule(ri, { conditions: rules[ri].conditions.filter((_, idx) => idx !== ci) })

  const addRule = () => onChange([...rules, defaultRule()])
  const removeRule = (i: number) => onChange(rules.filter((_, idx) => idx !== i))
  const duplicateRule = (i: number) => {
    const src = rules[i]
    const clone: StrategyRule = {
      ...src,
      id: newId(),
      name: src.name ? `${src.name} (copy)` : '',
      conditions: src.conditions.map(c => ({ ...c })),
      action: { ...src.action, entry: { ...src.action.entry }, exit: { ...src.action.exit } },
    }
    const next = [...rules]
    next.splice(i + 1, 0, clone)
    onChange(next)
  }
  const moveRule = (i: number, dir: -1 | 1) => {
    const j = i + dir
    if (j < 0 || j >= rules.length) return
    const next = [...rules]
    ;[next[i], next[j]] = [next[j], next[i]]
    onChange(next)
  }

  if (readOnly && rules.length === 0) {
    return <div className="rule-empty">This strategy has no rules.</div>
  }

  return (
    <div className="rule-builder">
      {rules.map((rule, ri) => {
        const a = rule.action
        return (
          <div key={rule.id} className={`rule-card${rule.enabled ? '' : ' rule-disabled'}`}>
            <div className="rule-head">
              <span className="rule-index">#{ri + 1}</span>
              <input
                className="rule-name-input"
                type="text"
                placeholder="Rule name (optional)"
                value={rule.name ?? ''}
                disabled={readOnly}
                onChange={e => patchRule(ri, { name: e.target.value })}
              />
              {!structLocked && (
                <div className="rule-head-actions">
                  <label className="rule-enable" title="Enable / disable this rule">
                    <input
                      type="checkbox"
                      checked={rule.enabled}
                      onChange={e => patchRule(ri, { enabled: e.target.checked })}
                    />
                    <span>{rule.enabled ? 'On' : 'Off'}</span>
                  </label>
                  <button type="button" className="rule-icon-btn" disabled={ri === 0}
                    onClick={() => moveRule(ri, -1)} title="Move up">↑</button>
                  <button type="button" className="rule-icon-btn" disabled={ri === rules.length - 1}
                    onClick={() => moveRule(ri, 1)} title="Move down">↓</button>
                  <button type="button" className="rule-icon-btn"
                    onClick={() => duplicateRule(ri)} title="Duplicate rule">⧉</button>
                  <button type="button" className="rule-icon-btn rule-icon-danger"
                    onClick={() => removeRule(ri)} title="Delete rule">✕</button>
                </div>
              )}
            </div>

            {/* IF — conditions */}
            <div className="rule-section">
              <div className="rule-section-label">IF <span>all of</span></div>
              {rule.conditions.map((c, ci) => {
                const meta = FIELD_META[c.field]
                const isTime = meta.unit === 'time'
                const unit = timeUnitOf(c.value)
                return (
                  <div key={ci} className="rule-cond-row">
                    <select className="rule-input rule-field" value={c.field} disabled={structLocked}
                      onChange={e => patchCondition(ri, ci, { field: e.target.value as RuleField })}>
                      {FIELD_ORDER.map(f => (
                        <option key={f} value={f}>{FIELD_META[f].label}</option>
                      ))}
                    </select>
                    <select className="rule-input rule-op" value={c.op} disabled={structLocked}
                      onChange={e => patchCondition(ri, ci, { op: e.target.value as RuleOp })}>
                      {OP_ORDER.map(o => (
                        <option key={o} value={o}>{OP_LABELS[o]}</option>
                      ))}
                    </select>
                    <div className="rule-value-wrap">
                      <input className="rule-input rule-value" type="number" placeholder="value"
                        disabled={structLocked}
                        value={isTime ? secsToDisplay(c.value, unit) : (c.value ?? '')}
                        onChange={e => {
                          const raw = e.target.value
                          if (raw === '') return patchCondition(ri, ci, { value: null })
                          const n = parseFloat(raw)
                          patchCondition(ri, ci, { value: isTime ? displayToSecs(n, unit) : n })
                        }} />
                      {c.op === 'between' && (
                        <>
                          <span className="rule-and">and</span>
                          <input className="rule-input rule-value" type="number" placeholder="value"
                            disabled={structLocked}
                            value={isTime ? secsToDisplay(c.value2, unit) : (c.value2 ?? '')}
                            onChange={e => {
                              const raw = e.target.value
                              if (raw === '') return patchCondition(ri, ci, { value2: null })
                              const n = parseFloat(raw)
                              patchCondition(ri, ci, { value2: isTime ? displayToSecs(n, unit) : n })
                            }} />
                        </>
                      )}
                      {isTime ? (
                        <select className="rule-unit" value={unit} disabled={structLocked}
                          onChange={e => {
                            const nextUnit = e.target.value as 'min' | 'sec'
                            // reinterpret the displayed number in the new unit
                            const disp = secsToDisplay(c.value, unit)
                            const disp2 = secsToDisplay(c.value2, unit)
                            patchCondition(ri, ci, {
                              value:  disp === '' ? c.value  : displayToSecs(disp as number, nextUnit),
                              value2: disp2 === '' ? c.value2 : displayToSecs(disp2 as number, nextUnit),
                            })
                          }}>
                          <option value="min">min</option>
                          <option value="sec">sec</option>
                        </select>
                      ) : (
                        meta.unit && <span className="rule-unit-static">{meta.unit}</span>
                      )}
                    </div>
                    {!structLocked && (
                      <button type="button" className="rule-icon-btn rule-icon-danger"
                        disabled={rule.conditions.length === 1}
                        onClick={() => removeCondition(ri, ci)} title="Remove condition">−</button>
                    )}
                  </div>
                )
              })}
              {!structLocked && (
                <button type="button" className="rule-add-cond" onClick={() => addCondition(ri)}>
                  + Add condition
                </button>
              )}
            </div>

            {/* THEN — action */}
            <div className="rule-section">
              <div className="rule-section-label">THEN</div>
              <div className="rule-action-grid">
                <label className="rule-action-field">
                  <span>Buy side</span>
                  <select className="rule-input" value={a.side} disabled={structLocked}
                    onChange={e => patchRule(ri, { action: { ...a, side: e.target.value as RuleAction['side'] } })}>
                    <option value="yes">YES</option>
                    <option value="no">NO</option>
                    <option value="both">Both</option>
                  </select>
                </label>
                <label className="rule-action-field">
                  <span>Entry price</span>
                  <select className="rule-input" value={a.entry.type} disabled={structLocked}
                    onChange={e => patchRule(ri, {
                      action: { ...a, entry: { ...a.entry, type: e.target.value as 'limit' | 'ask' } },
                    })}>
                    <option value="limit">Limit @</option>
                    <option value="ask">Take current ask</option>
                  </select>
                </label>
                {a.entry.type === 'limit' && (
                  <label className="rule-action-field">
                    <span>Limit (¢)</span>
                    <input className="rule-input" type="number" min={1} max={99} disabled={structLocked}
                      value={a.entry.price_cents ?? ''}
                      onChange={e => patchRule(ri, {
                        action: { ...a, entry: { ...a.entry, price_cents: e.target.value === '' ? null : parseInt(e.target.value, 10) } },
                      })} />
                  </label>
                )}
                <label className="rule-action-field">
                  <span>Quantity</span>
                  <input className="rule-input" type="number" min={1} disabled={readOnly}
                    value={a.quantity}
                    onChange={e => patchRule(ri, { action: { ...a, quantity: Math.max(1, parseInt(e.target.value, 10) || 1) } })} />
                </label>
                <label className="rule-action-field">
                  <span>After fill</span>
                  <select className="rule-input" value={a.exit.type} disabled={structLocked}
                    onChange={e => patchRule(ri, {
                      action: { ...a, exit: { ...a.exit, type: e.target.value as 'hold' | 'limit_sell' } },
                    })}>
                    <option value="hold">Hold to expiration</option>
                    <option value="limit_sell">Limit sell @</option>
                  </select>
                </label>
                {a.exit.type === 'limit_sell' && (
                  <label className="rule-action-field">
                    <span>Sell (¢)</span>
                    <input className="rule-input" type="number" min={1} max={99} disabled={structLocked}
                      value={a.exit.price_cents ?? ''}
                      onChange={e => patchRule(ri, {
                        action: { ...a, exit: { ...a.exit, price_cents: e.target.value === '' ? null : parseInt(e.target.value, 10) } },
                      })} />
                  </label>
                )}
                <label className="rule-action-field">
                  <span>Stop loss (¢)</span>
                  <input className="rule-input" type="number" min={1} max={99} disabled={structLocked}
                    placeholder="off"
                    value={a.exit.stop_cents ?? ''}
                    onChange={e => patchRule(ri, {
                      action: { ...a, exit: { ...a.exit, stop_cents: e.target.value === '' ? null : parseInt(e.target.value, 10) } },
                    })} />
                </label>
              </div>
              {a.side === 'both' && (
                <label className="rule-oco">
                  <input
                    type="checkbox"
                    checked={!!a.cancel_sibling_on_fill}
                    disabled={structLocked}
                    onChange={e => patchRule(ri, { action: { ...a, cancel_sibling_on_fill: e.target.checked } })}
                  />
                  <span>
                    <strong>Cancel the other side when one fills (OCO)</strong>
                    <small>Rest both legs; the first to fill cancels the sibling. Leave off for cheap two-sided longshot fishing.</small>
                  </span>
                </label>
              )}
            </div>

            <div className="rule-summary">{ruleSummary(rule)}</div>
          </div>
        )
      })}

      {!structLocked && (
        <button type="button" className="btn rule-add-btn" onClick={addRule}>
          + Add Rule
        </button>
      )}
    </div>
  )
}
