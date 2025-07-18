from flask import Flask, request, render_template
import requests, re
import os
import psycopg2
from urllib.parse import urlparse


app = Flask(__name__)


VERIFY_TOKEN = "test123"
PAGE_ACCESS_TOKEN = "EAARsLYLElpcBPFoGAXkq1N6hjluaFhGEqV11cWHIxeAeomv7XDgke3LKM7TOY3n7I81eKVZCZBvw3aknrzKLZCqfDE4hmI7EzZCfwQjFtBZCPqT3MLW0rZCL8ZBqvN3nyCgEpQOvJF9u2hbhm8j180aZAokRtbRWCeNM0fkEek62bE4M1wrSBZBd7xMVhmaOy0Er6mxWzDwZDZD"
user_states = {}


DATABASE_URL = os.environ.get("DATABASE_URL")

#connecting to postgres
def get_pg_connection():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

#data base connection and commit
def init_pg():
    conn = get_pg_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id TEXT,
            seller TEXT,
            product TEXT,
            name TEXT,
            address TEXT,
            phone TEXT,
            payment TEXT,
            price NUMERIC,
            quantity INTEGER,
            unit_price NUMERIC


        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

init_pg() #initiating db

# ✅ Messenger Webhook
@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        if request.args.get("hub.verify_token") == VERIFY_TOKEN:
            return request.args.get("hub.challenge")
        return "Invalid token"

    data = request.get_json()
    for entry in data.get("entry", []):
        for msg_event in entry.get("messaging", []):
            sender_id = msg_event["sender"]["id"]
            if "message" in msg_event and "text" in msg_event["message"]:
                user_message = msg_event["message"]["text"].title()
                response = handle_user_message(sender_id, user_message)
                send_message(sender_id, response)
    return "ok", 200

def handle_user_message(user_id, msg):
    state = user_states.get(user_id, {})
    if 'step' not in state:
        match = re.search(r'#([A-Za-z0-9_]+)', msg)
        if not match:
            user_states.pop(user_id, None)  # clear any existing state
            return (
            "⚠️ Sorry, hindi ko po naintindihan wala po tag #.\n"
            "Please lagyan po natin ng hashtag si seller # example:\n"
            "`#Sophialive 2x Lip Balm`\n\n"
            "Subukan po uli"
        )

        seller_tag = match.group(1)
        product_text = re.sub(r'#\w+', '', msg).strip()
        # Match formats like 2x150 3x188
        match_price_qty = re.search(r'(\d+)[xX]₱?(\d+(\.\d{1,2})?)', product_text)
        if match_price_qty:
            quantity = int(match_price_qty.group(1))
            unit_price = float(match_price_qty.group(2))
            total_price = quantity * unit_price
        else:
            quantity = 1
            unit_price = None
            total_price = None
        product = re.sub(r'\d+[xX]₱?\d+(\.\d{1,2})?', '', product_text).strip()
        state = {
        "step": "awaiting_name",
        "order": {
            "seller": seller_tag,
            "product": product,
            "unit_price": unit_price,
            "quantity": quantity,
            "price": total_price
        }
        }
        user_states[user_id] = state
        return f"Thanks for your order for '{product}' from seller #{seller_tag}.\nMay I have your full name?"
    
    elif state["step"] == "awaiting_name":
        state["order"]["name"] = msg
        state["step"] = "awaiting_address"
        return "Thanks! What is your complete delivery address?"
    elif state["step"] == "awaiting_address":
        state["order"]["address"] = msg
        state["step"] = "awaiting_phone"
        return "Noted. What's your phone number? o alam na po ni seller"
    elif state["step"] == "awaiting_phone":
        state["order"]["phone"] = msg
        state["step"] = "awaiting_payment"
        return "Last step Bank Transfer, Maya, Gcash or Cash on Delivery?"
    elif state["step"] == "awaiting_payment":
        state["order"]["payment"] = msg
        order = state["order"]
        save_order(user_id, order)
        user_states.pop(user_id)
        return (
            f"✅ Order confirmed!\n\n"
            f"📦 Product: {order['product']}\n"
            f"    Quantity {order['quantity']} @ {order['unit_price']:.2f} \n"
            f"💰 Total: @{order['price']:.2f}\n"
            f"👤 Name: {order['name']}\n"
            f"📍 Address: {order['address']}\n"
            f"📞 Phone: {order['phone']}\n"
            f"💰 Payment: {order['payment']}\n\n"
            f"Thank you! you'll be in touch with the seller soon. 😊"
        )
    else:
        user_states.pop(user_id, None)
        return "Oops, something went wrong. Let's start over. Please send your order again."

def save_order(user_id, order):
    conn = get_pg_connection()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO orders (user_id, seller, product, price, name, address, phone, payment,quantity,unit_price)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ''', (
        user_id,         #row0 base 0
        order["seller"], #row1
        order["product"],#row2
        order["price"],#row3
        order["name"],#row4
        order["address"],#row5
        order["phone"],#row6
        order["payment"],#row7
        order["quantity"],#row8
        order["unit_price"]#row9
    ))
    conn.commit()
    cur.close()
    conn.close()


def send_message(recipient_id, message_text):
    url = "https://graph.facebook.com/v18.0/me/messages"
    headers = {"Content-Type": "application/json"}
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": message_text}
    }
    params = {"access_token": PAGE_ACCESS_TOKEN}
    res = requests.post(url, headers=headers, params=params, json=payload)
    if res.status_code != 200:
        print("Failed to send message:", res.text)

# 📊 Dashboard View
@app.route('/')
def dashboard():
    seller = request.args.get("seller")
    conn = get_pg_connection()
    cur = conn.cursor()
    if seller:
        cur.execute("SELECT * FROM orders WHERE seller = %s ORDER BY id DESC", (seller,))
    else:
        cur.execute("SELECT * FROM orders ORDER BY id DESC")
    orders = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("dashboard.html", orders=orders, seller=seller)

#  Buyers View
@app.route('/buyers')
def buyers_summary():
    conn = get_pg_connection()
    cur = conn.cursor()
    cur.execute('''
        SELECT buyer_name, SUM(COALESCE(price, 0) * COALESCE(quantity, 1)) AS total
        FROM orders
        WHERE seller = %s
        GROUP BY buyer_name
    ''',(seller,))
    summary = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("buyers.html", summary=summary)

# Sellers View
@app.route('/sellers')
def sellers_overview():
    conn = get_pg_connection()
    cur = conn.cursor()
    cur.execute('''
        SELECT seller, COUNT(DISTINCT name) AS buyer_count, SUM(price) AS total_sales
        FROM orders
        GROUP BY seller
        ORDER BY total_sales DESC
    ''')
    sellers = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("sellers.html", sellers=sellers)


# Start the app

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
