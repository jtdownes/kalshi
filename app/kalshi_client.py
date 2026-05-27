"""
Kalshi API v2 client with RSA-PSS-SHA256 request signing.

Auth flow:
  timestamp (ms) + METHOD + full path (incl. /trade-api/v2)  →  RSA-PSS-SHA256  →  base64
  Headers: KALSHI-ACCESS-KEY, KALSHI-ACCESS-TIMESTAMP, KALSHI-ACCESS-SIGNATURE
"""

import base64
import logging
import time

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from pathlib import Path

import config

log = logging.getLogger(__name__)


class KalshiError(Exception):
    pass


class KalshiClient:
    def __init__(self):
        key_bytes = Path(config.KALSHI_PRIVATE_KEY_PATH).read_bytes()
        self._private_key = serialization.load_pem_private_key(key_bytes, password=None)
        self._key_id = config.KALSHI_KEY_ID
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

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

    def _get(self, path: str, params: dict = None) -> dict:
        url = config.KALSHI_API_BASE + path
        r = self._session.get(url, headers=self._auth_headers("GET", path),
                              params=params, timeout=10)
        self._raise_for_status(r)
        return r.json()

    def _post(self, path: str, body: dict) -> dict:
        url = config.KALSHI_API_BASE + path
        r = self._session.post(url, headers=self._auth_headers("POST", path),
                               json=body, timeout=10)
        self._raise_for_status(r)
        return r.json()

    def _delete(self, path: str) -> dict:
        url = config.KALSHI_API_BASE + path
        r = self._session.delete(url, headers=self._auth_headers("DELETE", path),
                                 timeout=10)
        self._raise_for_status(r)
        return r.json()

    @staticmethod
    def _raise_for_status(r: requests.Response):
        if not r.ok:
            raise KalshiError(f"HTTP {r.status_code} – {r.text[:300]}")

    def get_balance(self) -> dict:
        return self._get("/portfolio/balance")

    def get_markets(self, **kwargs) -> dict:
        return self._get("/markets", params={k: v for k, v in kwargs.items() if v is not None})

    def get_market(self, ticker: str) -> dict:
        return self._get(f"/markets/{ticker}")

    def place_order(self, ticker: str, side: str, price_cents: int,
                    client_order_id: str, count: int = 1) -> dict:
        yes_price = price_cents if side == "yes" else (100 - price_cents)
        body = {
            "ticker":           ticker,
            "client_order_id":  client_order_id,
            "type":             "limit",
            "action":           "buy",
            "side":             side,
            "count":            count,
            "yes_price":        yes_price,
        }
        return self._post("/portfolio/orders", body)

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
        return self._delete(f"/portfolio/orders/{order_id}")

    def get_fills(self, ticker: str = None, limit: int = 200) -> dict:
        params: dict = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        return self._get("/portfolio/fills", params=params)
