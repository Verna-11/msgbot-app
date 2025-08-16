import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, request, render_template,session, redirect, url_for, flash, send_file
import io
import xlsxwriter
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import re
import os
from dotenv import load_dotenv
import uuid
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.errors import UniqueViolation
from pytz import timezone, utc
from supabase import create_client, Client



load_dotenv()

app = Flask(__name__)


PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

DATABASE_URL = os.environ.get("SUPABASE_DB_URL")  # use your Supabase connection string

app.secret_key = os.environ.get("SECRET_KEY")

user_states = {}


logging.basicConfig(
    level=logging.INFO, # logging for debugging DEBUG
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
    )


@app.route("/privacy")
def privacy():
    return """
    <h1>Privacy Policy</h1>
    <p>This app does not collect personal information beyond what is needed for order processing and communication through Facebook Messenger. We do not share your data with third parties.</p>
    """

@app.route("/terms")
def terms():
    return """
    <h1>Terms of Service</h1>
    <p>By using this app, you agree to allow us to manage your order information for the purpose of sales tracking and customer support.</p>
    """

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

        try:
            # Check if seller or email already exists
            existing = supabase.table("sellers").select("*").or_(f"seller.eq.{seller},email.eq.{email}").execute()

            if len(existing.data) > 0:
                flash('Seller or email already exists.', 'danger')
                return render_template('register.html')

            # Insert new seller
            supabase.table("sellers").insert({
                "seller": seller,
                "password": hashed_password,
                "email": email
            }).execute()

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

        try:
            # Query seller record
            result = supabase.table("sellers").select("password").eq("seller", seller).execute()

            if result.data and check_password_hash(result.data[0]['password'], password):
                session['seller'] = seller
                flash("Login successful.", "success")
                return redirect(url_for('dashboard'))
            else:
                flash("Invalid credentials.", "danger")

        except Exception as e:
            print("Error:", e)
            flash("Login failed. Please try again later.", "danger")

    return render_template('login.html')



@app.route('/logout')
def logout():
    session.pop('seller', None)
    flash("Logged out.", "info")
    return redirect(url_for('login'))

#test route for deleting orders older than 1 day


@app.route('/connect_page')
def connect_page():
    fb_app_id = os.getenv("FB_APP_ID")
    redirect_uri = url_for('fb_callback', _external=True)
    return redirect(
        f"https://www.facebook.com/v23.0/dialog/oauth?client_id={fb_app_id}&redirect_uri={redirect_uri}&scope=pages_manage_metadata,pages_messaging,pages_read_engagement,pages_show_list&response_type=code"
    )


@app.route('/fb_callback')
def fb_callback():
    fb_app_id = os.getenv("FB_APP_ID")
    fb_app_secret = os.getenv("FB_APP_SECRET")
    code = request.args.get("code")
    redirect_uri = url_for('fb_callback', _external=True)

    if not code:
        return "Missing authorization code from Facebook", 400

    # Exchange code for short-lived access token
    token_res = requests.get(
        "https://graph.facebook.com/v23.0/oauth/access_token",
        params={
            "client_id": fb_app_id,
            "redirect_uri": redirect_uri,
            "client_secret": fb_app_secret,
            "code": code
        }
    ).json()

    if 'access_token' not in token_res:
        return f"Failed to get access token: {token_res}", 400

    short_token = token_res['access_token']

    # Exchange for long-lived token
    long_token_res = requests.get(
        "https://graph.facebook.com/v23.0/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": fb_app_id,
            "client_secret": fb_app_secret,
            "fb_exchange_token": short_token
        }
    ).json()

    long_token = long_token_res.get("access_token")
    if not long_token:
        return f"Failed to get long-lived token: {long_token_res}", 400

    # Fetch user pages
    pages_res = requests.get(
        "https://graph.facebook.com/v19.0/me/accounts",
        params={"access_token": long_token}
    ).json()

    pages = pages_res.get("data", [])

    # Optional: Save token and page info to DB (you can implement this later)
    return {
        "message": "Successfully connected to Facebook.",
        "long_lived_token": long_token,
        "pages": pages
    }

