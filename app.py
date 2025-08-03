from flask import Flask, request, jsonify, session, send_from_directory
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
import json
import uuid
import re
import random
import secrets
import threading
import subprocess
import sys
from datetime import datetime
from functools import wraps
import spacy
import logging
import base64
from dotenv import load_dotenv
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="frontend", static_url_path="")

# Secure configuration for SECRET_KEY
def get_secret_key():
    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        if os.environ.get('FLASK_ENV') == 'development':
            logger.warning("Using a temporary development secret key. Set SECRET_KEY in .env for production.")
            return 'dev-secret-key-not-for-production'
        raise ValueError("SECRET_KEY must be set in environment variables for production")
    return secret_key

app.secret_key = get_secret_key()

# --- START: Session and CORS Configuration ---

IS_DEPLOYED = "SPACE_ID" in os.environ

if IS_DEPLOYED:
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_SAMESITE='None',
        SESSION_COOKIE_HTTPONLY=True,
        PERMANENT_SESSION_LIFETIME=3600
    )
else: 
    app.config.update(
        SESSION_COOKIE_SECURE=False,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_HTTPONLY=True,
        PERMANENT_SESSION_LIFETIME=3600
    )

allowed_origins = []
if IS_DEPLOYED:
    space_host = os.environ.get("SPACE_HOST")
    if space_host:
        allowed_origins.append(f"https://{space_host}")
else:
    local_origin = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000")
    allowed_origins.append(local_origin)

CORS(
    app,
    supports_credentials=True,
    resources={
        r"/api/*": {
            "origins": allowed_origins,
            "methods": ["GET", "POST"],
            "allow_headers": ["Content-Type"]
        }
    }
)

# --- END: Session and CORS Configuration ---

# Rate limiting
limiter = Limiter(key_func=get_remote_address, app=app, default_limits=["200 per day", "50 per hour"])

# Data configuration and NLP setup
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
USERS_FILE = os.path.join(DATA_DIR, "users.json")
CHATLOG_DIR = os.path.join(DATA_DIR, "chatlogs")
os.makedirs(CHATLOG_DIR, exist_ok=True)
file_lock = threading.Lock()
if not os.path.exists(USERS_FILE):
    with file_lock:
        with open(USERS_FILE, "w") as f: json.dump({}, f)

nlp = None
nlp_model_available = False
def load_nlp_model():
    global nlp, nlp_model_available
    try:
        nlp = spacy.load("en_core_web_sm")
        nlp_model_available = True
        logger.info("spaCy model 'en_core_web_sm' loaded successfully.")
    except OSError:
        logger.warning("spaCy model not found. NLP features will be limited.")
        nlp_model_available = False
threading.Thread(target=load_nlp_model, daemon=True).start()


# Constants
AVATAR_EMOTIONS = {
    "neutral": {"face": "😐", "color": "#4CAF50"}, "concerned": {"face": "😟", "color": "#FF9800"},
    "caring": {"face": "🥰", "color": "#E91E63"}, "listening": {"face": "👂", "color": "#2196F3"},
    "crisis": {"face": "🚨", "color": "#F44336"}, "calm": {"face": "🧘", "color": "#00BCD4"},
    "helpful": {"face": "🤝", "color": "#9C27B0"}, "wise": {"face": "🕉️", "color": "#FF9800"} 
}

# Helper functions
def validate_username(username):
    if not username or not isinstance(username, str): return False, "Username is required"
    username = username.strip()
    if len(username) < 2: return False, "Username must be at least 2 characters"
    if len(username) > 50: return False, "Username must be less than 50 characters"
    if not re.match(r'^[a-zA-Z0-9_-]+$', username): return False, "Username can only contain letters, numbers, hyphens, and underscores"
    return True, username.lower()

def validate_message(message):
    if not message or not isinstance(message, str): return False, "Message is required"
    message = message.strip()
    if len(message) < 1: return False, "Message cannot be empty"
    if len(message) > 1000: return False, "Message is too long (max 1000 characters)"
    return True, message

