"""
Kalshi API v2 client with RSA-PSS-SHA256 request signing.

Auth flow:
  timestamp (ms) + METHOD + full path (incl. /trade-api/v2)  →  RSA-PSS-SHA256  →  base64
  Headers: KALSHI-ACCESS-KEY, KALSHI-ACCESS-TIMESTAMP, KALSHI-ACCESS-SIGNATURE
"""

import base64
import logging
import random
import threading
import time

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from pathlib import Path

import config

log = logging.getLogger(__name__)


# Per-tier per-second token budgets (read, write) from the Kalshi docs:
# official-docs/concepts/rate-limits-and-tiers.md
_TIER_BUDGETS = {
    "basic":    (200,  100),
    "advanced": (300,  300),
    "premier":  (1000, 1000),
    "paragon":  (2000, 2000),
    "prime":    (4000, 4000),
}
# Token cost per request. Most endpoints cost 10; cancellations are cheaper.
_DEFAULT_COST = 10
_CANCEL_COST  = 2

# Statuses we transparently retry. 429 = our own rate limit (back off until the
# bucket refills — there is no Retry-After header, per the docs). 5xx = Kalshi's
# exchange flapping; a couple of backed-off retries smooth transient blips.
_RETRY_429 = 5
_RETRY_5XX = 2
_BACKOFF_BASE = 0.5   # seconds; doubles each attempt
_BACKOFF_CAP  = 8.0

# Circuit breaker: when the exchange returns sustained 503s, stop hammering it
# (every retry into a down exchange is what drains the write bucket and earns a
# 429). After N consecutive write failures we open the breaker and fail writes
# locally — no network, no tokens spent — until a short cool-off elapses.
_CB_THRESHOLD = 5
_CB_COOLOFF   = 15.0


class KalshiError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class _TokenBucket:
    """Continuously-refilling token bucket matching a Kalshi read/write budget.

    Refills at `rate` tokens/sec up to `capacity`. The write bucket holds two
    seconds of budget (one on Basic) of burst headroom, per the docs.
    """

    def __init__(self, rate: float, capacity: float):
        self._rate = float(rate)
        self._capacity = float(capacity)
        self._tokens = float(capacity)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, cost: float):
        """Block until `cost` tokens are available, then spend them."""
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self._capacity,
                    self._tokens + (now - self._last) * self._rate,
                )
                self._last = now
                if self._tokens >= cost:
                    self._tokens -= cost
                    return
                wait = (cost - self._tokens) / self._rate
            time.sleep(min(wait, 1.0))


