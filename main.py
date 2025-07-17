from flask import Flask, request, render_template
import sqlite3, requests, re
import os

app = Flask(__name__)

VERIFY_TOKEN = "test123"
PAGE_ACCESS_TOKEN = "EAARsLYLElpcBPFoGAXkq1N6hjluaFhGEqV11cWHIxeAeomv7XDgke3LKM7TOY3n7I81eKVZCZBvw3aknrzKLZCqfDE4hmI7EzZCfwQjFtBZCPqT3MLW0rZCL8ZBqvN3nyCgEpQOvJF9u2hbhm8j180aZAokRtbRWCeNM0fkEek62bE4M1wrSBZBd7xMVhmaOy0Er6mxWzDwZDZD"
user_states = {}

# 🔧 SQLite init
def init_db():
    conn = sqlite3.connect("orders.db")
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            seller TEXT,
            product TEXT,
            name TEXT,
            address TEXT,
            phone TEXT,
            payment TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

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
                user_message = msg_event["message"]["text"]
                response = handle_user_message(sender_id, user_message)
                send_message(sender_id, response)
    return "ok", 200

def handle_user_message(user_id, msg):
    state = user_states.get(user_id, {})
    if 'step' not in state:
        match = re.search(r'#([A-Za-z0-9_]+)', msg)
        seller_tag = match.group(1) if match else "Unknown"
        product = re.sub(r'#\w+', '', msg).strip()
        state = {
            "step": "awaiting_name",
            "order": {
                "seller": seller_tag,
                "product": product
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
        return "Noted. What's your phone number?"
    elif state["step"] == "awaiting_phone":
        state["order"]["phone"] = msg
        state["step"] = "awaiting_payment"
        return "Almost done. Will you pay via GCash or Cash on Delivery?"
    elif state["step"] == "awaiting_payment":
        state["order"]["payment"] = msg
        order = state["order"]
        save_order(user_id, order)
        user_states.pop(user_id)
        return (
            f"✅ Order confirmed!\n\n"
            f"📦 Product: {order['product']}\n"
            f"👤 Name: {order['name']}\n"
            f"📍 Address: {order['address']}\n"
            f"📞 Phone: {order['phone']}\n"
            f"💰 Payment: {order['payment']}\n\n"
            f"Thank you! We’ll be in touch soon. 😊"
        )
    else:
        user_states.pop(user_id, None)
        return "Oops, something went wrong. Let's start over. Please send your order again."

def save_order(user_id, order):
    conn = sqlite3.connect("orders.db")
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO orders (user_id, seller, product, name, address, phone, payment)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        user_id,
        order["seller"],
        order["product"],
        order["name"],
        order["address"],
        order["phone"],
        order["payment"]
    ))
    conn.commit()
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
    conn = sqlite3.connect("orders.db")
    cur = conn.cursor()
    if seller:
        cur.execute("SELECT * FROM orders WHERE seller = ? ORDER BY id DESC", (seller,))
    else:
        cur.execute("SELECT * FROM orders ORDER BY id DESC")
    orders = cur.fetchall()
    conn.close()
    return render_template("dashboard.html", orders=orders, seller=seller)

# Start the app

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
