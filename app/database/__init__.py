"""
database package — re-exports all public functions from submodules.
Existing code that does `import database; database.save_order(...)` continues to work.
"""

from .core import (
    _conn, cursor_conn, _execute, execute_sql_file,
    init_db, _lock,
)
from .orders import (
    save_order, update_order,
    has_open_order, has_open_order_for_rule, has_filled_entry_for_rule,
    get_today_spend_cents, count_resting_orders,
    get_resting_orders, get_sibling_resting_entries,
    get_filled_without_outcome, get_open_stop_orders,
    get_open_time_exit_orders, get_resting_child_exits,
    get_order_by_kalshi_order_id, close_entry_order_with_exit,
    apply_exit_fill,
)
from .snapshots import (
    save_bitcoin_snapshot, save_ethereum_snapshot, save_market_snapshot,
    get_latest_snapshot_for_ticker,
    get_recent_market_snapshots, get_market_snapshots_for_ticker,
    get_recent_btc_prices, get_latest_snapshots_for_series,
    get_prior_resolutions_for_close,
)
from .weather import (
    save_weather_snapshot,
    get_latest_weather_snapshot, get_recent_weather_snapshots,
)
from .series import (
    get_scanned_series, add_scanned_series,
    remove_scanned_series, set_scanned_series_enabled,
)
from .profiles import (
    get_active_profile_id, create_profile, update_profile, delete_profile,
    activate_profile, deactivate_profile, get_active_profiles,
)
from .settings import get_settings, update_settings

__all__ = [
    # core
    '_conn', 'cursor_conn', '_execute', 'execute_sql_file', 'init_db', '_lock',
    # orders
    'save_order', 'update_order',
    'has_open_order', 'has_open_order_for_rule', 'has_filled_entry_for_rule',
    'get_today_spend_cents', 'count_resting_orders',
    'get_resting_orders', 'get_sibling_resting_entries',
    'get_filled_without_outcome', 'get_open_stop_orders',
    'get_open_time_exit_orders', 'get_resting_child_exits',
    'get_order_by_kalshi_order_id', 'close_entry_order_with_exit',
    'apply_exit_fill',
    # snapshots
    'save_bitcoin_snapshot', 'save_ethereum_snapshot', 'save_market_snapshot',
    'get_latest_snapshot_for_ticker',
    'get_recent_market_snapshots', 'get_market_snapshots_for_ticker',
    'get_recent_btc_prices', 'get_latest_snapshots_for_series',
    'get_prior_resolutions_for_close',
    # weather
    'save_weather_snapshot', 'get_latest_weather_snapshot', 'get_recent_weather_snapshots',
    # series
    'get_scanned_series', 'add_scanned_series',
    'remove_scanned_series', 'set_scanned_series_enabled',
    # profiles
    'get_active_profile_id', 'create_profile', 'update_profile', 'delete_profile',
    'activate_profile', 'deactivate_profile', 'get_active_profiles',
    # settings
    'get_settings', 'update_settings',
]