class KalshiClient:
    def __init__(self):
        key_bytes = Path(config.KALSHI_PRIVATE_KEY_PATH).read_bytes()
        self._private_key = serialization.load_pem_private_key(key_bytes, password=None)
        self._key_id = config.KALSHI_KEY_ID
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

        # Client-side throttling so we never out-run our budget and earn a 429.
        read_budget, write_budget = _TIER_BUDGETS.get(
            config.KALSHI_TIER, _TIER_BUDGETS["basic"])
        # Basic's write bucket holds 1s of budget; every other tier holds 2s.
        write_burst = 1.0 if config.KALSHI_TIER == "basic" else 2.0
        self._read_bucket = _TokenBucket(read_budget, read_budget * 2.0)
        self._write_bucket = _TokenBucket(write_budget, write_budget * write_burst)
        log.info("Kalshi client throttle: tier=%s read=%d/s write=%d/s",
                 config.KALSHI_TIER, read_budget, write_budget)

        # Write circuit breaker state.
        self._cb_lock = threading.Lock()
        self._cb_failures = 0
        self._cb_open_until = 0.0

    def _auth_headers(self, method: str, path: str) -> dict:
        # Kalshi signs only the URL path, not the query string. /trade-api/v2 prefix included.
        ts = str(int(time.time() * 1000))
        sig_path = "/trade-api/v2" + path
        msg = f"{ts}{method.upper()}{sig_path}".encode()
        sig = self._private_key.sign(
            msg,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY":       self._key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
        }

    # ── Circuit breaker (writes) ────────────────────────────────────────────
    def _breaker_guard(self):
        """Raise immediately if the write breaker is open (exchange is down)."""
        with self._cb_lock:
            remaining = self._cb_open_until - time.monotonic()
            if remaining > 0:
                raise KalshiError(
                    f"write circuit open (exchange unavailable), {remaining:.1f}s left",
                    status_code=503)

    def _breaker_record(self, ok: bool):
        with self._cb_lock:
            if ok:
                if self._cb_failures or self._cb_open_until:
                    log.info("Kalshi write circuit reset")
                self._cb_failures = 0
                self._cb_open_until = 0.0
            else:
                self._cb_failures += 1
                if self._cb_failures >= _CB_THRESHOLD and not self._cb_open_until:
                    self._cb_open_until = time.monotonic() + _CB_COOLOFF
                    log.warning("Kalshi write circuit OPEN after %d consecutive failures; "
                                "cooling off %.0fs", self._cb_failures, _CB_COOLOFF)

    # ── Request core ────────────────────────────────────────────────────────
    def _request(self, method: str, path: str, *, write: bool, cost: int,
                 params: dict = None, body: dict = None) -> dict:
        bucket = self._write_bucket if write else self._read_bucket
        url = config.KALSHI_API_BASE + path
        attempt = 0
        while True:
            if write:
                self._breaker_guard()
            bucket.acquire(cost)
            try:
                r = self._session.request(
                    method, url, headers=self._auth_headers(method, path),
                    params=params, json=body, timeout=10)
            except requests.RequestException as e:
                # Timeouts/resets must surface as KalshiError so callers'
                # error handling (and the write breaker) see a dead exchange
                # the same as a 5xx. Never retried in-call: a timed-out write
                # may have executed, and re-sending could double-place it.
                if write:
                    self._breaker_record(ok=False)
                raise KalshiError(f"network error: {e}") from e

            if r.ok:
                if write:
                    self._breaker_record(ok=True)
                return r.json()

            status = r.status_code
            is_5xx = 500 <= status < 600
            if write and is_5xx:
                self._breaker_record(ok=False)

            # Reads NEVER retry-in-call: the 1s market-data loop is the edge and
            # must keep its cadence, so a read error fails fast and the loop
            # retries on its own next tick. Backoff/breaker are write-only.
            if not write:
                raise KalshiError(f"HTTP {status} – {r.text[:300]}", status_code=status)

            limit = _RETRY_429 if status == 429 else (_RETRY_5XX if is_5xx else 0)
            if attempt < limit:
                delay = min(_BACKOFF_BASE * (2 ** attempt) + random.uniform(0, _BACKOFF_BASE),
                            _BACKOFF_CAP)
                log.warning("Kalshi %s %s -> HTTP %d; backoff %.2fs (retry %d/%d)",
                            method, path, status, delay, attempt + 1, limit)
                time.sleep(delay)
                attempt += 1
                continue

            raise KalshiError(f"HTTP {status} – {r.text[:300]}", status_code=status)

    def _get(self, path: str, params: dict = None, cost: int = _DEFAULT_COST) -> dict:
        return self._request("GET", path, write=False, cost=cost, params=params)

    def _post(self, path: str, body: dict, cost: int = _DEFAULT_COST) -> dict:
        return self._request("POST", path, write=True, cost=cost, body=body)

    def _delete(self, path: str, cost: int = _DEFAULT_COST) -> dict:
        return self._request("DELETE", path, write=True, cost=cost)

    def get_balance(self) -> dict:
        return self._get("/portfolio/balance")

    def get_markets(self, **kwargs) -> dict:
        return self._get("/markets", params={k: v for k, v in kwargs.items() if v is not None})

    def get_market(self, ticker: str) -> dict:
        return self._get(f"/markets/{ticker}")

    def place_order(self, ticker: str, side: str, price_cents: int,
                    client_order_id: str, count: int = 1,
                    action: str = "buy") -> dict:
        """Place a limit order.

        Kalshi deprecated the v1 outcome-centric create-order endpoint
        (POST /portfolio/orders → HTTP 410 deprecated_v1_order_endpoint). The V2
        endpoint (POST /portfolio/events/orders) speaks a single normalized
        YES-book instead of (side=yes/no, action=buy/sell):

            side="bid"  → buy YES        side="ask"  → sell YES
            price       → the YES-leg price, in DOLLARS (e.g. "0.56")
            count       → quantity, as a STRING

        Buying NO is economically selling YES, and selling NO is buying YES, so
        the YES-leg price is exactly the `yes_price` the bot already computes.
        We end up LONG yes (→ bid) when buying YES or selling NO, and SHORT yes
        (→ ask) when selling YES or buying NO. Verified against the live exchange:
        bid@0.01 rests as buy-YES@1¢; ask@0.99 rests as buy-NO@1¢.
        """
        yes_leg_cents = price_cents if side == "yes" else (100 - price_cents)
        yes_leg_cents = int(round(yes_leg_cents))
        book_side = "bid" if (action == "buy") == (side == "yes") else "ask"
        body = {
            "ticker":            ticker,
            "client_order_id":   client_order_id,
            "side":              book_side,
            "count":             str(int(count)),
            "price":             f"{yes_leg_cents / 100:.2f}",
            "time_in_force":     "good_till_canceled",
            "self_trade_prevention_type": "taker_at_cross",
        }
        resp = self._post("/portfolio/events/orders", body)
        # V2 returns a flat object ({order_id, client_order_id, fill_count,
        # remaining_count, ts_ms}); re-wrap as {"order": {...}} so every caller
        # that reads resp["order"]["order_id"] keeps working unchanged.
        return {"order": {
            "order_id":        resp.get("order_id"),
            "client_order_id": resp.get("client_order_id", client_order_id),
            "status":          "resting",
            "fill_count":      resp.get("fill_count"),
            "remaining_count": resp.get("remaining_count"),
        }}

    def get_orders(self, status: str = None, ticker: str = None, limit: int = 200) -> dict:
        params: dict = {"limit": limit}
        if status:
            params["status"] = status
        if ticker:
            params["ticker"] = ticker
        return self._get("/portfolio/orders", params=params)

    def get_order(self, order_id: str) -> dict:
        return self._get(f"/portfolio/orders/{order_id}")

    def cancel_order(self, order_id: str) -> dict:
        # V2 cancel. The v1 DELETE /portfolio/orders/{id} is being deprecated
        # alongside create (Kalshi notice 2026-06-18, cutover by ~06-25), so we
        # use the event-order path. Returns a flat {order_id, client_order_id,
        # reduced_by, ts_ms}; callers only check it doesn't raise.
        return self._delete(f"/portfolio/events/orders/{order_id}", cost=_CANCEL_COST)

    def get_fills(self, ticker: str = None, limit: int = 200) -> dict:
        params: dict = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        return self._get("/portfolio/fills", params=params)

    def get_positions(self, limit: int = 100) -> dict:
        return self._get("/portfolio/positions", params={
            "limit": limit,
            "count_filter": "position",
        })

    def ws_auth_headers(self) -> dict:
        """Generate authentication headers for the WebSocket handshake.
        Signs: timestamp + 'GET' + '/trade-api/ws/v2'  (no /v2 prefix on path)
        """
        ts = str(int(time.time() * 1000))
        msg = f"{ts}GET/trade-api/ws/v2".encode()
        sig = self._private_key.sign(
            msg,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY":       self._key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
        }


_client_lock = threading.Lock()
_client: KalshiClient | None = None


def get_client() -> KalshiClient:
    """Process-wide shared client. Constructing KalshiClient per call re-reads
    the private key and — worse — spins up fresh token buckets, so per-request
    instances each think they own the full rate-limit budget. Route handlers
    and workers in a process should share this one instance; the client is
    thread-safe (locked buckets/breaker, requests.Session)."""
    global _client
    with _client_lock:
        if _client is None:
            _client = KalshiClient()
        return _client
