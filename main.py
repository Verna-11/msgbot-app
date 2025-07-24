import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, request, render_template,session, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import re
import os
from dotenv import load_dotenv

import uuid
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.errors import UniqueViolation

from pytz import timezone

load_dotenv()

app = Flask(__name__)

PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

DATABASE_URL = os.environ.get("DATABASE_URL")
app.secret_key = os.environ.get("SECRET_KEY")

user_states = {}


logging.basicConfig(
    level=logging.INFO, # logging for debugging DEBUG
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
    )


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        seller = request.form['seller']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        # Check if passwords match
        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('register.html')

        # Hash password
        hashed_password = generate_password_hash(password)

        # Save to DB
        try:
            conn = get_pg_connection()
            cur = conn.cursor()

            # Check if seller or email already exists
            cur.execute("SELECT * FROM sellers WHERE seller = %s OR email = %s", (seller, email))
            existing = cur.fetchone()
            if existing:
                flash('Seller or email already exists.', 'danger')
                return render_template('register.html')

            # Insert new seller
            cur.execute("INSERT INTO sellers (seller, password, email) VALUES (%s, %s, %s)",
                        (seller, hashed_password, email))
            conn.commit()
            cur.close()
            conn.close()

            flash('Registration successful! You can now log in.', 'success')
            return redirect(url_for('login'))

        except Exception as e:
            print("Error:", e)
            flash('Registration failed. Please try again later.', 'danger')
            return render_template('register.html')

    return render_template('register.html')



