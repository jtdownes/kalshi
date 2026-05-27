"""
Kalshi longshot bot -- main entry point.

Two threads run concurrently:
  scanner  -- every SCAN_INTERVAL_SECONDS: fetch BTC markets, log snapshots,
              place limit buy orders within safety limits.
  monitor  -- every ORDER_CHECK_INTERVAL_SECONDS: sync resting/filled status,
              resolve outcomes after market settlement.
"""

import logging
import time
import threading
import uuid
from datetime import datetime, timezone

import config
import database as db
from kalshi_client import KalshiClient, KalshiError
from strategy import evaluate_market, can_place_order

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)-12s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("bot")


def dollars_to_cents(v) -> int | None:
    """Kalshi returns prices as strings like '0.3000' (USD). Convert to int cents."""
    if v is None or v == "":
        return None
    try:
        return round(float(v) * 100)
    except (TypeError, ValueError):
        return None


def close_ts_to_int(raw) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return int(dt.timestamp())
        except ValueError:
            return None
    return None


def seconds_until(ts: int) -> int:
    return max(0, ts - int(time.time()))


def scan_loop(client: KalshiClient):
    log.info("Scanner started  (interval=%ds, proactive=%s)",
             config.SCAN_INTERVAL_SECONDS, config.PROACTIVE_MODE)
    while True:
        try:
            _scan(client)
        except Exception:
            log.exception("Unhandled error in scanner")
        time.sleep(config.SCAN_INTERVAL_SECONDS)


def _scan(client: KalshiClient):
    now_ts    = int(time.time())
    max_close = now_ts + config.LOOK_AHEAD_SECONDS
    series_list = config.BTC_SERIES_TICKERS if config.BTC_SERIES_TICKERS else [None]

    for series in series_list:
        params = {"status": "open", "max_close_ts": max_close, "limit": 200}
        if series:
            params["series_ticker"] = series
        try:
            data = client.get_markets(**params)
        except KalshiError as e:
            log.error("get_markets failed: %s", e)
            continue

        for market in data.get("markets", []):
            ticker = market.get("ticker", "")
            if not series and "BTC" not in ticker.upper():
                if "bitcoin" not in market.get("title", "").lower():
                    continue

            close_ts = close_ts_to_int(
                market.get("close_time") or market.get("expiration_time")
            )
            if not close_ts:
                continue
            time_to_close = seconds_until(close_ts)
            if time_to_close < config.MIN_SECONDS_TO_CLOSE:
                continue

            yes_ask = dollars_to_cents(market.get("yes_ask_dollars"))
            yes_bid = dollars_to_cents(market.get("yes_bid_dollars"))
            no_ask  = dollars_to_cents(market.get("no_ask_dollars"))
            no_bid  = dollars_to_cents(market.get("no_bid_dollars"))

            try:
                volume = int(float(market.get("volume_fp") or 0))
            except (TypeError, ValueError):
                volume = None
            try:
                oi = int(float(market.get("open_interest_fp") or 0))
            except (TypeError, ValueError):
                oi = None

            # Floor strike = the BTC price the up/down market opened against
            strike = market.get("floor_strike")

            db.save_market_snapshot(
                ticker=ticker, title=market.get("title", ""),
                close_time=str(close_ts),
                yes_ask=yes_ask, yes_bid=yes_bid,
                no_ask=no_ask,   no_bid=no_bid,
                btc_price=None, time_to_close_secs=time_to_close,
                strike_str=str(strike) if strike is not None else None,
                volume=volume, open_interest=oi,
            )

            # Inject normalised prices for strategy logic
            market["yes_ask"] = yes_ask
            market["yes_bid"] = yes_bid
            market["no_ask"]  = no_ask
            market["no_bid"]  = no_bid

            for side, price_cents in evaluate_market(market, None):
                ok, reason = can_place_order(price_cents)
                if not ok:
                    log.warning("Order skipped (%s): %s %s", reason, side, ticker)
                    continue
                client_oid = str(uuid.uuid4())
                try:
                    resp = client.place_order(ticker, side, price_cents, client_oid)
                    kalshi_oid = resp.get("order", {}).get("order_id")
                    log.info("ORDER PLACED  %-6s %-50s  %d\u00a2  ttc=%ds  yes_ask=%s\u00a2  no_ask=%s\u00a2  id=%s",
                             side, ticker, price_cents, time_to_close,
                             yes_ask, no_ask, kalshi_oid)
                    db.save_order(
                        client_order_id=client_oid, market_ticker=ticker,
                        side=side, entry_price_cents=price_cents,
                        kalshi_order_id=kalshi_oid, btc_price=None,
                        distance_to_strike=None, market_close_time=str(close_ts),
                        time_to_close_seconds=time_to_close,
                    )
                except KalshiError as e:
                    log.error("place_order failed on %s %s: %s", side, ticker, e)