def load_users():
    try:
        with file_lock:
            with open(USERS_FILE, "r") as f: return json.load(f)
    except Exception: return {}

def save_users(users):
    try:
        with file_lock:
            with open(USERS_FILE, "w") as f: json.dump(users, f, indent=2)
        return True
    except Exception: return False

def get_chatlog_path(username):
    safe_username = re.sub(r'[^a-zA-Z0-9_-]', '', username)
    return os.path.join(CHATLOG_DIR, f"{safe_username}.json")

def log_message(username, user_input, response):
    try:
        chatlog_path = get_chatlog_path(username)
        history = []
        if os.path.exists(chatlog_path):
            try:
                with open(chatlog_path, "r") as f: history = json.load(f)
            except Exception: history = []
        history.append({"id": str(uuid.uuid4()), "timestamp": datetime.now().isoformat(), "user": user_input, "bot": response})
        with open(chatlog_path, "w") as f: json.dump(history[-50:], f, indent=2)
    except Exception as e: logger.error(f"Error logging message for {username}: {e}")

def is_offensive(text):
    offensive_patterns = [r'\b(fuck|shit|damn|hell|ass|bitch|bastard)\b', r'\b(idiot|stupid|moron|retard)\b', r'\b(kill\s+yourself|kys)\b']
    return any(re.search(pattern, text.lower()) for pattern in offensive_patterns)

def detect_crisis(text):
    crisis_phrases = [r'\b(kill\s+myself|end\s+it\s+all|want\s+to\s+die)\b', r'\b(suicide|suicidal|end\s+my\s+life)\b', r'\b(harm\s+myself|hurt\s+myself)\b']
    return any(re.search(phrase, text.lower()) for phrase in crisis_phrases)

def get_crisis_response():
    return ("I'm very concerned about what you're sharing. Please reach out for immediate support:\n\n"
            "🆘 Emergency: Call 100 (India) or your local emergency number\n"
            "📞 National Suicide Prevention Lifeline: 988 (US)\n"
            "💬 Crisis Text Line: Text HOME to 741741 (US/Canada)\n"
            "🌍 International: https://findahelpline.com\n\n"
            "You matter, and help is available. Please reach out right now.")

def is_gibberish(text):
    text = text.lower().strip()
    if not text: return False
    if len(text) < 3 and text not in ['hi', 'om', 'ok', 'no', 'go', 'am', 'is', 'me', 'my']: return True
    vowels = "aeiou"
    consonants = "bcdfghjklmnpqrstvwxyz"
    letter_count = sum(1 for char in text if char.isalpha())
    if letter_count < 3: return False
    num_vowels = sum(1 for char in text if char in vowels)
    if num_vowels == 0 or num_vowels == letter_count: return True
    if len(set(text)) / len(text) < 0.3: return True
    consecutive_consonants = 0
    for char in text:
        if char in consonants:
            consecutive_consonants += 1
        else:
            consecutive_consonants = 0
        if consecutive_consonants >= 5: return True
    return False

def detect_emotion(context):
    last_topic = context.get("last_topic")
    if last_topic == "gita": return "wise"
    if last_topic in ["stress", "anger", "fear"]: return "concerned"
    if last_topic in ["sadness", "loneliness", "grief"]: return "caring"
    if last_topic in ["motivation", "change", "self-doubt"]: return "helpful"
    if last_topic == "calm": return "calm"
    return "listening"


# --- V6 UPGRADE: CONVERSATIONAL MEMORY AND VASTLY EXPANDED RESPONSE LIBRARY ---

