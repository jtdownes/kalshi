import sqlite3
import psycopg2
import os
import sys

# Add app to path to get config
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))
import config

def migrate():
    sqlite_path = '/data/kalshi_trades.db'
    if not os.path.exists(sqlite_path):
        print(f"SQLite database not found at {sqlite_path}")
        return

    print(f"Connecting to SQLite: {sqlite_path}")
    s_conn = sqlite3.connect(sqlite_path)
    s_conn.row_factory = sqlite3.Row
    
    print(f"Connecting to Postgres: {config.DB_URL}")
    p_conn = psycopg2.connect(config.DB_URL)
    p_cur = p_conn.cursor()

    tables = ['orders', 'market_snapshots', 'btc_prices']
    
    for table in tables:
        print(f"Migrating table: {table}")
        rows = s_conn.execute(f"SELECT * FROM {table}").fetchall()
        if not rows:
            print(f"No data in {table}")
            continue
        
        columns = rows[0].keys()
        # Filter out 'id' if we want serial to handle it, but better to keep IDs
        cols_str = ", ".join(columns)
        placeholders = ", ".join(["%s"] * len(columns))
        
        insert_query = f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
        
        data = [tuple(r) for r in rows]
        p_cur.executemany(insert_query, data)
        print(f"Inserted {len(data)} rows into {table}")

    p_conn.commit()
    print("Migration complete!")
    s_conn.close()
    p_conn.close()

if __name__ == "__main__":
    migrate()
