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
import crypto_assets
import database as db
import weather
from kalshi_client import KalshiClient, KalshiError
from strategy import evaluate_market, can_place_order

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)-12s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("bot")


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


# Each constituent returns (price, 24h_volume) or None on failure. These are
# the venues CF Benchmarks aggregates for its real-time indices (BRTI etc.), so
# an equal-weighted average of whatever responds is a close, license-free proxy
# for the real index. Volume is the venue's trailing-24h volume in the asset —
# a weight for volume-weighted blending. Venue symbols come from the asset
# registry in crypto_assets.py, so new assets need no new fetchers.
def _venue_coinbase(product: str) -> tuple[float, float | None] | None:
    try:
        d = _get_json(f"https://api.coinbase.com/v2/prices/{product}/spot")
        price = float(d["data"]["amount"])
    except Exception:
        return None
    vol = None
    try:
        s = _get_json(f"https://api.exchange.coinbase.com/products/{product}/stats")
        vol = float(s["volume"])
    except Exception:
        pass
    return (price, vol)


def _venue_kraken(pair: str) -> tuple[float, float | None] | None:
    try:
        r = _get_json(f"https://api.kraken.com/0/public/Ticker?pair={pair}")["result"]
        t = next(iter(r.values()))
        price = _mid(t["b"][0], t["a"][0])
        if price is None:
            return None
        return (price, float(t["v"][1]))  # v[1] = trailing 24h volume
    except Exception:
        return None


def _venue_bitstamp(pair: str) -> tuple[float, float | None] | None:
    try:
        d = _get_json(f"https://www.bitstamp.net/api/v2/ticker/{pair}/")
        price = _mid(d["bid"], d["ask"])
        if price is None:
            return None
        return (price, float(d["volume"]))  # 24h volume in the asset
    except Exception:
        return None


def _venue_gemini(pair: str, volume_key: str) -> tuple[float, float | None] | None:
    try:
        d = _get_json(f"https://api.gemini.com/v1/pubticker/{pair}")
        price = _mid(d["bid"], d["ask"])
        if price is None:
            return None
        return (price, float(d["volume"][volume_key]))  # 24h volume in the asset
    except Exception:
        return None


def fetch_crypto_prices(asset: str) -> dict:
    """Fetch one asset's USD price from all four venues, returning per-venue
    price + volume and the equal-weighted consolidated mid across whatever
    responded. One call per venue — no redundant fetches.

    Note: the consolidated mid is NOT the licensed CF Benchmarks fixing, just a
    close keyless approximation. Volumes are captured so the blend can later be
    made volume-weighted to better track the real index.
    """
    cfg = crypto_assets.CRYPTO_ASSETS[asset]
    venues = {
        "coinbase": _venue_coinbase(cfg["coinbase_product"]),
        "kraken":   _venue_kraken(cfg["kraken_pair"]),
        "bitstamp": _venue_bitstamp(cfg["bitstamp_pair"]),
        "gemini":   _venue_gemini(cfg["gemini_pair"], cfg["gemini_volume_key"]),
    }
    prices = [v[0] for v in venues.values() if v is not None]
    consolidated = round(sum(prices) / len(prices), 2) if prices else None
    if consolidated is None:
        log.warning("fetch_crypto_prices(%s): no venues responded", asset)

    def price_of(v):  return round(v[0], 2) if v is not None else None
    def volume_of(v): return round(v[1], 4) if (v is not None and v[1] is not None) else None

    return {
        "coinbase_price":  price_of(venues["coinbase"]),
        "kraken_price":    price_of(venues["kraken"]),
        "bitstamp_price":  price_of(venues["bitstamp"]),
        "gemini_price":    price_of(venues["gemini"]),
        "coinbase_volume": volume_of(venues["coinbase"]),
        "kraken_volume":   volume_of(venues["kraken"]),
        "bitstamp_volume": volume_of(venues["bitstamp"]),
        "gemini_volume":   volume_of(venues["gemini"]),
        "consolidated_price": consolidated,
    }


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
            _check_stop_losses(client)
            _check_time_exits(client)
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