@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        seller = request.form['seller']
        password = request.form['password']

        conn = get_pg_connection()
        cur = conn.cursor()
        cur.execute("SELECT password FROM sellers WHERE seller = %s", (seller,))
        result = cur.fetchone()
        cur.close()
        conn.close()

        if result and check_password_hash(result[0], password):
            session['seller'] = seller
            flash("Login successful.", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid credentials.", "danger")
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('seller', None)
    flash("Logged out.", "info")
    return redirect(url_for('login'))


#connecting to postgres
def get_pg_connection():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

#scheduler deletion of old order in database
def delete_old_orders():
    conn = get_pg_connection()
    cur = conn.cursor()
    two_days = datetime.utcnow() - timedelta(days=2)
    cur.execute("DELETE FROM orders WHERE created_at < %s", (two_days,))
    conn.commit()
    cur.close()
    conn.close()
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
            unit_price NUMERIC,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            order_key TEXT UNIQUE,
            ref_code TEXT


        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS sellers (
            seller TEXT PRIMARY KEY,
            password TEXT
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id TEXT PRIMARY KEY,
            name TEXT,
            address TEXT,
            phone TEXT,
            payment TEXT
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            fb_id TEXT PRIMARY KEY,
            ref_code TEXT
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
    logging.info(f"Received Data: {data}")

    for entry in data.get("entry", []):
        for msg_event in entry.get("messaging", []):
            sender_id = msg_event["sender"]["id"]
            ref_code = None

            # ✅ Check for referral in postback
            if "postback" in msg_event and "referral" in msg_event["postback"]:
                referral = msg_event["postback"]["referral"]
                ref_code = referral.get("ref")
                logging.info(f"[Postback] Referral code: {ref_code}")

            # ✅ Check for standalone referral (from m.me link click)
            elif "referral" in msg_event:
                referral = msg_event["referral"]
                ref_code = referral.get("ref")
                logging.info(f"[Referral] Referral code: {ref_code}")

            # ✅ Check for optin (for checkbox plugin etc)
            elif "optin" in msg_event and "ref" in msg_event["optin"]:
                ref_code = msg_event["optin"]["ref"]
                logging.info(f"[Optin] Referral code: {ref_code}")

            # ✅ Save ref_code if found
            if ref_code:
                user_states[sender_id] = user_states.get(sender_id, {})
                user_states[sender_id]["ref_code"] = ref_code

                # Optional: save to DB
                try:
                    conn = get_pg_connection()
                    cur = conn.cursor()
                    cur.execute("SELECT ref_code FROM users WHERE fb_id = %s", (sender_id,))
                    row = cur.fetchone()
                    if row is None:
                        cur.execute("INSERT INTO users (fb_id, ref_code) VALUES (%s, %s)", (sender_id, ref_code))
                    elif not row[0]:
                        cur.execute("UPDATE users SET ref_code = %s WHERE fb_id = %s", (ref_code, sender_id))
                    conn.commit()
                    cur.close()
                    conn.close()
                    logging.info(f"Saved ref_code {ref_code} for {sender_id} in DB.")
                except Exception as e:
                    logging.error(f"DB Error: {e}")

                send_message(sender_id, f"👋 Welcome! to *{ref_code}*'s shop")
                continue  # ✅ Skip message if this is just a referral event

            # ✅ Handle regular text messages
            if "message" in msg_event and "text" in msg_event["message"]:
                user_message = msg_event["message"]["text"].strip()
                logging.info(f"[Message] From {sender_id}: {user_message}")
                response = handle_user_message(sender_id, user_message)
                send_message(sender_id, response)

    return "ok", 200




#get name in facebook
def get_user_full_name(psid, page_access_token):
    url = f"https://graph.facebook.com/v23.0/{psid}"
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
        return ("Error fetching user name:", e)
    return None

#checking capture name 
def is_full_name(name):
    if not name:
        return False
    return len(name.strip().split()) >= 2

def handle_user_message(user_id, msg):
    if msg.lower().startswith("invoice"):
        match = re.search(r'#([A-Za-z0-9_]+)', msg)
        if match:
            override_ref = match.group(1)
        else:
            override_ref = None
    
        orders = get_orders_by_sender(user_id, override_ref)
    
        if not orders:
            return "📭 You have no orders for this store."
    
        invoice_message = generate_invoice_for_sender(user_id, orders)
        send_message(user_id, invoice_message)
        return

    if msg.lower().startswith("edit"):
        parts = msg.split(" ", 1)
        if len(parts) != 2 or not parts[1].strip():
            return "❌ Please provide a valid order key to edit. Example: *edit abcd1234*"
    
        key = parts[1].strip()
        conn = get_pg_connection()
        cur = conn.cursor()
    
        cur.execute("SELECT product, quantity, unit_price, address, phone, payment FROM orders WHERE order_key = %s AND user_id = %s", (key, user_id))
        order = cur.fetchone()

        if order:
            product, quantity, unit_price, address, phone, payment = order
            user_states[user_id] = {
                "step": "edit_product",
                "edit_key": key,
                "order": {
                    "product": product,
                    "quantity": quantity,
                    "unit_price": float(unit_price),
                    "price": float(unit_price) * int(quantity),
                    "address": address,
                    "phone": phone,
                    "payment": payment
                }
            }
            cur.close()
            conn.close()
            return (
                f"📝 Editing order `{key}` for '{product}'.\n"
                f"Current product: {product}, Qty: {quantity}, Unit Price: ₱{unit_price:.2f}\n\n"
                f"✏️ Please send the new *product name/description*:"
            )
        else:
            cur.close()
            conn.close()
            return f"⚠️ *No order found* with key `{key}` that belongs to you."

    if msg.lower().startswith("cancel"):
        parts = msg.split(" ", 1)
        if len(parts) != 2 or not parts[1].strip():
            return "❌ Please provide a valid *order key*. Example: *cancel abcd1234*"

        key = parts[1].strip().lower()
        conn = get_pg_connection()
        cur = conn.cursor()

        # Double check if the order exists and belongs to user
        cur.execute("SELECT id FROM orders WHERE order_key = %s AND user_id = %s", (key, user_id))
        order = cur.fetchone()

        if order:
            cur.execute("DELETE FROM orders WHERE id = %s", (order[0],))
            conn.commit()
            result = f"✅ Your order with key *`{key}`* has been *canceled.*"
        else:
            result = f"⚠️ Order key *`{key}`* was not *found* or does not *belong* to you."

        cur.close()
        conn.close()
        return result
    state = user_states.get(user_id, {})
    ref_code = state.get("ref_code")
    
    if 'step' not in state:
        match = re.search(r'#([A-Za-z0-9_]+)', msg)
        if match:
            # 🔁 New store explicitly in message (#store)
            seller_tag = match.group(1)
            user_states[user_id] = user_states.get(user_id, {})
            user_states[user_id]["ref_code"] = seller_tag
            save_ref_code_to_db(user_id, seller_tag)
        
        else:
            # ⚠️ Use referral from state (latest click) or DB if not found
            seller_tag = state.get("ref_code")
            if not seller_tag:
                conn = get_pg_connection()
                cur = conn.cursor()
                cur.execute("SELECT ref_code FROM users WHERE fb_id = %s", (user_id,))
                row = cur.fetchone()
                cur.close()
                conn.close()
                if row and row[0]:
                    seller_tag = row[0]
                    user_states[user_id] = {"ref_code": seller_tag}
                else:
                    user_states.pop(user_id, None)
                    return "⚠️ Sorry, I can't determine your store. Please include *#storename* in your message."

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
        #cache name, address, payment, phone
        profile = get_user_profile(user_id)
        if profile:
            name, address, phone, payment = profile
            user_states[user_id] = {
                "step": "awaiting_confirm",
                "order": {
                    "name": name,
                    "address": address,
                    "phone": phone,
                    "payment": payment,
                    "seller": seller_tag,
                    "product": product,
                    "unit_price": unit_price,
                    "quantity": quantity,
                    "price": total_price
                }
            }
            return (
                f"📝 Reusing your previous info:\n"
                f"👤 {name}\n📍 {address}\n📞 {phone}\n💳 {payment}\n\n"
                f"✅ Send *yes or no* to confirm this order or *no or n* to edit"
            )
        # ✅ Get full name from Facebook API
        full_name = get_user_full_name(user_id, PAGE_ACCESS_TOKEN)
        if not is_full_name(full_name):
            user_states[user_id] = {
                "step": "ask_name",
                "order": {
                    "seller": seller_tag,
                    "product": product,
                    "unit_price": unit_price,
                    "quantity": quantity,
                    "price": total_price
                }
            }
            return f"Thanks for your order for *'{product}'* from seller *#{seller_tag}.*\nMay I have your *full name*?"
        else:
            user_states[user_id] = {
                "step": "awaiting_address",
                "order": {
                    "name": full_name,
                    "seller": seller_tag,
                    "product": product,
                    "unit_price": unit_price,
                    "quantity": quantity,
                    "price": total_price
                }
            }
            return "📍 Please enter your *delivery address*:"


    elif state["step"] == "edit_product":
        state["order"]["product"] = msg
        state["step"] = "edit_quantity"
        return "🔢 New *quantity*?"

    elif state["step"] == "edit_quantity":
        try:
            qty = int(msg)
            state["order"]["quantity"] = qty
            state["step"] = "edit_unit_price"
            return "💸 New unit *price*?"
        except ValueError:
            return "❌ Please enter a valid *number* for *quantity*."

    elif state["step"] == "edit_unit_price":
        try:
            price = float(msg)
            state["order"]["unit_price"] = price
            state["order"]["price"] = price * state["order"]["quantity"]
            state["step"] = "edit_address"
            return "📍 New *address*?"
        except ValueError:
            return "❌ Please enter a valid *price (e.g., 99.99)*"
    elif state["step"] == "edit_address":
        state["order"]["address"] = msg
        state["step"] = "edit_phone"
        return "📞 Got it. What's the new *phone number*?"

    elif state["step"] == "edit_phone":
        state["order"]["phone"] = msg
        state["step"] = "edit_payment"
        return "💳 Noted. What's the new *payment method*?"

    elif state["step"] == "edit_payment":
        state["order"]["payment"] = msg
        order = state["order"]
        order_key = state["edit_key"]

        conn = get_pg_connection()
        cur = conn.cursor()
        cur.execute('''
            UPDATE orders
            SET
                product = %s,
                quantity = %s,
                unit_price = %s,
                price = %s, 
                address = %s,
                phone = %s,
                payment = %s
            WHERE order_key = %s AND user_id = %s
        ''', (
            order["product"],
            order["quantity"],
            order["unit_price"],
            order["price"],
            order["address"],
            order["phone"],
            order["payment"],
            order_key,
            user_id
        ))
        conn.commit()
        cur.close()
        conn.close()

        user_states.pop(user_id)
        return (
            f"✅ Order `{order_key}` updated successfully!\n"
            f"📦 Product: {order['product']}\n"
            f"🔢 Quantity: {order['quantity']} x ₱{order['unit_price']:.2f}\n"
            f"💰 Total: ₱{order['price']:.2f}\n"
            f"📍 Address: {order['address']}\n"
            f"📞 Phone: {order['phone']}\n"
            f"💳 Payment: {order['payment']}"
        )
    elif state["step"] == "awaiting_confirm":
        if msg.strip().lower() == "yes" or msg.strip().lower() == "y":
            order = state["order"]
            order_key = save_order(user_id, order)
            user_states.pop(user_id, None)
            return (
                f"✅ Order confirmed!\n\n"
                f"🆔 Order Key: {order_key}\n"
                f"📦 Product: {order['product']}\n"
                f"🔢 Quantity: {order['quantity']} x ₱{order['unit_price']:.2f}\n"
                f"💰 Total: ₱{order['price']:.2f}\n"
                f"👤 Name: {order['name']}\n"
                f"📍 Address: {order['address']}\n"
                f"📞 Phone: {order['phone']}\n"
                f"💳 Payment: {order['payment']}\n\n"
                f"❌ Cancel: Gusto po i-cancel? Send >> *cancel {order_key}*\n"
                f"✏️ Edit: May babaguhin po? Send >> *edit {order_key}*"
            )
        else:
            # Let user change cached details if they said something other than "yes"
            user_states[user_id]["step"] = "ask_name"
            return "✏️ No problem! Let's update your info.\nPlease enter your *full name*:"

    elif state["step"] == "ask_name":
        name = msg.strip()
        if not is_full_name(name):
            return "❌ Please enter your **full name** (e.g., Maria Clara Reyes)."
        
        state["order"]["name"] = name
        state["step"] = "awaiting_address"
        return "📍 Thank you! Now, please enter your *delivery address*:"
    elif state["step"] == "awaiting_address":
        state["order"]["address"] = msg
        state["step"] = "awaiting_phone"
        return "Noted. What's your *phone number*?"
    elif state["step"] == "awaiting_phone":
        state["order"]["phone"] = msg
        state["step"] = "awaiting_payment"
        return "*Mode Of Payment* Gcash, Maya, Bank, Cash, COD"
    elif state["step"] == "awaiting_payment":
        state["order"]["payment"] = msg
        order = state["order"]
        order_key = save_order(user_id, order)
        save_user_profile(user_id, order["name"], order["address"], order["phone"], order["payment"])
        user_states.pop(user_id)
        return (
            f"✅ Order confirmed!\n\n"
            f"🆔 Order Key: {order_key}\n"
            f"📦 Product: {order['product']}\n"
            f"🔢 Quantity: {order['quantity']} x ₱{order['unit_price']:.2f}\n"
            f"💰 Total: ₱{order['price']:.2f}\n"
            f"👤 Name: {order['name']}\n"
            f"📍 Address: {order['address']}\n"
            f"📞 Phone: {order['phone']}\n"
            f"💳 Payment: {order['payment']}\n\n"
            f"❌ Cancel: Gusto po i-cancel? Send >> *cancel {order_key}*\n"
            f"✏️ Edit: May babaguhin po sa product o price? Send >> *edit {order_key}*\n"
        )
    else:
        user_states.pop(user_id, None)
        return "Oops, something went wrong. Let's start over. Please send your order again."

def get_user_profile(user_id):
    conn = get_pg_connection()
    cur = conn.cursor()
    cur.execute("SELECT name, address, phone, payment FROM user_profiles WHERE user_id = %s", (user_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result if result else None

def generate_order_key():
    return str(uuid.uuid4())[:8]  # short, user-friendly ID (8 chars)

def save_user_profile(user_id, name, address, phone, payment):
    conn = get_pg_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO user_profiles (user_id, name, address, phone, payment)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            name = EXCLUDED.name,
            address = EXCLUDED.address,
            phone = EXCLUDED.phone,
            payment = EXCLUDED.payment
    """, (user_id, name, address, phone, payment))
    conn.commit()
    cur.close()
    conn.close()

def save_order(user_id, order):
    ref_code = order.get("ref_code") or user_states.get(user_id, {}).get("ref_code")
    order["ref_code"] = ref_code  # ✅ Ensure it's saved in the dict

    order_key = generate_order_key()
    logging.info(f"Saving order for user {user_id} with key {order_key} and ref_code {ref_code}")

    conn = get_pg_connection()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO orders (user_id, seller, product, price, name, address, phone, payment, quantity, unit_price, order_key, ref_code)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ''', (
        user_id,
        order["seller"],
        order["product"],
        order["price"],
        order["name"],
        order["address"],
        order["phone"],
        order["payment"],
        order["quantity"],
        order["unit_price"],
        order_key,
        order["ref_code"]  # ✅ Now guaranteed to exist
    ))
    conn.commit()
    cur.close()
    conn.close()
    logging.info(f"[Order] {user_id} placed order to #{order['ref_code']} for {order['product']}")
    return order_key



def send_message(recipient_id, message_text):
    url = "https://graph.facebook.com/v23.0/me/messages"
    headers = {"Content-Type": "application/json"}
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": message_text}
    }
    params = {"access_token": PAGE_ACCESS_TOKEN}
    res = requests.post(url, headers=headers, params=params, json=payload)
    if res.status_code != 200:
        print("Failed to send message:", res.text)

#invoice
def generate_invoice_for_sender(user_id, orders):
    if not orders:
        return "📭 You don't have any orders yet."

    invoice_lines = ["🧾 *Your Invoice Summary:*"]
    total = 0

    for idx, order in enumerate(orders, start=1):
        order_key, product, quantity, unit_price, price, address, phone, payment, created_at = order
        total += float(price)

        ph_tz = timezone('Asia/Manila')

        invoice_lines.append(
            f"\n📦 {idx}. {product}\n"
            f"🔢 Qty: {quantity} x ₱{unit_price:.2f} = ₱{price:.2f}\n"
            f"🆔 Key: {order_key}\n"
            f"📍 {address}\n"
            f"📞 {phone} | 💳 {payment}\n"
            f"🕒 {created_at.astimezone(ph_tz).strftime('%B-%d-%y %H:%M')}"
        )

    invoice_lines.append(f"\n🧮 *Total Amount: ₱{total:.2f}*")
    invoice_lines.append("✏️ To edit: *edit ORDERKEY*")
    invoice_lines.append("❌ To cancel: *cancel ORDERKEY*")

    return "\n".join(invoice_lines)


def get_orders_by_sender(user_id, override_ref_code=None):
    state = user_states.get(user_id, {})
    ref_code = override_ref_code or state.get("ref_code")

    conn = get_pg_connection()
    cur = conn.cursor()

    if not ref_code:
        # Fallback: fetch from users table
        cur.execute("SELECT ref_code FROM users WHERE fb_id = %s", (user_id,))
        row = cur.fetchone()

        if row and row[0]:
            ref_code = row[0]
            user_states[user_id] = {"ref_code": ref_code}
        else:
            cur.close()
            conn.close()
            return []

    # Now get the orders for this user + specific store (ref_code)
    cur.execute("""
        SELECT order_key, product, quantity, unit_price, price, address, phone, payment, created_at
        FROM orders
        WHERE user_id = %s AND ref_code = %s
        ORDER BY created_at DESC
    """, (user_id, ref_code))
    orders = cur.fetchall()

    cur.close()
    conn.close()
    return orders




def save_ref_code_to_db(user_id, ref_code):
    try:
        conn = get_pg_connection()
        cur = conn.cursor()
        cur.execute("SELECT ref_code FROM users WHERE fb_id = %s", (user_id,))
        row = cur.fetchone()
        if row is None:
            cur.execute("INSERT INTO users (fb_id, ref_code) VALUES (%s, %s)", (user_id, ref_code))
        elif not row[0] or row[0] != ref_code:
            cur.execute("UPDATE users SET ref_code = %s WHERE fb_id = %s", (ref_code, user_id))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"[DB] Error saving ref_code for {user_id}: {e}")


# 📊 Public View 
@app.route('/viewer_dashboard')
def viewer_dashboard():
    # Connect to your database
    conn = get_pg_connection()
    cur = conn.cursor()

    # Fetch all orders
    cur.execute("SELECT * FROM orders ORDER BY created_at DESC")
    orders = cur.fetchall()
    conn.close()

    # Convert UTC to Philippine Time
    ph_tz = timezone('Asia/Manila')
    orders_with_local_time = []
    for order in orders:
        order_dict = {
            "id": order[0],
            "user_id": order[1],
            "seller": order[2],
            "product": order[3],
            "payment": order[7],
            "price": order[8],
            "quantity": order[9],
            "unit_price": order[10],
            "created_at": order[11].astimezone(ph_tz),
            "order_key": order[12],
        }
        orders_with_local_time.append(order_dict)

    return render_template('viewer_dashboard.html', orders=orders_with_local_time, seller='Public')
# Seller Dashboard
@app.route('/')
def dashboard():
    seller = session.get("seller")
    if not seller:
        return redirect(url_for('viewer_dashboard'))

    conn = get_pg_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE seller = %s ORDER BY id DESC", (seller,))
    orders = cur.fetchall()
    cur.close()
    conn.close()

    # Convert UTC to Philippine time
    ph_tz = timezone('Asia/Manila')
    orders_with_local_time = []
    for order in orders:
        order_dict = {
            "id": order[0],
            "user_id": order[1],
            "seller": order[2],
            "product": order[3],
            "name": order[4],
            "address": order[5],
            "phone": order[6],
            "payment": order[7],
            "price": order[8],
            "quantity": order[9],
            "unit_price": order[10],
            "created_at": order[11].astimezone(ph_tz),
            "order_key": order[12],
        }
        orders_with_local_time.append(order_dict)

    return render_template("dashboard.html", orders=orders_with_local_time, seller=seller)

    

#delete data for 7 days scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(delete_old_orders, 'interval', days=1)  # run daily
scheduler.start()

# Start the app
if __name__ == '__main__':
    delete_old_orders()  # cleanup on startup
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