RESPONSE_LIBRARY = {
    "stress": [
        "It sounds like you're carrying a heavy burden. The Gita teaches that much of our stress comes from attachment to results we can't control. Let's practice letting go. First, ground yourself with a simple exercise: name three things you can see right now. This brings you to the present, the only place you have power.",
        "Anxiety often pulls us into a future that hasn't happened. The Gita advises us to focus on our present action (dharma). Let's try a calming breath: breathe in for 4 seconds, hold for 4, and exhale for 6. By focusing on your breath, you anchor yourself in the now, freeing your mind from 'what if'.",
        "When feeling overwhelmed, remember Krishna's advice to Arjuna: 'Perform your duty and leave the results to me.' This means focusing only on the next small step, not the entire journey. What is one tiny action you can take right now, without worrying about the outcome?",
        "That feeling of being burnt out is a signal to pause. The Gita doesn't advocate for constant action, but for *wise* action. True rest is a vital part of your dharma. Can you give yourself permission to do one small, restorative thing in the next hour, like listening to a calm song or sitting in silence for five minutes?",
        "Worry is like a rocking chair; it gives you something to do but gets you nowhere. The Gita teaches us to act with 'equanimity'—a balanced mind. Let's try to observe your anxious thoughts without getting caught in them. Imagine them as clouds passing in the sky. You are the sky, not the clouds.",
        "Panic can feel like a storm inside. The Gita says the wise person is like the ocean, which remains calm even as rivers flow into it. Let's find your inner ocean. Place your feet firmly on the ground. Feel the solid earth beneath you. You are supported. Breathe into that feeling of stability.",
        "Stress often arises when we feel our situation is permanent. The Gita reminds us that everything is in a state of flux. This difficult moment will pass, just as day follows night. A practical step is to do something different for just five minutes to break the cycle. Can you walk to a different room or look out a window?",
    ],
    "sadness": [
        "I'm truly sorry you're feeling this way. Please be gentle with yourself. The Gita reminds us that feelings, like seasons, are temporary (Chapter 2, Verse 14). This pain is not permanent. A simple act of self-kindness can be a powerful anchor. Can you place a hand on your heart and just acknowledge, 'This is hard,' offering yourself a moment of grace?",
        "Feeling hopeless is incredibly difficult, but the Gita teaches that your true Self (Atman) is a source of eternal strength, untouched by these feelings. You are more resilient than you know. Let's find one tiny spark: what is one small thing, no matter how simple, that you could do for yourself in the next hour?",
        "Loneliness can feel vast and empty. The Gita teaches that the divine consciousness resides within all beings. You are fundamentally connected to everything. A practical way to feel this is to connect with nature. Can you look out a window and notice the details of a single leaf or a cloud? This can remind us we are part of a larger whole.",
        "When you feel low, your mind might tell you harsh stories about yourself. The Gita asks us to be a witness to our thoughts, not to believe every one of them. You are the sky, and your thoughts are just clouds. Let's try to observe one sad thought without judgment, just letting it float by.",
        "Grief is a testament to love. The Gita teaches that the soul is eternal and cannot be destroyed. While the physical form is gone, the essence remains. Allow yourself to feel this sorrow without judgment. It is a sacred part of your connection. What is one cherished memory you can hold in your heart right now?",
    ],
    "motivation": [
        "Motivation often follows action, not the other way around. The Gita champions 'Karma Yoga'—the power of action without fear of the outcome. Let's make the first step incredibly small. Can you commit to just two minutes of a task? The goal isn't to finish, but simply to begin.",
        "Feeling overwhelmed by a goal is natural. The Gita advises us to focus on the action, not the fruit of the action. Don't look at the whole staircase; just focus on the first step. What is the absolute smallest action you can take right now to move forward?",
        "The fear of failure can be paralyzing. Krishna reminds Arjuna that both success and failure should be met with equanimity. The real victory is in doing your duty with a pure heart. What would you do if you knew you could not fail? Let's explore that.",
        "Fear of change is fear of the unknown. The Gita teaches that change is the only constant in the material world: 'The soul is not born, nor does it die.' (Chapter 2, Verse 20). While circumstances change, your true Self is stable. Let's focus on that inner anchor. What is one thing about you that remains true, no matter what changes around you?",
        "Self-doubt is the mind questioning your true nature. The Gita affirms that the divine Self (Atman) within you is perfect and whole. Let's challenge that doubt with a small piece of evidence. What is one thing, however small, that you have accomplished in the past week? Acknowledge that success.",
    ],
    "anger": [
        "Anger can be a powerful and overwhelming emotion. The Gita describes anger as arising from unfulfilled desire (Chapter 2, Verse 62). Before reacting, let's pause and understand. What desire or expectation might be underneath this anger?",
        "It's okay to feel angry. The wisdom lies not in suppressing it, but in how we respond. The Gita advises against acting impulsively. Let's try a 'wise response' exercise: take three deep breaths. Now, what is the most compassionate and constructive way you could respond to this situation, both for yourself and others?",
        "Frustration often comes from feeling powerless. Let's reclaim your power by focusing on what you can control. The Gita teaches that we control our actions, but not the results. What is one small, constructive action you can take right now, regardless of how others might react?",
        "Anger, as the Gita warns, clouds judgment and leads to delusion. Let's create some space between the feeling and your reaction. A simple physical action can help. Can you press your palms together firmly for ten seconds, then release? This can help discharge some of that intense energy safely.",
    ],
    "clarification": [
        "Thank you for sharing that. Sometimes feelings are hard to name. Does it feel more like a heaviness, like sadness, or more like a buzzing, like anxiety?",
        "I understand. Past thoughts can certainly weigh on us. Are these thoughts making you feel more worried about the future, or more sad about what has been?",
        "Let's try to explore this gently. When these thoughts or feelings arise, what physical sensations do you notice in your body? For example, a tightness in your chest or a knot in your stomach?",
        "That makes sense. Sometimes the feeling is just a general sense of unease. To help me understand, is this feeling more directed outward, like frustration with the world, or inward, like disappointment in yourself?"
    ],
    "encouragement": [
        "I'm with you. Go on.",
        "Take your time. I'm listening.",
        "Tell me more when you're ready.",
        "I'm here to hold space for that.",
        "Okay, I'm following."
    ],
    "repetition": [
        "I notice you've shared that a few times. It seems to be weighing very heavily on you. There's no pressure to talk more about it if you don't want to. I can just sit here with you in silence.",
        "It's okay if words are difficult right now. You've told me what's on your mind, and I've heard you. We don't have to analyze it. Would you prefer to try a simple breathing exercise instead, or just take a moment of quiet?",
        "I hear you. It seems like you're really in this feeling, and I want to honor that. Sometimes, just saying the word is enough. We can pause here if you'd like."
    ]
}

