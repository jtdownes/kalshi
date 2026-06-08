"""
Auth routes: login, logout, status, and brute-force rate limiting.
"""

import bcrypt
import psycopg2
import psycopg2.extras
import time
from collections import defaultdict
from contextlib import contextmanager
from threading import Lock

from flask import Blueprint, jsonify, request, session

import config

auth_bp = Blueprint('auth', __name__)

# ── Brute-force rate limiter ──────────────────────────────────────────────────
_MAX_ATTEMPTS = 10
_WINDOW       = 300   # 5 minutes
_LOCKOUT      = 900   # 15 minutes
_attempts: dict[str, list[float]] = defaultdict(list)
_attempts_lock = Lock()

_DUMMY_HASH = bcrypt.hashpw(b'dummy', bcrypt.gensalt())


def _get_client_ip() -> str:
    return request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()


def _check_rate_limit(ip: str) -> bool:
    """Return True if the IP is currently locked out."""
    now = time.time()
    with _attempts_lock:
        _attempts[ip] = [t for t in _attempts[ip] if now - t < _WINDOW]
        return len(_attempts[ip]) >= _MAX_ATTEMPTS


def _record_failure(ip: str):
    with _attempts_lock:
        _attempts[ip].append(time.time())


def _clear_attempts(ip: str):
    with _attempts_lock:
        _attempts.pop(ip, None)


@contextmanager
def _users_conn():
    conn = psycopg2.connect(config.USERS_DB_URL)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            yield cur
    finally:
        conn.close()


def _get_user_key_by_email(email: str):
    with _users_conn() as cur:
        cur.execute("SELECT user_key FROM users.profiles WHERE email = %s", (email,))
        row = cur.fetchone()
        return row['user_key'] if row else None


def _get_user_key_by_username(username: str):
    with _users_conn() as cur:
        cur.execute("SELECT user_key FROM users.profiles WHERE username = %s LIMIT 1", (username,))
        row = cur.fetchone()
        return row['user_key'] if row else None


def _get_password_hash(user_key) -> str | None:
    with _users_conn() as cur:
        cur.execute(
            "SELECT password_hash FROM users.credentials WHERE user_key = %s AND is_active = TRUE LIMIT 1",
            (user_key,)
        )
        row = cur.fetchone()
        return row['password_hash'] if row else None


def _get_login_info(user_key):
    with _users_conn() as cur:
        cur.execute(
            """SELECT p.user_key, p.username, p.email, p.first_name, p.last_name
               FROM users.profiles p
               JOIN users.credentials c ON p.user_key = c.user_key
               WHERE p.user_key = %s AND c.is_active = TRUE""",
            (user_key,)
        )
        return cur.fetchone()


@auth_bp.post('/api/auth/login')
def auth_login():
    ip = _get_client_ip()
    if _check_rate_limit(ip):
        return jsonify({"error": "Too many failed attempts. Try again later."}), 429

    data     = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip().lower()
    password = (data.get('password') or '').encode('utf-8')

    if not username or not password:
        _record_failure(ip)
        return jsonify({"error": "Username and password required"}), 400

    user_key = _get_user_key_by_username(username) or _get_user_key_by_email(username)

    if user_key:
        stored_hash = _get_password_hash(user_key)
    else:
        stored_hash = None

    if stored_hash:
        hash_bytes = stored_hash.encode('utf-8') if isinstance(stored_hash, str) else stored_hash
        valid = bcrypt.checkpw(password, hash_bytes)
    else:
        bcrypt.checkpw(password, _DUMMY_HASH)
        valid = False

    if not valid:
        _record_failure(ip)
        return jsonify({"error": "Invalid credentials"}), 401

    info = _get_login_info(user_key)
    if not info:
        _record_failure(ip)
        return jsonify({"error": "Account unavailable"}), 403

    _clear_attempts(ip)
    session.permanent = True
    session['user_key'] = str(info['user_key'])
    session['username'] = info['username']
    session['email']    = info['email']
    return jsonify({
        "ok": True,
        "username":   info['username'],
        "first_name": info.get('first_name'),
        "last_name":  info.get('last_name'),
    })


@auth_bp.get('/api/auth/logout')
def auth_logout():
    session.clear()
    return jsonify({"ok": True})


@auth_bp.get('/api/auth/status')
def auth_status():
    if session.get('username'):
        return jsonify({'logged_in': True, 'username': session['username']})
    return jsonify({'logged_in': False})