def weather_loop():
    """Poll NWS CLI products for the official observed daily high (settlement
    source for KXHIGH<city> markets) and store a row whenever the report changes."""
    if not config.WEATHER_STATIONS:
        log.info("Weather collector idle (no WEATHER_STATIONS configured)")
        return
    log.info("Weather collector started  (interval=%ds, stations=%s)",
             config.WEATHER_INTERVAL_SECONDS, config.WEATHER_STATIONS)
    while True:
        for site, station in config.WEATHER_STATIONS:
            try:
                obs = weather.fetch_cli(site, station)
                if obs.get("max_temp_f") is None and obs.get("obs_date") is None:
                    log.warning("weather %s/%s: unparseable report", site, station)
                    continue
                # Dedup: only store when the report actually changed.
                last = db.get_latest_weather_snapshot(obs["station"])
                if last and (last["obs_date"], last["max_temp_f"], last["min_temp_f"],
                             last["issued"]) == (obs["obs_date"], obs["max_temp_f"],
                                                 obs["min_temp_f"], obs["issued"]):
                    continue
                db.save_weather_snapshot(
                    station=obs["station"], scanned_at=datetime.utcnow().isoformat(),
                    obs_date=obs["obs_date"], max_temp_f=obs["max_temp_f"],
                    min_temp_f=obs["min_temp_f"], precip_in=obs["precip_in"],
                    issued=obs["issued"], raw_excerpt=obs["raw_excerpt"],
                    source_url=obs.get("url"))
                log.info("WEATHER  %s  %s  high=%s°F low=%s°F",
                         obs["station"], obs["obs_date"], obs["max_temp_f"], obs["min_temp_f"])
            except Exception as e:
                log.error("weather fetch failed for %s/%s: %s", site, station, e)
        time.sleep(config.WEATHER_INTERVAL_SECONDS)


def _clean_scale_out_legs(legs, quantity: int) -> list[dict] | None:
    """Validate a scale-out ladder: each leg needs a qty and a 1-99¢ price, and
    the ladder may not sell more than the entry buys. Returns clean legs or None."""
    if not isinstance(legs, list) or not legs:
        return None
    clean, total = [], 0
    for leg in legs:
        try:
            qty   = int(leg.get("qty"))
            price = int(leg.get("price_cents"))
        except (TypeError, ValueError, AttributeError):
            return None
        if qty < 1 or not (1 <= price <= 99):
            return None
        if total + qty > quantity:
            qty = quantity - total       # truncate the last rung to fit
            if qty < 1:
                break
        clean.append({"qty": qty, "price_cents": price})
        total += qty
    return clean or None


