import io
import pandas as pd
from flask import send_file
from datetime import datetime
from pytz import timezone

@app.route("/download-old-orders")
def download_old_orders():
    seller = session.get("seller")
    if not seller:
        return "You must be logged in as a seller", 403
    
    one_day_ago_utc = datetime.now(utc) - timedelta(days=1)

    conn = get_pg_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, user_id, seller, product, name, address, phone, payment, price, quantity, unit_price, created_at, order_key
        FROM orders
        WHERE created_at < %s AND seller = %s
        ORDER BY created_at ASC
    """, (one_day_ago_utc, seller))
    rows = cur.fetchall()
    col_names = [desc[0] for desc in cur.description]
    cur.close()
    conn.close()

    if not rows:
        return "No old orders found to download."

    # Create DataFrame
    df = pd.DataFrame(rows, columns=col_names)

    # Create an in-memory output file
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Old Orders")
    output.seek(0)

    # Send file to browser
    timestamp_str = ph_time.strftime("%Y-%m-%d")

    filename = f"{seller}_{timestamp_str}_orders.xlsx"
    return send_file(output, as_attachment=True, download_name=filename, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
