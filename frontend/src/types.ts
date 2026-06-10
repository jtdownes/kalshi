// ── Domain model types ────────────────────────────────────────────────────────

export interface Position {
  ticker: string
  position_fp: string
  total_traded_dollars: string
  market_exposure_dollars: string
  realized_pnl_dollars: string
  fees_paid_dollars: string
  last_updated_ts: string
}

export interface Order {
  id: number
  kalshi_order_id: string | null
  market_ticker: string
  side: string
  order_role: string
  entry_price_cents: number
  count: number
  status: string
  placed_at: string
  filled_at: string | null
  market_close_time: string | null
  time_to_close_at_placement: number | null
  outcome: string | null
  payout_cents: number | null
  net_profit_cents: number | null
}

export interface Trade {
  market_ticker: string
  order_count: number
  closed_order_count: number
  total_count: number
  placed_at: string
  filled_at: string | null
  first_entry_filled_at: string | null
  last_entry_filled_at: string | null
  closed_at: string | null
  market_close_time: string | null
  entry_price_cents: number | null
  total_entry_cost_cents: number
  total_close_proceeds_cents: number
  net_profit_cents: number | null
  status: string
  outcome: string | null
  peak_price_cents: number | null
  peak_time: string | null
}

export interface Snapshot {
  id: number
  ticker: string
  title: string
  scanned_at: string
  close_time: string | null
  yes_ask: number | null
  yes_bid: number | null
  no_ask: number | null
  no_bid: number | null
  time_to_close_secs: number | null
  strike_str: string | null
  btc_price: number | null
  brti_price: number | null
  coinbase_price: number | null
  kraken_price: number | null
  bitstamp_price: number | null
  gemini_price: number | null
  eth_price: number | null
  volume: number | null
  open_interest: number | null
}

// ── Strategy / rule model ─────────────────────────────────────────────────────

export type RuleField =
  | 'time_to_close' | 'distance_to_strike'
  | 'yes_ask' | 'yes_bid' | 'no_ask' | 'no_bid'
  | 'btc_price' | 'spread' | 'volume' | 'open_interest'
  | 'prior_resolution' | 'prev2_resolution'
  | 'btc_volatility' | 'btc_range' | 'btc_drift'
  | 'strike_crossings' | 'buffer_ratio'
export type RuleOp = 'lt' | 'lte' | 'gt' | 'gte' | 'eq' | 'between'

export interface RuleCondition {
  field: RuleField
  op: RuleOp
  value: number | null
  value2?: number | null
}
export interface RuleEntry {
  type: 'limit' | 'ask' | 'ask_minus' | 'ask_minus_pct'
  price_cents?: number | null    // limit
  offset_cents?: number | null   // ask_minus: rest N¢ below the current ask
  offset_pct?: number | null     // ask_minus_pct: rest N% below the current ask
}
export interface ScaleOutLeg { qty: number | null; price_cents: number | null }
export interface RuleExit {
  type: 'hold' | 'limit_sell' | 'scale_out'
  price_cents?: number | null      // limit_sell
  legs?: ScaleOutLeg[]             // scale_out ladder (sell qty @ price, ...)
  stop_cents?: number | null       // stop at an absolute price, or:
  stop_pct?: number | null         // stop at N% below the entry price
  time_exit_secs?: number | null   // market-out remainder at N secs to close
}
export interface RuleAction {
  side: 'yes' | 'no' | 'both'
  entry: RuleEntry
  quantity: number
  exit: RuleExit
  cancel_sibling_on_fill?: boolean
}
export interface StrategyRule {
  id: string
  name?: string
  enabled: boolean
  conditions: RuleCondition[]
  action: RuleAction
}

// ── Settings / profile model ──────────────────────────────────────────────────

export interface Settings {
  min_entry_cents: number
  max_entry_cents: number
  proactive_mode: boolean
  max_open_orders: number
  max_daily_spend_cents: number
  btc_series_tickers: string[]
  exit_strategy: 'hold_to_expiration' | 'limit_sell'
  limit_sell_price_cents: number | null
  min_time_to_close_secs: number | null
  max_time_to_close_secs: number | null
  active_profile_id: number | null
  rules: StrategyRule[] | null
  name?: string
}

export interface Profile {
  id: number
  name: string
  created_at: string
  is_active: boolean
  min_entry_cents: number
  max_entry_cents: number
  proactive_mode: boolean
  max_open_orders: number
  max_daily_spend_cents: number
  btc_series_tickers: string
  exit_strategy: 'hold_to_expiration' | 'limit_sell'
  limit_sell_price_cents: number | null
  min_time_to_close_secs: number | null
  max_time_to_close_secs: number | null
  rules: StrategyRule[] | null
  order_count: number
  win_count: number
  loss_count: number
  total_spend_cents: number
  total_profit_cents: number
}

export type Quotes = Record<string, {
  yes_ask: number | null
  no_ask: number | null
  yes_bid: number | null
  no_bid: number | null
  open_interest: number | null
}>
