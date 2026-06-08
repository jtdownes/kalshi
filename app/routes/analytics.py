"""
Analytics routes: overview, edge matrix, EV curve.
"""

from flask import Blueprint, jsonify, request

from database.core import cursor_conn

analytics_bp = Blueprint('analytics', __name__)


@analytics_bp.get("/api/analytics/overview")
def analytics_overview():
    with cursor_conn() as c:
        c.execute("""
            SELECT
                COUNT(*)::bigint            AS total_snapshots,
                COUNT(DISTINCT ticker)::int AS unique_markets,
                MIN(scanned_at)             AS first_snapshot,
                MAX(scanned_at)             AS last_snapshot
            FROM market_snapshots
        """)
        overview = dict(c.fetchone())

        c.execute("""
            WITH final AS (
                SELECT DISTINCT ON (ticker)
                    ticker, yes_ask, time_to_close_secs
                FROM market_snapshots
                WHERE time_to_close_secs IS NOT NULL
                ORDER BY ticker, time_to_close_secs ASC
            )
            SELECT
                COUNT(*) FILTER (
                    WHERE time_to_close_secs < 120
                      AND (yes_ask >= 85 OR yes_ask <= 15)
                )::int AS resolved_markets,
                COUNT(*) FILTER (
                    WHERE time_to_close_secs < 120 AND yes_ask >= 85
                )::int AS yes_wins,
                COUNT(*) FILTER (
                    WHERE time_to_close_secs < 120 AND yes_ask <= 15
                )::int AS no_wins
            FROM final
        """)
        resolution = dict(c.fetchone())

    overview.update(resolution)
    return jsonify(overview)


@analytics_bp.get("/api/analytics/edge-matrix")
def analytics_edge_matrix():
    """Price × Time-to-Close matrix showing actual win rates vs implied probability."""
    with cursor_conn() as c:
        c.execute("""
            WITH resolved AS (
                SELECT DISTINCT ON (ticker)
                    ticker,
                    CASE WHEN yes_ask >= 85 THEN true ELSE false END AS won_yes
                FROM market_snapshots
                WHERE time_to_close_secs IS NOT NULL
                  AND time_to_close_secs < 120
                  AND (yes_ask >= 85 OR yes_ask <= 15)
                ORDER BY ticker, time_to_close_secs ASC
            )
            SELECT
                (FLOOR(s.yes_ask / 10)::int * 10) AS price_bucket,
                CASE
                    WHEN s.time_to_close_secs <= 120 THEN '0-2m'
                    WHEN s.time_to_close_secs <= 300 THEN '2-5m'
                    WHEN s.time_to_close_secs <= 600 THEN '5-10m'
                    ELSE '10-15m'
                END AS ttc_bucket,
                CASE
                    WHEN s.time_to_close_secs <= 120 THEN 1
                    WHEN s.time_to_close_secs <= 300 THEN 2
                    WHEN s.time_to_close_secs <= 600 THEN 3
                    ELSE 4
                END AS ttc_order,
                COUNT(DISTINCT s.ticker)::int AS market_count,
                ROUND(AVG(CASE WHEN r.won_yes THEN 1.0 ELSE 0.0 END) * 100, 1) AS actual_win_pct
            FROM market_snapshots s
            JOIN resolved r ON r.ticker = s.ticker
            WHERE s.yes_ask IS NOT NULL
              AND s.yes_ask > 0
              AND s.yes_ask < 100
              AND s.time_to_close_secs IS NOT NULL
              AND s.time_to_close_secs > 0
            GROUP BY 1, 2, 3
            HAVING COUNT(DISTINCT s.ticker) >= 3
            ORDER BY 1, 3
        """)
        rows = c.fetchall()
    return jsonify([{
        "price_bucket":   int(r["price_bucket"]),
        "ttc_bucket":     r["ttc_bucket"],
        "ttc_order":      int(r["ttc_order"]),
        "market_count":   int(r["market_count"]),
        "actual_win_pct": float(r["actual_win_pct"]) if r["actual_win_pct"] else 0,
    } for r in rows])


@analytics_bp.get("/api/analytics/ev-curve")
def analytics_ev_curve():
    """Per-cent expected value curve for low-price YES entries."""
    try:
        max_price = min(int(request.args.get("max_price", 50)), 99)
    except ValueError:
        max_price = 50

    with cursor_conn() as c:
        c.execute("""
            WITH resolved AS (
                SELECT DISTINCT ON (ticker)
                    ticker,
                    CASE WHEN yes_ask >= 85 THEN true ELSE false END AS won_yes
                FROM market_snapshots
                WHERE time_to_close_secs IS NOT NULL
                  AND time_to_close_secs < 120
                  AND (yes_ask >= 85 OR yes_ask <= 15)
                ORDER BY ticker, time_to_close_secs ASC
            )
            SELECT
                FLOOR(s.yes_ask)::int        AS price_cent,
                COUNT(DISTINCT s.ticker)::int AS market_count,
                ROUND(AVG(CASE WHEN r.won_yes THEN 1.0 ELSE 0.0 END) * 100, 2) AS win_pct
            FROM market_snapshots s
            JOIN resolved r ON r.ticker = s.ticker
            WHERE s.yes_ask IS NOT NULL
              AND s.yes_ask >= 1
              AND s.yes_ask <= %s
              AND s.time_to_close_secs IS NOT NULL
            GROUP BY 1
            HAVING COUNT(DISTINCT s.ticker) >= 2
            ORDER BY 1
        """, (max_price,))
        rows = c.fetchall()

    return jsonify([{
        "price":    int(r["price_cent"]),
        "markets":  int(r["market_count"]),
        "win_pct":  float(r["win_pct"]),
        "ev_cents": round(float(r["win_pct"]) - int(r["price_cent"]), 2),
    } for r in rows])