#edit button route
@app.route("/update_order/<order_key>", methods=["POST"])
def update_order(order_key):
    seller = session.get("seller")
    if not seller:
        flash("You must be logged in to edit orders.", "danger")
        return redirect(url_for("login"))

    product = request.form.get("product")
    quantity = request.form.get("quantity", type=int)
    unit_price = request.form.get("unit_price", type=float)
    address = request.form.get("address")
    phone = request.form.get("phone")
    payment = request.form.get("payment")

    price = quantity * unit_price if quantity and unit_price else None

    try:
        # Use Supabase update query
        result = supabase.table("orders").update({
            "product": product,
            "quantity": quantity,
            "unit_price": unit_price,
            "price": price,
            "address": address,
            "phone": phone,
            "payment": payment
        }).eq("order_key", order_key).eq("seller", seller).execute()

        if result.data:
            flash(f"Order {order_key} updated successfully.", "success")
        else:
            flash("Order not found or update failed.", "danger")

    except Exception as e:
        print("Error updating order:", e)
        flash("Something went wrong while updating the order.", "danger")

    return redirect(url_for("dashboard"))


#connecting to postgres
def get_pg_connection():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

# Define scheduler globally
scheduler = BackgroundScheduler()
# Delete old orders for a specific seller
# --------------------
def delete_old_orders_for_seller(seller_name):
    one_day_ago_utc = datetime.now(timezone.utc) - timedelta(days=1)
    print(f"[Scheduler] Deleting orders before: {one_day_ago_utc} for seller: {seller_name}")

    try:
        # 1. Find orders that will be deleted
        old_orders = supabase.table("orders") \
            .select("id") \
            .lt("created_at", one_day_ago_utc.isoformat()) \
            .eq("seller", seller_name) \
            .execute()

        deleted_ids = [order["id"] for order in old_orders.data]

        # 2. Delete them
        if deleted_ids:
            supabase.table("orders") \
                .delete() \
                .lt("created_at", one_day_ago_utc.isoformat()) \
                .eq("seller", seller_name) \
                .execute()

        return len(deleted_ids)

    except Exception as e:
        print("Error deleting old orders:", e)
        return 0

# --------------------
# Delete old orders for ALL sellers (for scheduler)
# --------------------
def delete_old_orders_all_sellers():
    try:
        # 1. Get all distinct sellers
        result = supabase.table("orders").select("seller").execute()
        sellers = list({row["seller"] for row in result.data if row.get("seller")})

        # 2. Loop through each seller and clean up
        for seller in sellers:
            count = delete_old_orders_for_seller(seller)
            print(f"[Scheduler] Deleted {count} old orders for seller: {seller}")

    except Exception as e:
        print("Error fetching sellers:", e)


# --------------------
# Manual delete for logged-in seller
# --------------------
@app.route("/test-delete")
def test_delete():
    seller = session.get("seller")
    if not seller:
        return "You must be logged in as a seller", 403
    count = delete_old_orders_for_seller(seller)
    return f"Deleted {count} old orders for seller {seller}"

# --------------------
# Download old orders in Excel for logged-in seller
# --------------------

@app.route("/clear_orders", methods=["POST"])
def clear_orders():
    seller = session.get("seller")
    if not seller:
        flash("Not logged in.")
        return redirect(url_for("login"))

    try:
        # Delete all orders for this seller
        result = supabase.table("orders").delete().eq("seller", seller).execute()

        # Count how many were deleted
        deleted_count = len(result.data) if result.data else 0

        flash(f"✅ Cleared {deleted_count} orders for seller {seller}.")
    except Exception as e:
        print("Error clearing orders:", e)
        flash("⚠️ Failed to clear orders. Please try again.", "danger")

    return redirect(url_for("dashboard", seller=seller))


#invoice in pdf route
@app.route("/buyer/<buyer_name>")
def buyer_invoice(buyer_name):
    seller = session.get("seller")
    if not seller:
        flash("You must be logged in.", "danger")
        return redirect(url_for("login"))

    try:
        # Query orders for this buyer and seller
        result = (
            supabase.table("orders")
            .select("order_key, product, quantity, unit_price, price, payment, created_at")
            .eq("name", buyer_name)
            .eq("seller", seller)
            .order("created_at", desc=False)  # ASC
            .execute()
        )

        orders = result.data if result.data else []

        return render_template(
            "buyer_invoice.html",
            buyer=buyer_name,
            orders=orders,
            seller=seller
        )
    except Exception as e:
        print("Error fetching buyer invoice:", e)
        flash("⚠️ Could not load buyer invoice.", "danger")
        return redirect(url_for("dashboard"))