def order_monitor_loop(client: KalshiClient):
    log.info("Monitor started  (interval=%ds)", config.ORDER_CHECK_INTERVAL_SECONDS)
    time.sleep(10)
    while True:
        try:
            _sync_order_statuses(client)
            _resolve_outcomes(client)
        except Exception:
            log.exception("Unhandled error in monitor")
        time.sleep(config.ORDER_CHECK_INTERVAL_SECONDS)


def _sync_order_statuses(client: KalshiClient):
    resting = db.get_resting_orders()
    if not resting:
        return
    try:
        filled_ids   = {o["order_id"] for o in client.get_orders(status="filled").get("orders", [])}
        canceled_ids = {o["order_id"] for o in client.get_orders(status="canceled").get("orders", [])}
    except KalshiError as e:
        log.error("get_orders failed: %s", e)
        return

    for order in resting:
        oid = order.get("kalshi_order_id")
        if not oid:
            continue
        if oid in filled_ids:
            db.update_order(oid, status="filled",
                            filled_at=datetime.utcnow().isoformat())
            log.info("FILLED  %-6s %-50s  %d\u00a2",
                     order["side"], order["market_ticker"],
                     order["entry_price_cents"])
        elif oid in canceled_ids:
            db.update_order(oid, status="canceled")


def _resolve_outcomes(client: KalshiClient):
    pending = db.get_filled_without_outcome()
    if not pending:
        return
    now_ts = int(time.time())
    for order in pending:
        close_ts = close_ts_to_int(order.get("market_close_time"))
        if close_ts and close_ts > now_ts:
            continue
        ticker = order["market_ticker"]
        try:
            mkt    = client.get_market(ticker).get("market", {})
            result = mkt.get("result")
            if result not in ("yes", "no"):
                continue
            side    = order["side"]
            outcome = "win" if result == side else "loss"
            payout  = 100 if outcome == "win" else 0
            net     = payout - order["entry_price_cents"]
            db.update_order(order["kalshi_order_id"],
                            outcome=outcome, payout_cents=payout, net_profit_cents=net)
            log.info("OUTCOME  %-4s  %-50s  %s  net=%+d\u00a2",
                     side, ticker, outcome.upper(), net)
        except KalshiError as e:
            log.debug("outcome check failed for %s: %s", ticker, e)


def main():
    log.info("=" * 60)
    log.info("Kalshi Longshot Bot")
    log.info("API base       : %s", config.KALSHI_API_BASE)
    log.info("Proactive mode : %s", config.PROACTIVE_MODE)
    log.info("Entry range    : %d-%d\u00a2", config.MIN_ENTRY_CENTS, config.MAX_ENTRY_CENTS)
    log.info("Daily limit    : %d\u00a2 ($%.2f)", config.MAX_DAILY_SPEND_CENTS,
             config.MAX_DAILY_SPEND_CENTS / 100)
    log.info("Max open orders: %d", config.MAX_OPEN_ORDERS)
    log.info("BTC series     : %s", config.BTC_SERIES_TICKERS or "auto-detect")
    log.info("=" * 60)

    db.init_db()
    client = KalshiClient()

    try:
        bal_data = client.get_balance()
        balance  = bal_data.get("balance", bal_data)
        log.info("API connected  balance=%s cents", balance)
    except Exception as e:
        log.critical("Cannot connect to Kalshi API: %s", e)
        raise SystemExit(1)

    scanner = threading.Thread(target=scan_loop, args=(client,), daemon=True, name="scanner")
    monitor = threading.Thread(target=order_monitor_loop, args=(client,), daemon=True, name="monitor")
    scanner.start()
    monitor.start()

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log.info("Shutting down.")


if __name__ == "__main__":
    main()