def get_contextual_suggestions(context):
    last_topic = context.get("last_topic")

    if last_topic == "gita":
        return ["Tell me about selfless action (Karma Yoga)", "How can I find my purpose (Dharma)?", "How to deal with a restless mind?", "What is the nature of the Self (Atman)?"]
    if last_topic == "stress":
        return ["Help me ground myself in the present", "How can I let go of worry?", "Guide me through a calming breath exercise", "I'm feeling burnt out"]
    if last_topic == "sadness":
        return ["How can I be kinder to myself?", "Help me find a tiny spark of motivation", "Remind me that this feeling is temporary", "I feel so lonely"]
    if last_topic == "motivation":
        return ["Help me take the first small step", "I feel overwhelmed by my goals", "How can I act without fearing failure?", "I'm afraid of change"]
    if last_topic == "anger":
        return ["How can I respond to anger wisely?", "Help me understand the root of my anger", "What's a healthy way to release anger?"]
    
    return ["I'm feeling stressed and overwhelmed", "I've been feeling sad and hopeless", "Tell me some wisdom for a troubled mind", "I'm feeling angry and frustrated"]

def get_unique_response(topic, context):
    if topic not in RESPONSE_LIBRARY: return None, context
    if "used_responses" not in context: context["used_responses"] = {}
    if topic not in context["used_responses"]: context["used_responses"][topic] = []
    
    all_responses = RESPONSE_LIBRARY[topic]
    used_indices = context["used_responses"][topic]
    available_indices = [i for i, _ in enumerate(all_responses) if i not in used_indices]

    if not available_indices:
        context["used_responses"][topic] = []
        available_indices = list(range(len(all_responses)))

    chosen_index = random.choice(available_indices)
    context["used_responses"][topic].append(chosen_index)
    context["used_responses"][topic] = context["used_responses"][topic][-10:]
    return all_responses[chosen_index], context