#all buyers excel invoices
@app.route("/download_all_invoices_excel")
def download_all_invoices_excel():
    seller = session.get("seller")
    if not seller:
        return "Unauthorized", 401

    try:
        # 1. Get distinct buyers for this seller
        buyers_result = (
            supabase.table("orders")
            .select("name")
            .eq("seller", seller)
            .order("name")
            .execute()
        )

        buyers = sorted(set(row["name"] for row in buyers_result.data if row["name"]))

        # 2. Create Excel file in memory
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        for buyer in buyers:
            sheet_name = buyer[:31] if buyer else "Unknown"
            worksheet = workbook.add_worksheet(sheet_name)

            # 3. Fetch buyer orders
            orders_result = (
                supabase.table("orders")
                .select("order_key, product, quantity, unit_price, price, payment, created_at")
                .eq("seller", seller)
                .eq("name", buyer)
                .order("created_at")
                .execute()
            )

            orders = orders_result.data if orders_result.data else []

            headers = ["Order Key", "Product", "Qty", "Unit Price", "Total", "Payment", "Date"]
            for col, header in enumerate(headers):
                worksheet.write(0, col, header)

            total = 0
            for row_num, order in enumerate(orders, start=1):
                values = [
                    order.get("order_key"),
                    order.get("product"),
                    order.get("quantity"),
                    order.get("unit_price"),
                    order.get("price"),
                    order.get("payment"),
                    order.get("created_at"),
                ]

                for col_num, value in enumerate(values):
                    if col_num == 6 and value:  # Format created_at
                        try:
                            value = datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
                        except Exception:
                            pass
                    worksheet.write(row_num, col_num, str(value) if value is not None else "")

                if order.get("price"):
                    try:
                        total += float(order["price"])
                    except ValueError:
                        pass

            worksheet.write(len(orders) + 1, 3, "Grand Total")
            worksheet.write(len(orders) + 1, 4, total)

        # 4. Finalize and return file
        workbook.close()
        output.seek(0)

        filename = f"All_Buyers_Invoices_{seller}.xlsx"
        return send_file(output, download_name=filename, as_attachment=True)

    except Exception as e:
        print("Error generating Excel:", e)
        return "Error generating Excel file", 500


# Change your scheduler job to:

scheduler = BackgroundScheduler(timezone=utc)
scheduler.add_job(delete_old_orders_all_sellers, 'interval', days=1)
scheduler.start()
#data base connection and commit

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def init_pg():
    # Just test connection now
    try:
        supabase.table("orders").select("*").limit(1).execute()
        print("✅ Supabase connected, tables are ready.")
    except Exception as e:
        print("❌ Error:", e)