def _place_scale_out_exits(client: KalshiClient, entry_order: dict):
    """Entry filled with a scale-out exit: rest one sell order per ladder rung.
    Any quantity the ladder doesn't cover simply holds to expiration."""
    legs = entry_order.get("exit_legs")
    if isinstance(legs, str):
        try:
            legs = json.loads(legs)
        except json.JSONDecodeError:
            legs = None
    legs = _clean_scale_out_legs(legs, entry_order.get("count") or 1)
    if not legs:
        log.warning("Scale-out skipped for %s: no valid legs saved",
                    entry_order["market_ticker"])
        return

    current = db.get_order_by_kalshi_order_id(entry_order["kalshi_order_id"]) or entry_order
    if current.get("exit_order_kalshi_id"):
        return

    close_ts = close_ts_to_int(entry_order.get("market_close_time"))
    time_to_close = seconds_until(close_ts) if close_ts else None
    first_leg_id = None
    for leg in legs:
        leg_oid = str(uuid.uuid4())
        try:
            resp = client.place_order(
                entry_order["market_ticker"], entry_order["side"],
                leg["price_cents"], leg_oid, count=leg["qty"], action="sell",
            )
        except KalshiError as e:
            log.error("scale-out leg failed on %s %s @%d¢: %s",
                      entry_order["side"], entry_order["market_ticker"],
                      leg["price_cents"], e)
            continue
        leg_order_id = resp.get("order", {}).get("order_id")
        first_leg_id = first_leg_id or leg_order_id
        db.save_order(
            client_order_id=leg_oid,
            market_ticker=entry_order["market_ticker"],
            side=entry_order["side"],
            entry_price_cents=leg["price_cents"],
            kalshi_order_id=leg_order_id,
            market_close_time=entry_order.get("market_close_time"),
            time_to_close_seconds=time_to_close,
            profile_id=entry_order.get("profile_id"),
            order_role="exit",
            parent_kalshi_order_id=entry_order["kalshi_order_id"],
            exit_strategy="scale_out",
            exit_target_cents=leg["price_cents"],
            count=leg["qty"],
        )
        log.info("LADDER   %-6s %-50s  sell %d @ %d¢  parent=%s",
                 entry_order["side"], entry_order["market_ticker"],
                 leg["qty"], leg["price_cents"], entry_order["kalshi_order_id"])
    if first_leg_id:
        db.update_order(entry_order["kalshi_order_id"], exit_order_kalshi_id=first_leg_id)


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


def _cancel_resting_child_exits(client: KalshiClient, parent_kalshi_order_id: str):
    """Cancel resting passive exits (limit sell / scale-out rungs) before a
    market-out, so the remainder isn't sold twice."""
    for child in db.get_resting_child_exits(parent_kalshi_order_id):
        oid = child.get("kalshi_order_id")
        if not oid:
            continue
        try:
            client.cancel_order(oid)
        except KalshiError as e:
            # Likely filled in the race — the fill monitor will account for it.
            log.warning("exit-leg cancel failed for %s: %s", oid, e)
            continue
        db.update_order(oid, status="canceled")


def _place_market_out(client: KalshiClient, entry_order: dict, sell_price: int,
                      reason: str):
    """Stop or time exit triggered: cancel any resting exit legs, then sell the
    remaining position now by crossing into the current bid. Saved as an `exit`
    order so the normal fill monitor closes the parent at the sale price;
    market_out_kalshi_id on the parent blocks re-fires."""
    sell_price = max(1, min(99, int(sell_price)))

    # Re-read under the lock-free race window: another tick may have placed it.
    current = db.get_order_by_kalshi_order_id(entry_order["kalshi_order_id"]) or entry_order
    if current.get("market_out_kalshi_id") or current.get("closed_at"):
        return

    _cancel_resting_child_exits(client, entry_order["kalshi_order_id"])

    # Remaining count re-read after cancels, in case a leg filled in the race.
    current = db.get_order_by_kalshi_order_id(entry_order["kalshi_order_id"]) or current
    remaining = (current.get("count") or 1) - (current.get("closed_count") or 0)
    if remaining < 1:
        return

    exit_oid = str(uuid.uuid4())
    try:
        resp = client.place_order(
            entry_order["market_ticker"], entry_order["side"], sell_price,
            exit_oid, count=remaining, action="sell",
        )
    except KalshiError as e:
        log.error("%s sell failed on %s %s: %s", reason,
                  entry_order["side"], entry_order["market_ticker"], e)
        return

    exit_order_id = resp.get("order", {}).get("order_id")
    db.save_order(
        client_order_id=exit_oid,
        market_ticker=entry_order["market_ticker"],
        side=entry_order["side"],
        entry_price_cents=sell_price,
        kalshi_order_id=exit_order_id,
        market_close_time=entry_order.get("market_close_time"),
        profile_id=entry_order.get("profile_id"),
        order_role="exit",
        parent_kalshi_order_id=entry_order["kalshi_order_id"],
        exit_strategy=reason,
        exit_target_cents=sell_price,
        count=remaining,
    )
    db.update_order(entry_order["kalshi_order_id"],
                    market_out_kalshi_id=exit_order_id,
                    exit_order_kalshi_id=current.get("exit_order_kalshi_id") or exit_order_id)
    log.info("%s %-6s %-50s  sell %d @ %d¢  id=%s",
             "STOP HIT" if reason == "stop_loss" else "TIME OUT",
             entry_order["side"], entry_order["market_ticker"],
             remaining, sell_price, exit_order_id)


