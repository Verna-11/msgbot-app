from flask import Flask, request
import requests
import sqlite3
import re

app = Flask(__name__)

VERIFY_TOKEN = "test123"
PAGE_ACCESS_TOKEN = "EAARsLYLElpcBPG0EiUlS1oCX7sl8RFInZClq7R8uY9XGT2ZBPVJ3bllj9WHXyb7bebxdAm6PPTfbLpmmv4fzjP9ouF58IxOU5xt0zZAOZBkNJvJrY7pwt2F65FYO45OMQoVKgMQLUFhBGq8jDxLFf4YIZAKGjs51KJdIF4aMhlQbnc0eg19UR2nYjtasm8OfxURXx8QZDZD"

# In-memory user states
user_states = {}

# Initialize database
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
    # Extract seller tag if present
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

    elif state["step"] == "awaiting_product":
        state["order"]["product"] = msg
        state["step"] = "awaiting_name"
        return "Got it. May I have your full name?"

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
    if msg.lower().strip() in ["cancel", "start", "restart"]:
        user_states.pop(user_id, None)
        return "✅ Restarted. What product would you like to order? Please include the seller code (e.g., #Ana123)."

    else:
        # Unknown state
        user_states.pop(user_id, None)
        return "Oops, something went wrong. Let’s start over. What product would you like to order?"

def save_order(user_id, order):
    conn = sqlite3.connect("orders.db")
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO orders (user_id, seller, product, name, address, phone, payment)
        VALUES (?, ?, ?, ?, ?, ?,?)
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
    res = requests.post(url, headers=headers, params=params, json=payload)
    if res.status_code != 200:
        print("Failed to send message:", res.status_code, res.text)
    url = "https://graph.facebook.com/v18.0/me/messages"
    headers = {"Content-Type": "application/json"}
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": message_text}
    }
    params = {"access_token": PAGE_ACCESS_TOKEN}
    requests.post(url, headers=headers, params=params, json=payload)

if __name__ == '__main__':
    app.run(debug=True, port=5000)