# ✅ Messenger Webhook
@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        if request.args.get("hub.verify_token") == VERIFY_TOKEN:
            return request.args.get("hub.challenge")
        return "Invalid token"

    data = request.get_json()
    logging.info(f"Received Data: {data}")

    #finding ref tag
    for entry in data["entry"]:
        for event in entry["messaging"]:
            if "referral" in event:
                ref_code = event["referral"].get("ref")
                user_id = event["sender"]["id"]
                handle_referral(user_id, ref_code)
                return "ok", 200

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
                    # Check if user exists
                    existing = supabase.table("users").select("ref_code").eq("fb_id", sender_id).execute()
                
                    if not existing.data:
                        supabase.table("users").insert({"fb_id": sender_id, "ref_code": ref_code}).execute()
                        logging.info(f"Inserted new user {sender_id} with ref_code {ref_code}")
                    elif not existing.data[0].get("ref_code"):
                        supabase.table("users").update({"ref_code": ref_code}).eq("fb_id", sender_id).execute()
                        logging.info(f"Updated user {sender_id} with ref_code {ref_code}")
                except Exception as e:
                    logging.error(f"Supabase Error: {e}")

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
            seller = match.group(1)
        else:
            return "⚠️ Please include the store name like `invoice #storeb`."
    
        orders = get_orders_by_sender(user_id, seller)
        
        if not orders:
            return f"📭 You have no orders for store `#{seller}`."
    
        invoice_message = generate_invoice_for_sender(user_id, orders)
        return invoice_message




    if msg.lower().startswith("edit"):
        parts = msg.split(" ", 1)
        if len(parts) != 2 or not parts[1].strip():
            return "❌ Please provide a valid order key to edit. Example: *edit abcd1234*"
        
        key = parts[1].strip()
    
        # 🔄 Query Supabase instead of psycopg2
        response = (
            supabase.table("orders")
            .select("product, quantity, unit_price, address, phone, payment")
            .eq("order_key", key)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
    
        if response.data:
            order = response.data[0]
            product = order["product"]
            quantity = order["quantity"]
            unit_price = float(order["unit_price"])
            address = order["address"]
            phone = order["phone"]
            payment = order["payment"]
    
            user_states[user_id] = {
                "step": "edit_product",
                "edit_key": key,
                "order": {
                    "product": product,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "price": unit_price * int(quantity),
                    "address": address,
                    "phone": phone,
                    "payment": payment
                }
            }
    
            return (
                f"📝 Editing order `{key}` for '{product}'.\n"
                f"Current product: {product}, Qty: {quantity}, Unit Price: ₱{unit_price:.2f}\n\n"
                f"✏️ Please send the new *product name/description*:"
            )
        else:
            return f"⚠️ *No order found* with key `{key}` that belongs to you."

    if msg.lower().startswith("cancel"):
        parts = msg.split(" ", 1)
        if len(parts) != 2 or not parts[1].strip():
            return "❌ Please provide a valid *order key*. Example: *cancel abcd1234*"
    
        key = parts[1].strip().lower()
    
        # 🔎 Check if the order exists
        response = (
            supabase.table("orders")
            .select("id")
            .eq("order_key", key)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
    
        if response.error:
            logging.error(f"Supabase error: {response.error}")
            return "⚠️ Something went wrong while checking your order."
    
        if response.data:
            order_id = response.data[0]["id"]
    
            # 🗑️ Delete the order
            delete_response = (
                supabase.table("orders")
                .delete()
                .eq("id", order_id)
                .execute()
            )
    
            if delete_response.error:
                logging.error(f"Supabase delete error: {delete_response.error}")
                return "⚠️ Failed to cancel your order. Please try again later."
    
            return f"✅ Your order with key *`{key}`* has been *canceled.*"
        else:
            return f"⚠️ Order key *`{key}`* was not *found* or does not *belong* to you."
    
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
                response = (
                    supabase.table("users")
                    .select("ref_code")
                    .eq("fb_id", user_id)
                    .limit(1)
                    .execute()
                )
            
                if response.data and response.data[0].get("ref_code"):
                    seller_tag = response.data[0]["ref_code"]
                    user_states[user_id] = {"ref_code": seller_tag}

                else:
                    user_states.pop(user_id, None)
                    return (
                        f"⚠️ Sorry, I can't determine your store. Please include *#storename* in your message.\n"
                        f"example #teststore bag 100 \n"
                        f"example #teststore bag 2x"
                        f"example bag 100 #teststore"
                        )

        clean_msg = re.sub(r'#\w+', '', msg).strip()

        # Reject messages that are unclear (price-only, one word, or one character)
        if (
            re.fullmatch(r'₱?\d+(\.\d{1,2})?', clean_msg)  # Only a number or price
            or len(clean_msg.split()) == 1                 # Only one word
            or len(clean_msg) == 1                         # Only one character
        ):
            return "❌ I didn't understand your order. Please order like: Bag 100 or Bag 100 x2"
        
        product_text = clean_msg
        
        # Format: ₱100 x2 or 100 x2
        match_price_qty = re.search(r'₱?(\d+(\.\d{1,2})?)\s*[xX](\d+)', product_text)
        
        # Match formats like: 2x100, 2 x100, 2 x 100, 2x₱100.00
        match_qty_price1 = re.search(r'(\d+)\s*[xX]\s*₱?(\d+(\.\d{1,2})?)', product_text)
        
        # Match formats like: x2 100 or x2 ₱100
        match_qty_price2 = re.search(r'[xX](\d+)\s*₱?(\d+(\.\d{1,2})?)', product_text)

        # Match single price anywhere: e.g., "Gloves 20" or "Pen ₱15.50"
        match_single_price = re.search(r'₱?(\d+(\.\d{1,2})?)', product_text)

        # Format: ₱100 2x or 100 2x
        match_price_qty_reverse = re.search(r'₱?(\d+(\.\d{1,2})?)\s*(\d+)[xX]', product_text)

        
        if match_price_qty:
            unit_price = float(match_price_qty.group(1))
            quantity = int(match_price_qty.group(3))
            total_price = quantity * unit_price
            product = product_text.replace(match_price_qty.group(0), '').strip()

        elif match_qty_price1:
            quantity = int(match_qty_price1.group(1))
            unit_price = float(match_qty_price1.group(2))
            total_price = quantity * unit_price
            product = product_text.replace(match_qty_price1.group(0), '').strip()

        elif match_qty_price2:
            quantity = int(match_qty_price2.group(1))
            unit_price = float(match_qty_price2.group(2))
            total_price = quantity * unit_price
            product = product_text.replace(match_qty_price2.group(0), '').strip()


        elif match_price_qty_reverse:
            unit_price = float(match_price_qty_reverse.group(1))
            quantity = int(match_price_qty_reverse.group(3))
            total_price = quantity * unit_price
            product = product_text.replace(match_price_qty_reverse.group(0), '').strip()
        # Match single price anywhere: e.g., "Gloves 20" or "Pen ₱15.50"
        elif match_single_price:
            quantity = 1
            unit_price = float(match_single_price.group(1))
            total_price = unit_price
            product = product_text.replace(match_single_price.group(0), '').strip()

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
                f"✅ Send *yes or no* to confirm"
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
            return (
                f"Thanks for your order for *'{product}'* from seller *#{seller_tag}.*\n"
                "May I have your *full name*?"
            )
        
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
            return "⚠️ Please enter a valid number for *quantity*."
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
    
        try:
            supabase.table("orders").update({
                "product": order["product"],
                "quantity": order["quantity"],
                "unit_price": order["unit_price"],
                "price": order["price"],
                "address": order["address"],
                "phone": order["phone"],
                "payment": order["payment"],
            }).eq("order_key", order_key).eq("user_id", user_id).execute()
    
        except Exception as e:
            logging.error(f"[DB] Error updating order {order_key} for {user_id}: {e}")
    

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
                f"✅ *Order confirmed!*\n\n"
                f"🏪 Store: {order['seller']}\n"
                f"🆔 Order Key: {order_key}\n"
                f"📦 Product: {order['product']}\n"
                f"🔢 Quantity: {order['quantity']} x ₱{order['unit_price']:.2f}\n"
                f"💰 Total: ₱{order['price']:.2f}\n"
                f"👤 Name: {order['name']}\n"
                f"📍 Address: {order['address']}\n"
                f"📞 Phone: {order['phone']}\n"
                f"💳 Payment: {order['payment']}\n\n"
                f"🖥️ Dashboard: https://anrev.onrender.com\n"
                f"👍 *Like our page for updates!*"
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
            f"✅ *Order confirmed!*\n\n"
            f"🏪 Store: {order['seller']}\n"
            f"🆔 Order Key: {order_key}\n"
            f"📦 Product: {order['product']}\n"
            f"🔢 Quantity: {order['quantity']} x ₱{order['unit_price']:.2f}\n"
            f"💰 Total: ₱{order['price']:.2f}\n"
            f"👤 Name: {order['name']}\n"
            f"📍 Address: {order['address']}\n"
            f"📞 Phone: {order['phone']}\n"
            f"💳 Payment: {order['payment']}\n\n"
            f"🖥️ Dashboard: https://anrev.onrender.com\n"
            f"👍 *Like our page for updates!*"
        )

    else:
        user_states.pop(user_id, None)
        return "Oops, something went wrong. Let's start over. Please send your order again."

def get_user_profile(user_id):
    response = (
        supabase.table("user_profiles")
        .select("name, address, phone, payment")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )

    if response.data:
        return response.data[0]  # returns dict: {"name": ..., "address": ..., ...}
    return None


def generate_order_key():
    return str(uuid.uuid4())[:8]  # short, user-friendly ID (8 chars)

def save_user_profile(user_id, name, address, phone, payment):
    data = {
        "user_id": user_id,
        "name": name,
        "address": address,
        "phone": phone,
        "payment": payment
    }

    response = (
        supabase.table("user_profiles")
        .upsert(data, on_conflict="user_id")  # works like INSERT ... ON CONFLICT (user_id) DO UPDATE
        .execute()
    )

    return response.data  # optional: returns the inserted/updated row(s)


def save_order(user_id, order):
    order["ref_code"] = order["seller"]  # ✅ enforce always

    order_key = generate_order_key()
    logging.info(f"Saving order for user {user_id} with key {order_key} and ref_code {order['ref_code']}")

    data = {
        "user_id": user_id,
        "seller": order["seller"],
        "product": order["product"],
        "price": order["price"],
        "name": order["name"],
        "address": order["address"],
        "phone": order["phone"],
        "payment": order["payment"],
        "quantity": order["quantity"],
        "unit_price": order["unit_price"],
        "order_key": order_key,
        "ref_code": order["ref_code"],
    }

    response = supabase.table("orders").insert(data).execute()

    if response.data:
        logging.info(f"[Order] {user_id} placed order to #{order['ref_code']} for {order['product']}")
        return order_key
    else:
        logging.error(f"❌ Failed to save order for {user_id}: {response}")
        return None




def chunk_text(text, max_len=2000):
    lines = text.split('\n')
    chunks = []
    current = ''
    for line in lines:
        # Add line only if it doesn't exceed the limit
        if len(current) + len(line) + 1 > max_len:
            chunks.append(current.strip())
            current = ''
        current += line + '\n'
    if current:
        chunks.append(current.strip())
    return chunks


def send_message(recipient_id, message_text):
    url = "https://graph.facebook.com/v23.0/me/messages"
    headers = {"Content-Type": "application/json"}
    params = {"access_token": PAGE_ACCESS_TOKEN}

    # Split into safe chunks
    message_chunks = chunk_text(message_text)

    for chunk in message_chunks:
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": chunk}
        }
        res = requests.post(url, headers=headers, params=params, json=payload)
        if res.status_code != 200:
            print("Failed to send message chunk:", res.text)

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
    invoice_lines.append("Dashboard: https://anrev.onrender.com")
    invoice_lines.append(f"*Like our page for updates*")

    return "\n".join(invoice_lines)