def _check_stop_losses(client: KalshiClient):
    """Every scan tick: for each filled position carrying a stop, exit the moment
    the side's freshest bid is at/through the stop. Uses the latest snapshot bid
    (1s cadence) so this needs no extra API polling to decide."""
    positions = db.get_open_stop_orders()
    for pos in positions:
        snap = db.get_latest_snapshot_for_ticker(pos["market_ticker"])
        if not snap:
            continue
        bid = snap.get("yes_bid") if pos["side"] == "yes" else snap.get("no_bid")
        if bid is None or bid <= 0:
            continue
        if bid > pos["stop_loss_cents"]:
            continue
        _place_market_out(client, pos, round(float(bid)), "stop_loss")


def _check_time_exits(client: KalshiClient):
    """Every scan tick: market-out positions whose contract is within their
    time_exit_secs window of closing."""
    positions = db.get_open_time_exit_orders()
    for pos in positions:
        close_ts = close_ts_to_int(pos.get("market_close_time"))
        if not close_ts or seconds_until(close_ts) > pos["time_exit_secs"]:
            continue
        snap = db.get_latest_snapshot_for_ticker(pos["market_ticker"])
        if not snap:
            continue
        bid = snap.get("yes_bid") if pos["side"] == "yes" else snap.get("no_bid")
        if bid is None or bid <= 0:
            continue   # no bid to hit; retry next tick until close
        _place_market_out(client, pos, round(float(bid)), "time_exit")


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
        reason = order.get("exit_strategy") or "limit_sell"
        if reason not in ("stop_loss", "time_exit", "scale_out"):
            reason = "limit_sell"
        db.apply_exit_fill(
            order["parent_kalshi_order_id"],
            order.get("count") or 1,
            order["entry_price_cents"],
            closed_at=filled_at,
            close_reason=reason,
        )
        labels = {"stop_loss": "STOP OUT", "time_exit": "TIME OUT",
                  "scale_out": "RUNG HIT"}
        log.info(
            "%s %-6s %-50s  %d¢ x%d",
            labels.get(reason, "EXIT HIT"),
            order["side"],
            order["market_ticker"],
            order["entry_price_cents"],
            order.get("count") or 1,
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

    exit_strategy = order.get("exit_strategy")
    if exit_strategy == "scale_out":
        _place_scale_out_exits(client, order)
    elif exit_strategy == "limit_sell":
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

            exit_legs = None
            if exit_spec.get("type") == "limit_sell":
                exit_strategy = "limit_sell"
                exit_target_cents = exit_spec.get("price_cents")
            elif exit_spec.get("type") == "scale_out":
                exit_strategy = "scale_out"
                exit_target_cents = None
                exit_legs = _clean_scale_out_legs(exit_spec.get("legs"), quantity)
                if not exit_legs:
                    log.warning("Order skipped (scale-out rule has no valid legs): %s %s",
                                side, ticker)
                    continue
            else:
                exit_strategy = "hold_to_expiration"
                exit_target_cents = None

            # Optional stop-loss (independent of the passive exit): the bot
            # market-sells the remainder when the side's bid trades at/through
            # this level. Absolute cents wins; otherwise a % stop is resolved
            # against this order's entry price right here, so downstream
            # machinery only ever sees cents.
            stop_loss_cents = exit_spec.get("stop_cents")
            try:
                stop_loss_cents = int(stop_loss_cents) if stop_loss_cents not in (None, "") else None
            except (TypeError, ValueError):
                stop_loss_cents = None
            if stop_loss_cents is None:
                stop_pct = exit_spec.get("stop_pct")
                try:
                    stop_pct = float(stop_pct) if stop_pct not in (None, "") else None
                except (TypeError, ValueError):
                    stop_pct = None
                if stop_pct is not None and 0 < stop_pct < 100:
                    stop_loss_cents = int(price_cents * (1 - stop_pct / 100.0))
            if stop_loss_cents is not None and not (1 <= stop_loss_cents <= 99):
                stop_loss_cents = None

            # Optional time-based exit: market-sell whatever is still held when
            # the contract has <= N seconds to close.
            time_exit_secs = exit_spec.get("time_exit_secs")
            try:
                time_exit_secs = int(time_exit_secs) if time_exit_secs not in (None, "") else None
            except (TypeError, ValueError):
                time_exit_secs = None
            if time_exit_secs is not None and time_exit_secs <= 0:
                time_exit_secs = None

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
                    stop_loss_cents=stop_loss_cents,
                    exit_legs=exit_legs,
                    time_exit_secs=time_exit_secs,
                )
            except KalshiError as e:
                log.error("place_order failed on %s %s: %s", side, ticker, e)


