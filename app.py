from flask import Flask, request, jsonify, session
from flask_session import Session
from filters import is_offensive
from dialogue_script import get_fallback_response
from log_user import log_message
import json, os

app = Flask(__name__)
app.secret_key = "super_secret_key"
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

chat_logs = {}
USERS_FILE = "users.json"
if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, "w") as f:
        json.dump({}, f)

def load_users():
    with open(USERS_FILE, "r") as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

@app.route("/login", methods=["POST"])
def login():
    username = request.json.get("username").strip().lower()
    if not username:
        return jsonify({"error": "Username is required."}), 400

    users = load_users()
    if username not in users:
        users[username] = {"created": True}
        save_users(users)

    session["username"] = username
    if username not in chat_logs:
        chat_logs[username] = []

    return jsonify({"message": f"Welcome {username}!"})

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Logged out."})

@app.route("/chat", methods=["POST"])
def chat():
    username = session.get("username")
    if not username:
        return jsonify({"error": "Login required"}), 403

    user_input = request.json.get("message")
    if is_offensive(user_input):
        response = "Let’s keep things respectful. I'm here to help."
    else:
        # Temporarily use fallback until DialoGPT or lightweight chatbot is added
        response = get_fallback_response()

    chat_logs[username].append((user_input, response))
    log_message(user_input, response)
    return jsonify({"response": response})

@app.route("/history", methods=["GET"])
def history():
    username = session.get("username")
    if not username:
        return jsonify({"error": "Login required"}), 403
    return jsonify({"username": username, "history": chat_logs.get(username, [])})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 7860)))

