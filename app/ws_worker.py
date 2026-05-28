"""
Background worker that maintains a persistent WebSocket connection to Kalshi.

Caches positions and quotes in-memory. Broadcasts state changes to per-client
queues consumed by the /api/events SSE endpoint.
"""

import asyncio
import json
import logging
import threading
import time
from queue import Empty, Queue

import websockets

import config
import database
from kalshi_client import KalshiClient

log = logging.getLogger(__name__)

_lock = threading.Lock()
_positions_cache: dict[str, dict] = {}   # ticker -> Position-shaped dict
_quotes_cache: dict[str, dict] = {}      # ticker -> quote dict
_snapshots_cache: list[dict] = []
_event_queues: list[Queue] = []
_connected = False
_bootstrapped = False
_started = False


# ── Public API ────────────────────────────────────────────────────────────────

def get_positions() -> list[dict]:
    with _lock:
        return list(_positions_cache.values())


def get_quotes() -> dict[str, dict]:
    with _lock:
        return dict(_quotes_cache)


def get_snapshots() -> list[dict]:
    with _lock:
        return list(_snapshots_cache)


def is_connected() -> bool:
    return _connected


def is_bootstrapped() -> bool:
    return _bootstrapped


def subscribe_events() -> Queue:
    q: Queue = Queue(maxsize=100)
    with _lock:
        _event_queues.append(q)
    return q


def unsubscribe_events(q: Queue) -> None:
    with _lock:
        try:
            _event_queues.remove(q)
        except ValueError:
            pass


# ── Internal helpers ──────────────────────────────────────────────────────────

def _broadcast(event_type: str, data) -> None:
    msg = {"type": event_type, "data": data}
    with _lock:
        queues = list(_event_queues)
    for q in queues:
        try:
            q.put_nowait(msg)
        except Exception:
            pass


def _dollars_to_cents(v) -> int | None:
    if v is None:
        return None
    try:
        return round(float(v) * 100)
    except Exception:
        return None


def _snapshot_poll_loop() -> None:
    last_head_id = None
    while True:
        try:
            snapshots = database.get_recent_market_snapshots(limit=200)
            head_id = snapshots[0]["id"] if snapshots else None
            with _lock:
                global _snapshots_cache
                _snapshots_cache = snapshots
            if head_id != last_head_id:
                _broadcast("snapshots", snapshots)
                last_head_id = head_id
        except Exception as e:
            log.debug("Snapshot poll failed: %s", e)
        time.sleep(1)


# ── Async worker ──────────────────────────────────────────────────────────────

