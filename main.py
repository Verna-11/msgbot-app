from flask import Flask, request
import requests

app = Flask(__name__)

VERIFY_TOKEN = 'test123'
PAGE_ACCESS_TOKEN = 'EAARsLYLElpcBPG0EiUlS1oCX7sl8RFInZClq7R8uY9XGT2ZBPVJ3bllj9WHXyb7bebxdAm6PPTfbLpmmv4fzjP9ouF58IxOU5xt0zZAOZBkNJvJrY7pwt2F65FYO45OMQoVKgMQLUFhBGq8jDxLFf4YIZAKGjs51KJdIF4aMhlQbnc0eg19UR2nYjtasm8OfxURXx8QZDZD'

@app.route('/', methods=['GET'])
def verify():
    # Verification handshake with Facebook
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge"), 200
    return "Verification failed", 403

@app.route('/', methods=['POST'])
def webhook():
    data = request.get_json()
    print("Incoming webhook data:", data)  # ✅ Add this line

    for entry in data.get("entry", []):
        for messaging_event in entry.get("messaging", []):
            sender_id = messaging_event["sender"]["id"]
            print("📨 Message from:", sender_id)  # ✅ Log sender

            if "message" in messaging_event:
                print("🧠 Received message:", messaging_event["message"].get("text"))
                send_message(sender_id, "Hi there! 👋 This is a test bot.")
    return "okay", 200


def send_message(recipient_id, message_text):
    url = "https://graph.facebook.com/v19.0/me/messages"
    params = {"access_token": PAGE_ACCESS_TOKEN}
    data = {
        "recipient": {"id": recipient_id},
        "message": {"text": message_text}
    }
    response = requests.post(url, params=params, json=data)
    print("Facebook response:", response.status_code, response.text)  # ✅ ADDED


if __name__ == "__main__":
    app.run(port=5000, debug=True)
