SELECT setval(pg_get_serial_sequence('orders', 'id'), coalesce(max(id), 1), max(id) IS NOT null) FROM orders;
SELECT setval(pg_get_serial_sequence('market_snapshots', 'id'), coalesce(max(id), 1), max(id) IS NOT null) FROM market_snapshots;
