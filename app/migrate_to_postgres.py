import sqlite3
import psycopg2
import os
import sys

# Add current directory to path to get config
sys.path.append(os.path.dirname(__file__))
import config

def migrate():
    # Use environment variable if available, otherwise default to container path
    sqlite_path = os.environ.get('DB_PATH', '/data/kalshi_trades.db')
    
    # If running outside container (e.g. during migration step), we might need to adjust
    if not os.path.exists(sqlite_path):
        # Try local path relative to project root
        project_root = os.path.dirname(os.path.dirname(__file__))
        alt_path = os.path.join(project_root, 'data', 'kalshi_trades.db')
        if os.path.exists(alt_path):
            sqlite_path = alt_path
        else:
            print(f"SQLite database not found at {sqlite_path} or {alt_path}")
            return

    print(f"Connecting to SQLite: {sqlite_path}")
    s_conn = sqlite3.connect(sqlite_path)
    s_conn.row_factory = sqlite3.Row
    
    print(f"Connecting to Postgres: {config.DB_URL}")
    try:
        p_conn = psycopg2.connect(config.DB_URL)
        p_cur = p_conn.cursor()
    except Exception as e:
        print(f"Failed to connect to Postgres: {e}")
        return

    tables = ['orders', 'market_snapshots', 'btc_prices']
    
    for table in tables:
        print(f"Migrating table: {table}")
        try:
            rows = s_conn.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                print(f"No data in {table}")
                continue
            
            columns = rows[0].keys()
            # Filter out 'id' if we want serial to handle it, but better to keep IDs
            cols_str = ", ".join(columns)
            placeholders = ", ".join(["%s"] * len(columns))
            
            # Build ON CONFLICT clause
            conflict_clause = "DO NOTHING"
            if table == 'orders':
                conflict_clause = "(client_order_id) DO NOTHING"
            elif table == 'market_snapshots':
                conflict_clause = "(id) DO NOTHING"
            elif table == 'btc_prices':
                conflict_clause = "(id) DO NOTHING"
                
            insert_query = f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) ON CONFLICT {conflict_clause}"
            
            data = [tuple(r) for r in rows]
            p_cur.executemany(insert_query, data)
            print(f"Inserted {len(data)} rows into {table}")
        except Exception as e:
            print(f"Error migrating {table}: {e}")

    p_conn.commit()
    print("Migration complete!")
    s_conn.close()
    p_conn.close()

if __name__ == "__main__":
    migrate()