async def _run() -> None:
    global _connected, _bootstrapped

    msg_id = 1
    ticker_sid: int | None = None
    subscribed_tickers: set[str] = set()

    while True:
        try:
            client = KalshiClient()

            # Bootstrap positions via REST so the cache is never cold-empty
            try:
                rest_data = client.get_positions()
                raw = rest_data.get("market_positions", [])
                with _lock:
                    _positions_cache.clear()
                    for p in raw:
                        if float(p.get("position_fp", 0)) != 0:
                            _positions_cache[p["ticker"]] = p
                _bootstrapped = True
                log.info("Bootstrapped %d positions via REST", len(_positions_cache))
            except Exception as e:
                log.warning("REST bootstrap failed: %s", e)

            headers = client.ws_auth_headers()
            async with websockets.connect(
                config.KALSHI_WS_URL,
                additional_headers=headers,
            ) as ws:
                _connected = True
                _broadcast("status", {"connected": True})
                log.info("Kalshi WS connected")

                msg_id = 1
                ticker_sid = None
                subscribed_tickers = set()

                # Subscribe to market_positions (all positions, no ticker filter)
                await ws.send(json.dumps({
                    "id": msg_id,
                    "cmd": "subscribe",
                    "params": {"channels": ["market_positions"]},
                }))
                msg_id += 1

                # Subscribe to ticker for held positions (with initial snapshot)
                with _lock:
                    initial_tickers = set(_positions_cache.keys())
                if initial_tickers:
                    await ws.send(json.dumps({
                        "id": msg_id,
                        "cmd": "subscribe",
                        "params": {
                            "channels": ["ticker"],
                            "market_tickers": list(initial_tickers),
                            "send_initial_snapshot": True,
                        },
                    }))
                    msg_id += 1
                    subscribed_tickers = set(initial_tickers)

                async for raw_msg in ws:
                    msg = json.loads(raw_msg)
                    t = msg.get("type")

                    if t == "market_position":
                        data = msg["msg"]
                        ticker = data["market_ticker"]

                        with _lock:
                            if float(data.get("position_fp", 0)) == 0:
                                _positions_cache.pop(ticker, None)
                            else:
                                existing = _positions_cache.get(ticker, {})
                                _positions_cache[ticker] = {
                                    "ticker": ticker,
                                    "position_fp": data["position_fp"],
                                    # Preserve total_traded_dollars from REST bootstrap
                                    "total_traded_dollars": existing.get("total_traded_dollars", "0"),
                                    "market_exposure_dollars": data["position_cost_dollars"],
                                    "realized_pnl_dollars": data["realized_pnl_dollars"],
                                    "fees_paid_dollars": data["fees_paid_dollars"],
                                    "last_updated_ts": "",
                                }
                            current_tickers = set(_positions_cache.keys())

                        _broadcast("positions", get_positions())

                        # Dynamically manage ticker subscriptions
                        new_tickers = current_tickers - subscribed_tickers
                        gone_tickers = subscribed_tickers - current_tickers

                        if ticker_sid is not None:
                            if new_tickers:
                                await ws.send(json.dumps({
                                    "id": msg_id,
                                    "cmd": "update_subscription",
                                    "params": {
                                        "sid": ticker_sid,
                                        "action": "add_markets",
                                        "market_tickers": list(new_tickers),
                                    },
                                }))
                                msg_id += 1
                                subscribed_tickers |= new_tickers
                            if gone_tickers:
                                await ws.send(json.dumps({
                                    "id": msg_id,
                                    "cmd": "update_subscription",
                                    "params": {
                                        "sid": ticker_sid,
                                        "action": "delete_markets",
                                        "market_tickers": list(gone_tickers),
                                    },
                                }))
                                msg_id += 1
                                subscribed_tickers -= gone_tickers
                        elif current_tickers:
                            # Ticker channel not yet started — subscribe now
                            await ws.send(json.dumps({
                                "id": msg_id,
                                "cmd": "subscribe",
                                "params": {
                                    "channels": ["ticker"],
                                    "market_tickers": list(current_tickers),
                                    "send_initial_snapshot": True,
                                },
                            }))
                            msg_id += 1
                            subscribed_tickers = set(current_tickers)

                    elif t == "subscribed":
                        channel = msg.get("msg", {}).get("channel")
                        sid = msg.get("msg", {}).get("sid")
                        if channel == "ticker":
                            ticker_sid = sid
                            log.info("Ticker channel subscribed sid=%s", sid)

                    elif t == "ticker":
                        data = msg["msg"]
                        ticker = data.get("market_ticker")
                        if ticker:
                            quote = {
                                "yes_ask": _dollars_to_cents(data.get("yes_ask_dollars")),
                                "no_ask":  _dollars_to_cents(data.get("no_ask_dollars")),
                                "yes_bid": _dollars_to_cents(data.get("yes_bid_dollars")),
                                "no_bid":  _dollars_to_cents(data.get("no_bid_dollars")),
                                "open_interest": (
                                    int(float(data["open_interest_fp"]))
                                    if data.get("open_interest_fp") else None
                                ),
                            }
                            with _lock:
                                _quotes_cache[ticker] = quote
                            _broadcast("quotes", {ticker: quote})

                    elif t == "error":
                        log.warning("Kalshi WS error msg: %s", msg)

        except Exception as e:
            log.warning("Kalshi WS disconnected: %s", e)
        finally:
            _connected = False
            _broadcast("status", {"connected": False})

        log.info("Reconnecting in 5s…")
        await asyncio.sleep(5)


def start() -> None:
    global _started
    if _started:
        return

    def _thread() -> None:
        asyncio.run(_run())

    t = threading.Thread(target=_thread, daemon=True, name="kalshi-ws")
    s = threading.Thread(target=_snapshot_poll_loop, daemon=True, name="snapshot-poll")
    t.start()
    s.start()
    _started = True
    log.info("Kalshi WS worker started")
