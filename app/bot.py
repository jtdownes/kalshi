"""
Kalshi longshot bot -- main entry point.

Two threads run concurrently:
    scanner  -- every SCAN_INTERVAL_SECONDS: fetch BTC markets, log snapshots,
                            place limit buy orders within safety limits.
    monitor  -- every ORDER_CHECK_INTERVAL_SECONDS: sync resting/filled status,
                            resolve outcomes after market settlement.
"""

import asyncio
import json
import logging
import time
import threading
import urllib.request
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


def fetch_btc_price() -> float | None:
    """Fetch current BTC/USD spot price from Coinbase public API. Returns None on failure."""
    try:
        req = urllib.request.Request(
            "https://api.coinbase.com/v2/prices/BTC-USD/spot",
            headers={"User-Agent": "kalshi-bot/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        return float(data["data"]["amount"])
    except Exception as e:
        log.warning("fetch_btc_price failed: %s", e)
        return None


def _get_json(url: str, timeout: int = 3):
    req = urllib.request.Request(url, headers={"User-Agent": "kalshi-bot/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _mid(bid, ask) -> float | None:
    try:
        b, a = float(bid), float(ask)
        if b > 0 and a > 0:
            return (b + a) / 2
    except (TypeError, ValueError):
        pass
    return None


# Each constituent returns a single venue mid (or None on any failure). These are
# the venues CF Benchmarks aggregates for BRTI, so an equal-weighted average of
# whatever responds is a close, license-free proxy for the real index.
def _venue_coinbase() -> float | None:
    try:
        d = _get_json("https://api.coinbase.com/v2/prices/BTC-USD/spot")
        return float(d["data"]["amount"])
    except Exception:
        return None


def _venue_kraken() -> float | None:
    try:
        r = _get_json("https://api.kraken.com/0/public/Ticker?pair=XBTUSD")["result"]
        t = next(iter(r.values()))
        return _mid(t["b"][0], t["a"][0])
    except Exception:
        return None


def _venue_bitstamp() -> float | None:
    try:
        d = _get_json("https://www.bitstamp.net/api/v2/ticker/btcusd/")
        return _mid(d["bid"], d["ask"])
    except Exception:
        return None


def _venue_gemini() -> float | None:
    try:
        d = _get_json("https://api.gemini.com/v1/pubticker/btcusd")
        return _mid(d["bid"], d["ask"])
    except Exception:
        return None


def fetch_brti_price() -> float | None:
    """BRTI proxy: equal-weighted mid across BRTI's constituent venues.

    Not the licensed CF Benchmarks BRTI fixing, but a close keyless approximation
    of the index Kalshi settles crypto markets on. Averages whatever venues
    respond; returns None only if all of them fail.
    """
    prices = [v for v in (
        _venue_coinbase(),
        _venue_kraken(),
        _venue_bitstamp(),
        _venue_gemini(),
    ) if v is not None]
    if not prices:
        log.warning("fetch_brti_price failed: no venues responded")
        return None
    return round(sum(prices) / len(prices), 2)


def fetch_kraken_price() -> float | None:
    """Kraken BTC/USD mid — a single BRTI constituent, recorded as a second
    venue line alongside Coinbase so the venue basis is visible on the chart."""
    price = _venue_kraken()
    if price is None:
        log.warning("fetch_kraken_price failed")
        return None
    return round(price, 2)


def fetch_bitstamp_price() -> float | None:
    """Bitstamp BTC/USD mid — another BRTI constituent, recorded as a third
    venue line so the inter-venue basis is visible on the chart."""
    price = _venue_bitstamp()
    if price is None:
        log.warning("fetch_bitstamp_price failed")
        return None
    return round(price, 2)


def dollars_to_cents(v) -> float | None:
    """Kalshi returns prices as strings like '0.3000' (USD). Convert to cents with 0.1c precision."""
    if v is None or v == "":
        return None
    try:
        return round(float(v) * 100, 1)
    except (TypeError, ValueError):
        return None


def fp_to_float(v) -> float:
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def close_ts_to_int(raw) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str):
        if raw.isdigit():
            return int(raw)
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return int(dt.timestamp())
        except ValueError:
            return None
    return None


def seconds_until(ts: int) -> int:
    return max(0, ts - int(time.time()))


def scan_loop(client: KalshiClient):
    log.info("Scanner started (1s tick, iterates all active profiles)")
    while True:
        try:
            active_profiles = db.get_active_profiles()
            for profile in active_profiles:
                _scan(client, profile)
        except Exception:
            log.exception("Unhandled error in scanner")
        time.sleep(1)


def market_data_loop(client: KalshiClient):
    log.info("Market data collector started  (interval=%ds)", config.SNAPSHOT_INTERVAL_SECONDS)
    while True:
        try:
            _collect_market_snapshots(client)
        except Exception:
            log.exception("Unhandled error in market data collector")
        time.sleep(config.SNAPSHOT_INTERVAL_SECONDS)


def _place_limit_sell_exit(client: KalshiClient, entry_order: dict):
    target_cents = entry_order.get("exit_target_cents")
    if target_cents is None:
        log.warning("Limit sell skipped for %s: no exit target saved", entry_order["market_ticker"])
        return

    current_entry = db.get_order_by_kalshi_order_id(entry_order["kalshi_order_id"]) or entry_order
    if current_entry.get("exit_order_kalshi_id"):
        return

    exit_client_oid = str(uuid.uuid4())
    close_ts = close_ts_to_int(entry_order.get("market_close_time"))
    time_to_close = seconds_until(close_ts) if close_ts else None
    resp = client.place_order(
        entry_order["market_ticker"],
        entry_order["side"],
        target_cents,
        exit_client_oid,
        count=entry_order.get("count") or 1,
        action="sell",
    )
    exit_order_id = resp.get("order", {}).get("order_id")

    db.save_order(
        client_order_id=exit_client_oid,
        market_ticker=entry_order["market_ticker"],
        side=entry_order["side"],
        entry_price_cents=target_cents,
        kalshi_order_id=exit_order_id,
        market_close_time=entry_order.get("market_close_time"),
        time_to_close_seconds=time_to_close,
        profile_id=entry_order.get("profile_id"),
        order_role="exit",
        parent_kalshi_order_id=entry_order["kalshi_order_id"],
        exit_strategy=entry_order.get("exit_strategy") or "limit_sell",
        exit_target_cents=target_cents,
    )
    db.update_order(entry_order["kalshi_order_id"], exit_order_kalshi_id=exit_order_id)

    log.info(
        "EXIT SET %-6s %-50s  %d¢  parent=%s  id=%s",
        entry_order["side"],
        entry_order["market_ticker"],
        target_cents,
        entry_order["kalshi_order_id"],
        exit_order_id,
    )


def _cancel_sibling_legs(client: KalshiClient, order: dict):
    """
    OCO: when one entry leg of a rule fills, cancel the other resting legs from
    the same rule on the same market so we don't double-fill (e.g. a "Both"
    rule that rested YES and NO).
    """
    siblings = db.get_sibling_resting_entries(
        order["market_ticker"],
        order.get("entry_rule_id"),
        order.get("kalshi_order_id"),
        profile_id=order.get("profile_id"),
    )
    for sib in siblings:
        sib_oid = sib.get("kalshi_order_id")
        if not sib_oid:
            continue
        try:
            client.cancel_order(sib_oid)
        except KalshiError as e:
            # Likely already filled/canceled in a race — record best-effort.
            log.warning("OCO cancel failed for %s %s: %s",
                        sib.get("side"), order["market_ticker"], e)
        db.update_order(sib_oid, status="canceled")
        log.info("OCO CANCEL %-6s %-50s  (sibling of filled %s)",
                 sib.get("side"), order["market_ticker"], order["side"])


def _handle_filled_order(client: KalshiClient, order: dict, filled_at: str = None):
    filled_at = filled_at or datetime.utcnow().isoformat()
    db.update_order(order["kalshi_order_id"], status="filled", filled_at=filled_at)

    if order.get("order_role") == "exit":
        db.close_entry_order_with_exit(
            order["parent_kalshi_order_id"],
            order["entry_price_cents"],
            closed_at=filled_at,
        )
        log.info(
            "EXIT HIT %-6s %-50s  %d¢",
            order["side"],
            order["market_ticker"],
            order["entry_price_cents"],
        )
        return

    log.info(
        "FILLED   %-6s %-50s  %d¢",
        order["side"],
        order["market_ticker"],
        order["entry_price_cents"],
    )

    if order.get("cancel_sibling_on_fill"):
        _cancel_sibling_legs(client, order)

    if order.get("exit_strategy") != "limit_sell":
        return

    try:
        _place_limit_sell_exit(client, order)
    except KalshiError as e:
        log.error(
            "limit sell placement failed on %s %s: %s",
            order["side"],
            order["market_ticker"],
            e,
        )


def _scan(client: KalshiClient, settings: dict):
    now_ts    = int(time.time())
    max_close = now_ts + config.LOOK_AHEAD_SECONDS
    series_list = settings.get("btc_series_tickers", config.BTC_SERIES_TICKERS)
    if not series_list:
        series_list = config.SNAPSHOT_SERIES_TICKERS

    profile_id = settings.get("id")
    min_secs = config.MIN_SECONDS_TO_CLOSE
    markets = db.get_latest_snapshots_for_series([s for s in series_list if s], max_age_seconds=15)

    for market in markets:
        ticker = market.get("ticker", "")
        close_ts = close_ts_to_int(market.get("close_time"))
        if not close_ts or close_ts > max_close:
            continue

        time_to_close = seconds_until(close_ts)
        if time_to_close < min_secs:
            continue

        yes_ask = market.get("yes_ask")
        no_ask = market.get("no_ask")

        for spec in evaluate_market(market, settings, profile_id=profile_id,
                                    time_to_close=time_to_close):
            side       = spec["side"]
            price_cents = spec["price_cents"]
            quantity   = spec["quantity"]
            exit_spec  = spec["exit"]
            rule_id    = spec["rule_id"]

            ok, reason = can_place_order(price_cents, settings, profile_id=profile_id,
                                         quantity=quantity)
            if not ok:
                log.warning("Order skipped (%s): %s %s", reason, side, ticker)
                continue

            if exit_spec.get("type") == "limit_sell":
                exit_strategy = "limit_sell"
                exit_target_cents = exit_spec.get("price_cents")
            else:
                exit_strategy = "hold_to_expiration"
                exit_target_cents = None

            client_oid = str(uuid.uuid4())
            try:
                resp = client.place_order(ticker, side, price_cents, client_oid, count=quantity)
                kalshi_oid = resp.get("order", {}).get("order_id")
                log.info("ORDER PLACED  %-6s %-50s  %d\u00a2 x%d  ttc=%ds  rule=%s  id=%s",
                         side, ticker, price_cents, quantity, time_to_close,
                         rule_id, kalshi_oid)
                db.save_order(
                    client_order_id=client_oid, market_ticker=ticker,
                    side=side, entry_price_cents=price_cents,
                    kalshi_order_id=kalshi_oid, btc_price=None,
                    distance_to_strike=None, market_close_time=str(close_ts),
                    time_to_close_seconds=time_to_close,
                    profile_id=profile_id, count=quantity,
                    entry_rule_id=rule_id,
                    cancel_sibling_on_fill=spec.get("oco", False),
                    exit_strategy=exit_strategy,
                    exit_target_cents=exit_target_cents,
                )
            except KalshiError as e:
                log.error("place_order failed on %s %s: %s", side, ticker, e)


def _collect_market_snapshots(client: KalshiClient):
    now_ts = int(time.time())
    max_close = now_ts + config.LOOK_AHEAD_SECONDS
    btc_price = fetch_btc_price()
    brti_price = fetch_brti_price()
    kraken_price = fetch_kraken_price()
    bitstamp_price = fetch_bitstamp_price()

    for series in config.SNAPSHOT_SERIES_TICKERS:
        try:
            data = client.get_markets(status="open", max_close_ts=max_close, limit=200, series_ticker=series)
        except KalshiError as e:
            log.error("snapshot get_markets failed for %s: %s", series, e)
            continue

        for market in data.get("markets", []):
            ticker = market.get("ticker", "")
            close_ts = close_ts_to_int(market.get("close_time") or market.get("expiration_time"))
            if not ticker or not close_ts:
                continue

            time_to_close = seconds_until(close_ts)
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

            strike = market.get("floor_strike")
            db.save_market_snapshot(
                ticker=ticker,
                title=market.get("title", ""),
                close_time=str(close_ts),
                yes_ask=yes_ask,
                yes_bid=yes_bid,
                no_ask=no_ask,
                no_bid=no_bid,
                btc_price=btc_price,
                brti_price=brti_price,
                kraken_price=kraken_price,
                bitstamp_price=bitstamp_price,
                time_to_close_secs=time_to_close,
                strike_str=str(strike) if strike is not None else None,
                volume=volume,
                open_interest=oi,
            )


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
        filled_ids = {
            f.get("order_id") for f in client.get_fills(limit=200).get("fills", [])
            if f.get("order_id")
        }
    except KalshiError as e:
        log.warning("get_fills failed; falling back to order status only: %s", e)
        filled_ids = set()

    # Look up each resting order individually — bulk-fetching all filled/canceled
    # orders is unreliable due to pagination and sort order.
    # Kalshi uses status="executed" for filled orders (not "filled").
    for order in resting:
        oid = order.get("kalshi_order_id")
        if not oid:
            continue
        try:
            remote = client.get_order(oid).get("order", {})
            remote_status = remote.get("status", "").lower()
            fill_count = fp_to_float(remote.get("fill_count_fp"))
            if oid in filled_ids or fill_count > 0 or remote_status in ("executed", "filled"):
                _handle_filled_order(client, order)
            elif remote_status in ("canceled", "cancelled", "expired"):
                db.update_order(oid, status="canceled")
                log.info("CANCELED %-6s %-50s",
                         order["side"], order["market_ticker"])
        except KalshiError as e:
            log.debug("sync check failed for %s: %s", oid, e)


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


async def _ws_fills_async(client: KalshiClient):
    """Connect to the Kalshi WebSocket fill channel and update order status in real-time."""
    import websockets

    RECONNECT_DELAYS = [5, 10, 30, 60, 120]
    attempt = 0

    while True:
        delay = RECONNECT_DELAYS[min(attempt, len(RECONNECT_DELAYS) - 1)]
        try:
            headers = client.ws_auth_headers()
            async with websockets.connect(
                config.KALSHI_WS_URL,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=30,
            ) as ws:
                log.info("WS connected  channel=fill")
                attempt = 0  # reset on successful connect

                await ws.send(json.dumps({
                    "id": 1,
                    "cmd": "subscribe",
                    "params": {"channels": ["fill", "user_orders"]},
                }))

                _user_orders_logged = 0  # log first few raw to learn the schema

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    msg_type = msg.get("type")
                    data = msg.get("msg", {})

                    if msg_type == "fill":
                        order_id = data.get("order_id")
                        if order_id:
                            order = db.get_order_by_kalshi_order_id(order_id)
                            if order:
                                _handle_filled_order(client, order)
                            else:
                                db.update_order(order_id, status="filled",
                                                filled_at=datetime.utcnow().isoformat())
                            log.info("WS FILL  order_id=%s  ticker=%s  side=%s",
                                     order_id,
                                     data.get("ticker") or data.get("market_ticker", "?"),
                                     data.get("side", "?"))
                    elif msg_type == "user_orders":
                        if _user_orders_logged < 5:
                            log.info("WS user_orders raw: %s", raw[:500])
                            _user_orders_logged += 1
                        order_id = data.get("order_id")
                        status = (data.get("status") or "").lower()
                        if order_id and status in ("canceled", "cancelled", "expired"):
                            db.update_order(order_id, status="canceled")
                            log.info("WS CANCEL order_id=%s  ticker=%s",
                                     order_id,
                                     data.get("ticker") or data.get("market_ticker", "?"))
                    elif msg_type == "error":
                        log.warning("WS error from server: %s", msg)

        except Exception as e:
            attempt += 1
            log.warning("WS disconnected (%s), reconnecting in %ds (attempt %d)",
                        e, delay, attempt)
            await asyncio.sleep(delay)


def ws_fills_thread(client: KalshiClient):
    """Run the async WebSocket fill listener in its own event loop (daemonised thread)."""
    asyncio.run(_ws_fills_async(client))


def main():
    log.info("Kalshi Longshot Bot")
    log.info("API base       : %s", config.KALSHI_API_BASE)
    log.info("Proactive mode : %s", config.PROACTIVE_MODE)
    log.info("Entry range    : %d-%d\u00a2", config.MIN_ENTRY_CENTS, config.MAX_ENTRY_CENTS)
    log.info("Daily limit    : %d\u00a2 ($%.2f)", config.MAX_DAILY_SPEND_CENTS,
             config.MAX_DAILY_SPEND_CENTS / 100)
    log.info("Max open orders: %d", config.MAX_OPEN_ORDERS)
    log.info("BTC series     : %s", config.BTC_SERIES_TICKERS or "auto-detect")
    log.info("Snapshot series: %s", config.SNAPSHOT_SERIES_TICKERS or "none")
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

    market_data = threading.Thread(target=market_data_loop, args=(client,), daemon=True, name="market-data")
    scanner = threading.Thread(target=scan_loop, args=(client,), daemon=True, name="scanner")
    monitor = threading.Thread(target=order_monitor_loop, args=(client,), daemon=True, name="monitor")
    ws_fills = threading.Thread(target=ws_fills_thread, args=(client,), daemon=True, name="ws-fills")
    market_data.start()
    scanner.start()
    monitor.start()
    ws_fills.start()

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log.info("Shutting down.")


if __name__ == "__main__":
    main()
