"""
Profiles and settings routes.
"""

from flask import Blueprint, jsonify, request

import database
from database.core import cursor_conn

profiles_bp = Blueprint('profiles', __name__)


@profiles_bp.get("/api/profiles")
def get_profiles():
    with cursor_conn() as c:
        c.execute("""
            SELECT p.*,
                   COUNT(DISTINCT o.market_ticker)                                                           AS order_count,
                   COUNT(DISTINCT o.market_ticker) FILTER (WHERE o.net_profit_cents > 0)               AS win_count,
                   COUNT(DISTINCT o.market_ticker) FILTER (WHERE o.net_profit_cents IS NOT NULL
                                                               AND o.net_profit_cents <= 0)            AS loss_count,
                   COALESCE(SUM(o.entry_price_cents * o.count) FILTER (WHERE o.status = 'filled'), 0) AS total_spend_cents,
                   COALESCE(SUM(o.net_profit_cents) FILTER (WHERE o.net_profit_cents IS NOT NULL), 0) AS total_profit_cents
            FROM profiles p
                 LEFT JOIN orders o ON o.profile_id = p.id AND o.order_role = 'entry'
            GROUP BY p.id
            ORDER BY p.created_at DESC
        """)
        rows = c.fetchall()
    return jsonify([dict(r) for r in rows])


@profiles_bp.post("/api/profiles")
def create_profile():
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400
    activate = data.get("activate", True)
    profile_id = database.create_profile(data, name=data.get("name"))
    if activate:
        database.activate_profile(profile_id)
    return jsonify({
        "status": "success",
        "profile_id": profile_id,
        "active_profile_id": profile_id if activate else None,
    })


@profiles_bp.put("/api/profiles/<int:profile_id>")
def update_profile(profile_id: int):
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400
    try:
        database.update_profile(profile_id, data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({"status": "success", "profile_id": profile_id})


@profiles_bp.post("/api/profiles/<int:profile_id>/activate")
def activate_profile(profile_id: int):
    try:
        database.activate_profile(profile_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({"status": "success", "active_profile_id": profile_id})


@profiles_bp.post("/api/profiles/<int:profile_id>/deactivate")
def deactivate_profile(profile_id: int):
    try:
        database.deactivate_profile(profile_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({"status": "success"})


@profiles_bp.delete("/api/profiles/<int:profile_id>")
def delete_profile(profile_id: int):
    try:
        ok, count = database.delete_profile(profile_id)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if not ok:
        if count is None:
            return jsonify({"error": "Profile not found"}), 404
        return jsonify({"error": "Profile has historical runs and cannot be deleted", "order_count": count}), 409

    return jsonify({"status": "success", "deleted_profile_id": profile_id}), 200


@profiles_bp.get("/api/settings")
def get_settings():
    return jsonify(database.get_settings())


@profiles_bp.post("/api/settings")
def update_settings():
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400
    database.update_settings(data)
    return jsonify({"status": "success"})