# --- NEW: Intent Analysis Engine ---
def analyze_intent(user_input_lower):
    # This function determines the user's primary goal.
    
    # High priority intents
    if user_input_lower.strip() == 'help': return "ask_for_help_general"
    if re.search(r"\b(i don'?t know|idk|not sure)\b", user_input_lower): return "express_uncertainty"
    if any(phrase in user_input_lower for phrase in ["help me take the first", "help me start"]): return "ask_for_motivation_step"

    # Greetings and simple statements
    if any(greeting == user_input_lower for greeting in ['hi', 'hello', 'hey']): return "simple_greeting"
    if re.match(r'.*my name is (\w+).*', user_input_lower): return "simple_statement"
    if any(phrase in user_input_lower for phrase in ["there is something", "i'm thinking", "well...", "it's about", "can say that", "it a mix", "some past thought"]): return "simple_continuation"

    # Emotional expression intents
    if any(kw in user_input_lower for kw in ['stress', 'anxious', 'overwhelm', 'worried', 'panic', 'burnt out']): return "express_stress"
    if any(kw in user_input_lower for kw in ['sad', 'depress', 'hopeless', 'lonely', 'low', 'grief', 'kinder to myself']): return "express_sadness"
    if any(kw in user_input_lower for kw in ['motivation', 'stuck', 'can\'t', 'failure', 'change', 'self-doubt']): return "express_motivation"
    if any(kw in user_input_lower for kw in ['angry', 'frustrated', 'mad', 'irritated']): return "express_anger"
    
    # Tool-based intents
    if any(kw in user_input_lower for kw in ['breathe', 'breathing', 'calm']): return "request_breathing"

    # Knowledge-based intents
    if any(keyword in user_input_lower for keyword in {'gita', 'wisdom', 'krishna', 'arjuna', 'dharma', 'purpose', 'atman', 'self', 'yoga', 'karma', 'mind', 'gunas'}): return "ask_for_gita_wisdom"

    return "unknown" # Default if no specific intent is found