_last_series_fetch: dict[str, float] = {}  # series_ticker -> last poll epoch (per-series cadence)


def _collect_market_snapshots(client: KalshiClient):
    now_ts = int(time.time())

    # Crypto prices are global per tick: fetch once per asset, write one row per
    # asset, and stamp every market_snapshots row with the same scanned_at so
    # they join on the tick.
    scanned_at = datetime.utcnow().isoformat()
    for asset in crypto_assets.CRYPTO_ASSETS:
        venues = fetch_crypto_prices(asset)
        db.save_crypto_snapshot(asset, scanned_at=scanned_at, **venues)

    # Series to scan come from the DB (editable on the Markets page); fall back to
    # the static config list if the table is empty/unavailable. Each series carries
    # its own look-ahead (how far out a market may close and still be captured —
    # 15-min BTC ~1200s, daily weather ~26h) and poll interval (slow markets don't
    # need 1s resolution), so we skip a series until its interval has elapsed.
    try:
        series_cfgs = db.get_scanned_series(enabled_only=True)
    except Exception as e:
        log.error("scanned_series read failed, using config fallback: %s", e)
        series_cfgs = []
    if not series_cfgs:
        series_cfgs = [{"series_ticker": s, "look_ahead_seconds": config.LOOK_AHEAD_SECONDS,
                        "interval_seconds": config.SNAPSHOT_INTERVAL_SECONDS}
                       for s in config.SNAPSHOT_SERIES_TICKERS]

    for cfg in series_cfgs:
        series = cfg["series_ticker"]
        interval = cfg.get("interval_seconds") or config.SNAPSHOT_INTERVAL_SECONDS
        if now_ts - _last_series_fetch.get(series, 0) < interval:
            continue
        _last_series_fetch[series] = now_ts
        series_max_close = now_ts + (cfg.get("look_ahead_seconds") or config.LOOK_AHEAD_SECONDS)
        try:
            data = client.get_markets(status="open", max_close_ts=series_max_close, limit=200, series_ticker=series)
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
                time_to_close_secs=time_to_close,
                scanned_at=scanned_at,
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
            count   = order.get("count") or 1
            # Scaled-out positions settle only the remainder; earlier rung
            # sales are already banked in close_proceeds_cents.
            remaining = count - (order.get("closed_count") or 0)
            proceeds  = order.get("close_proceeds_cents") or 0
            payout  = (100 if outcome == "win" else 0) * remaining + proceeds
            net     = payout - order["entry_price_cents"] * count
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
    log.info("Order caps     : none (max-open / daily-spend limits removed)")
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
    weather_collector = threading.Thread(target=weather_loop, daemon=True, name="weather")
    market_data.start()
    scanner.start()
    monitor.start()
    ws_fills.start()
    weather_collector.start()

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log.info("Shutting down.")


if __name__ == "__main__":
    main()