def get_orders_by_sender(user_id, seller):
    response = (
        supabase.table("orders")
        .select("order_key, product, quantity, unit_price, price, address, phone, payment, created_at")
        .eq("user_id", user_id)
        .eq("seller", seller)
        .order("created_at", desc=True)
        .execute()
    )

    return response.data if response.data else []


def save_ref_code_to_db(user_id, ref_code):
    try:
        # Check if user already exists
        response = (
            supabase.table("users")
            .select("ref_code")
            .eq("fb_id", user_id)
            .execute()
        )

        if not response.data:  
            # No row → insert new
            supabase.table("users").insert({
                "fb_id": user_id,
                "ref_code": ref_code
            }).execute()

        elif not response.data[0].get("ref_code") or response.data[0]["ref_code"] != ref_code:
            # Row exists but ref_code missing or different → update
            supabase.table("users").update({
                "ref_code": ref_code
            }).eq("fb_id", user_id).execute()

    except Exception as e:
        logging.error(f"[DB] Error saving ref_code for {user_id}: {e}")


# 📊 Public View 
@app.route('/viewer_dashboard')
def viewer_dashboard():
    try:
        # Fetch all orders sorted by newest first
        response = supabase.table("orders") \
            .select("*") \
            .order("created_at", desc=True) \
            .execute()

        orders = response.data if response.data else []

        return render_template("viewer_dashboard.html", orders=orders)

    except Exception as e:
        logging.error(f"[Viewer Dashboard] Failed to fetch orders: {e}")
        return render_template("viewer_dashboard.html", orders=[])


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
        return redirect(url_for("viewer_dashboard"))

    # 🔄 Supabase query instead of psycopg2
    response = (
        supabase.table("orders")
        .select("*")
        .eq("seller", seller)
        .order("id", desc=True)
        .execute()
    )

    orders = response.data if response.data else []

    return render_template("dashboard.html", seller=seller, orders=orders)


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

    