def get_response_based_on_context(user_input, context):
    user_input_lower = user_input.lower()
    new_context = context.copy()
    intent = analyze_intent(user_input_lower)

    # --- Definitive Response Hierarchy ---
    
    # 1. Gibberish check (overrides all other intents)
    if is_gibberish(user_input):
        new_context["last_topic"] = "listening"
        return ("I'm sorry, I'm having a little trouble understanding. Could you please try rephrasing that for me?", new_context)

    # 2. Repetition Protocol (overrides all other intents)
    last_input = context.get("last_input", "")
    repetition_count = context.get("repetition_count", 0)
    if user_input_lower == last_input:
        repetition_count += 1
    else:
        repetition_count = 0
    
    new_context["repetition_count"] = repetition_count
    new_context["last_input"] = user_input_lower

    if repetition_count >= 2:
        new_context["last_topic"] = "caring"
        response, new_context = get_unique_response("repetition", new_context)
        return (response, new_context)

    # 3. Intent-based routing
    if intent == "ask_for_help_general":
        help_count = context.get("help_count", 0) + 1
        new_context["help_count"] = help_count
        new_context["last_topic"] = "concerned"
        if help_count == 1: return ("I am here to help. Please tell me what's happening. I am ready to listen without judgment.", new_context)
        elif help_count == 2: return ("It sounds like you are in real distress. To help me guide you, does this feeling relate more to overwhelming stress, deep sadness, or immediate fear?", new_context)
        else:
            new_context["last_topic"] = "crisis"
            return (get_crisis_response(), new_context)

    if intent == "express_uncertainty":
        dont_know_count = context.get("dont_know_count", 0) + 1
        new_context["dont_know_count"] = dont_know_count
        new_context["last_topic"] = "listening"
        if dont_know_count == 1:
            response, new_context = get_unique_response("clarification", new_context)
            return (response, new_context)
        elif dont_know_count == 2:
            new_context["last_topic"] = "calm"
            return ("That's perfectly okay. Sometimes there are no words. Let's not try to figure it out right now. Instead, how about we try a simple grounding exercise to bring a little calm? Just notice three things in the room around you.", new_context)
        else:
            return ("I hear you. There's no pressure to talk or to know. I will just sit here with you for a moment in silence. Remember that it's okay to not be okay.", new_context)

    if intent == "simple_greeting":
        new_context["last_topic"] = "listening"
        return (random.choice(["Hello! I'm here to listen and support you. How are you feeling today?", "Hi there! Thank you for reaching out. What's on your mind?"]), new_context)

    if intent == "simple_statement":
        name = re.match(r'.*my name is (\w+).*', user_input_lower).group(1).capitalize()
        new_context["last_topic"] = "listening"
        return (f"It's nice to meet you, {name}. I'm here to offer a safe space for your thoughts and feelings. What can I help you with today?", new_context)

    if intent == "simple_continuation":
        new_context["last_topic"] = "listening"
        response, new_context = get_unique_response("encouragement", new_context)
        return (response, new_context)

    if intent == "ask_for_gita_wisdom":
        new_context["last_topic"] = "gita"
        return ("The Bhagavad Gita offers timeless wisdom. A core message is to find inner peace by performing our duties without attachment to the outcome. Is there a specific challenge you're facing where this wisdom might help?", new_context)

    if intent == "express_stress":
        new_context["last_topic"] = "stress"
        response, new_context = get_unique_response("stress", new_context)
        return (response, new_context)

    if intent == "express_sadness":
        new_context["last_topic"] = "sadness"
        response, new_context = get_unique_response("sadness", new_context)
        return (response, new_context)

    if intent == "express_motivation" or intent == "ask_for_motivation_step":
        new_context["last_topic"] = "motivation"
        response, new_context = get_unique_response("motivation", new_context)
        return (response, new_context)
        
    if intent == "express_anger":
        new_context["last_topic"] = "anger"
        response, new_context = get_unique_response("anger", new_context)
        return (response, new_context)

    if intent == "request_breathing":
        new_context["last_topic"] = "calm"
        return ("Of course. Let's practice a calming breath together. Find a comfortable seat. We will do a simple 4-4-6 breath.\n\n• Breathe in gently through your nose for 4 counts.\n• Hold the breath softly for 4 counts.\n• Exhale slowly through your mouth for 6 counts.\n\nLet's try three rounds. This simple act of focusing on the breath is a powerful way to calm the restless mind, just as the Gita advises.", new_context)

    # 4. Anti-Looping Clarification Logic if intent is "unknown"
    if context.get("clarification_asked"):
        new_context["last_topic"] = "listening"
        new_context["clarification_asked"] = False 
        response, new_context = get_unique_response("clarification", new_context)
        return (response, new_context)

    # 5. Empathetic, fused catch-all response (First pass)
    new_context["last_topic"] = "listening"
    new_context["clarification_asked"] = True 
    return ("I hear you. Every feeling is valid and, as the Gita reminds us, temporary. Let's sit with this together. What does this feeling bring up for you?", new_context)


