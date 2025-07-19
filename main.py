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

#get name in facebooke
def get_user_full_name(psid, page_access_token):
    url = f"https://graph.facebook.com/v18.0/{psid}"
    params = {
        "fields": "first_name,last_name",
        "access_token": page_access_token
    }
    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            return f"{data.get('first_name', '')} {data.get('last_name', '')}".strip()
    except Exception as e:
        print("Error fetching user name:", e)
    return None

def handle_user_message(user_id, msg):
    state = user_states.get(user_id, {})
    if 'step' not in state:
        match = re.search(r'#([A-Za-z0-9_]+)', msg)
        if not match:
            user_states.pop(user_id, None)  # clear any existing state
            return (
            "⚠️ Sorry, hindi ko po naintindihan\n"
            "Please lagyan po natin ng \n"
            "hashtag si #seller example:\n"
            "#Sophialive Lip Gloss\n\n"
            "Subukan po uli"
        )

        seller_tag = match.group(1)
        product_text = re.sub(r'#\w+', '', msg).strip()

        # Match formats like: 2x100, 2X₱100.00
        match_qty_price1 = re.search(r'(\d+)[xX]₱?(\d+(\.\d{1,2})?)', product_text)
        
        # Match formats like: x2 ₱100 or x2 100
        match_qty_price2 = re.search(r'[xX](\d+)\s*₱?(\d+(\.\d{1,2})?)', product_text)

        # Pattern 4: price then quantity, like "300 x4" or "₱300 x4"
        match_price_qty = re.search(r'₱?(\d+(\.\d{1,2})?)\s*[xX](\d+)', product_text)
        
        # Format 4: "300 4x" or "₱300 4x"
        match_price_qty_reverse = re.search(r'₱?(\d+(\.\d{1,2})?)\s*(\d+)[xX]', product_text)
        # Match single price: 100 or ₱100
        match_single_price = re.search(r'₱?(\d+(\.\d{1,2})?)', product_text)
        
        if match_qty_price1:
            quantity = int(match_qty_price1.group(1))
            unit_price = float(match_qty_price1.group(2))
            total_price = quantity * unit_price
            product = re.sub(r'\d+[xX]₱?\d+(\.\d{1,2})?', '', product_text).strip()
        elif match_qty_price2:
            quantity = int(match_qty_price2.group(1))
            unit_price = float(match_qty_price2.group(2))
            total_price = quantity * unit_price
            product = re.sub(r'[xX]\d+\s*₱?\d+(\.\d{1,2})?', '', product_text).strip()
        elif match_price_qty:
            unit_price = float(match_price_qty.group(1))
            quantity = int(match_price_qty.group(3))
            total_price = quantity * unit_price
            product = re.sub(r'₱?\d+(\.\d{1,2})?\s*[xX]\d+', '', product_text).strip()
        elif match_price_qty_reverse:
            unit_price = float(match_price_qty_reverse.group(1))
            quantity = int(match_price_qty_reverse.group(3))
            total_price = quantity * unit_price
            product = product_text.replace(match_price_qty_reverse.group(0), '').strip()
        elif match_single_price:
            quantity = 1
            unit_price = float(match_single_price.group(1))
            total_price = unit_price
            product = re.sub(r'₱?\d+(\.\d{1,2})?', '', product_text).strip()
        else:
            quantity = 1
            unit_price = None
            total_price = None
            product = product_text.strip()
        
        full_name = get_user_full_name(user_id,PAGE_ACCESS_TOKEN)
        state = {
        "step": "awaiting_address",
        "order": {
            "buyer_name": full_name,
            "seller": seller_tag,
            "product": product,
            "unit_price": unit_price,
            "quantity": quantity,
            "price": total_price
        }
        }
        user_states[user_id] = state
        return f"Thanks for your order for '{product}' from seller #{seller_tag}.\nMay I have your address?"

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
            f"    Quantity {order['quantity']} X ₱{order['unit_price']:.2f} \n"
            f"💰 Total: ₱    {order['price']:.2f}\n"
            f"👤 Name: {order['buyer_name']}\n"
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
        order["buyer_name"],#row4
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
        SELECT name, COUNT(DISTINCT seller) AS from_seller SUM(price) AS total_spent
        FROM orders
        GROUP BY name
        ORDER BY total_spent DESC
    ''')
    summary = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("buyers.html", summary=summary)

# Sellers View
@app.route('/sellers')
def sellers_summary():
    conn = get_pg_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT seller, COUNT(*)
        FROM orders
        GROUP BY seller
    """)
    sellers_data = cur.fetchall()

    # Fetch buyers per seller
    seller_summaries = []
    for seller, count in sellers_data:
        cur.execute("""
            SELECT DISTINCT name
            FROM orders
            WHERE seller = %s
            ORDER BY name
        """, (seller,))
        buyers = [row[0] for row in cur.fetchall()]
        seller_summaries.append((seller, count, buyers))

    conn.close()
    return render_template('sellers.html', sellers=seller_summaries)



# Start the app

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
