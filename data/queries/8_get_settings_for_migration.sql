SELECT min_entry_cents, max_entry_cents, proactive_mode, max_open_orders,
       max_daily_spend_cents, btc_series_tickers,
       exit_strategy, limit_sell_price_cents
FROM settings
WHERE id = 1;
