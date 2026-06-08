"""
Kalshi API — Flask app factory and blueprint registration.
"""

from flask import Flask, session, jsonify, request
from werkzeug.middleware.proxy_fix import ProxyFix

import config
import database
import ws_worker
from routes.auth import auth_bp
from routes.trading import trading_bp
from routes.backtest import backtest_bp
from routes.markets import markets_bp
from routes.profiles import profiles_bp
from routes.analytics import analytics_bp

database.init_db()
ws_worker.start()

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config['SESSION_COOKIE_DOMAIN']      = '.jtdownes.com'
app.config['SESSION_COOKIE_SAMESITE']    = 'Lax'
app.config['SESSION_COOKIE_SECURE']      = True
app.config['SESSION_COOKIE_HTTPONLY']    = True
app.config['PERMANENT_SESSION_LIFETIME'] = 43200  # 12 hours
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

app.register_blueprint(auth_bp)
app.register_blueprint(trading_bp)
app.register_blueprint(backtest_bp)
app.register_blueprint(markets_bp)
app.register_blueprint(profiles_bp)
app.register_blueprint(analytics_bp)


@app.before_request
def require_login():
    public = {'/api/auth/login', '/api/auth/logout', '/api/auth/status', '/api/health'}
    if request.path not in public and not session.get('username'):
        return jsonify({"error": "Unauthorized"}), 401


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8820, debug=False)
