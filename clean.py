import os
import psycopg2
from datetime import datetime, timedelta

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_pg_connection():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def delete_old_orders():
    conn = get_pg_connection()
    cur = conn.cursor()
    one_week_ago = datetime.utcnow() - timedelta(days=7)
    cur.execute("DELETE FROM orders WHERE created_at < %s", (one_week_ago,))
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    print(f"✅ Deleted {deleted} old orders.")

if __name__ == "__main__":
    delete_old_orders()
