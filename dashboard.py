from flask import Flask, render_template, request
import sqlite3

app = Flask(__name__)

def get_orders(seller_filter=None):
    conn = sqlite3.connect("orders.db")
    cur = conn.cursor()
    if seller_filter:
        cur.execute("SELECT * FROM orders WHERE seller = ?", (seller_filter,))
    else:
        cur.execute("SELECT * FROM orders ORDER BY id DESC")
    orders = cur.fetchall()
    conn.close()
    return orders

@app.route('/', methods=["GET"])
def dashboard():
    seller = request.args.get("seller")
    orders = get_orders(seller_filter=seller)
    return render_template("dashboard.html", orders=orders, seller=seller)

if __name__ == '__main__':
    app.run(debug=True, port=7000)