# --- Authentication Decorator and Routes ---
def require_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return decorated_function

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_client(path):
    return send_from_directory(app.static_folder, "index.html")

@app.route("/api/login", methods=["POST"])
@limiter.limit("10 per minute")
def login():
    try:
        data = request.get_json()
        is_valid, username = validate_username(data.get("username", ""))
        if not is_valid: return jsonify({"error": username}), 400
        
        users = load_users()
        if username not in users:
            users[username] = {"created": datetime.now().isoformat(), "avatar": "👤", "color": "#4361ee"}
        users[username]["last_login"] = datetime.now().isoformat()
        save_users(users)

        session.clear()
        session["username"] = username
        session["context"] = {}
        session.permanent = True
        
        logger.info(f"User {username} logged in")
        return jsonify({"username": username, "avatar": users[username]["avatar"], "color": users[username]["color"]})
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route("/api/logout", methods=["POST"])
@require_auth
def logout():
    session.clear()
    return jsonify({"message": "Logged out successfully"})

@app.route("/api/chat", methods=["POST"])
@require_auth
@limiter.limit("60 per minute")
def chat():
    try:
        data = request.get_json()
        is_valid, user_input = validate_message(data.get("message", ""))
        if not is_valid: return jsonify({"error": user_input}), 400

        username = session["username"]
        context = session.get("context", {})
        
        if is_offensive(user_input):
            response, new_context = "Let's keep our conversation respectful so I can better support you.", {"last_topic": "neutral"}
        elif detect_crisis(user_input):
            response, new_context = get_crisis_response(), {"last_topic": "crisis"}
        else:
            response, new_context = get_response_based_on_context(user_input, context)

        # Reset counters if a meaningful interaction occurs
        if new_context.get("last_topic") != "listening":
            new_context["clarification_asked"] = False
            new_context["dont_know_count"] = 0
            new_context["help_count"] = 0
            new_context["repetition_count"] = 0

        session["context"] = new_context
        session.modified = True
        
        emotion = detect_emotion(new_context)
        log_message(username, user_input, response)
        
        return jsonify({
            "response": response,
            "avatar": AVATAR_EMOTIONS.get(emotion, AVATAR_EMOTIONS["listening"]),
            "suggestions": get_contextual_suggestions(new_context),
            "emotion": emotion
        })
    except Exception as e:
        logger.error(f"Chat error for user {session.get('username', 'unknown')}: {e}")
        return jsonify({"response": "I'm having a little trouble processing that right now. Could you please try rephrasing?", "avatar": AVATAR_EMOTIONS["concerned"], "suggestions": get_contextual_suggestions({}), "emotion": "concerned"}), 500

# Other routes and error handlers
@app.route("/api/history", methods=["GET"])
@require_auth
def get_history():
    try:
        username = session["username"]
        chatlog_path = get_chatlog_path(username)
        history = []
        if os.path.exists(chatlog_path):
            try:
                with open(chatlog_path, "r") as f: history = json.load(f)
            except Exception: history = []
        return jsonify({"history": history})
    except Exception as e:
        logger.error(f"History error: {e}")
        return jsonify({"error": "Could not load history"}), 500

@app.errorhandler(404)
def not_found(error): return jsonify({"error": "Not Found"}), 404
@app.errorhandler(429)
def ratelimit_handler(e): return jsonify({"error": "Rate limit exceeded."}), 429
@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal Server Error: {error}")
    return jsonify({"error": "An internal error occurred."}), 500

if __name__ == "__main__":
    if not os.environ.get("SECRET_KEY"):
        logger.error("SECRET_KEY environment variable must be set!")
        exit(1)
    
    port = int(os.environ.get("PORT", 7860))
    debug_mode = os.environ.get("FLASK_ENV") != "production"
    
    logger.info(f"Starting MindCare App on port {port} | Debug: {debug_mode} | Deployed: {IS_DEPLOYED}")
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
