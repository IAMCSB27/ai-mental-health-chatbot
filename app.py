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
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="frontend", static_url_path="")

# Secure configuration
def get_secret_key():
    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        if os.environ.get('FLASK_ENV') == 'development':
            return 'dev-secret-key-not-for-production'
        raise ValueError("SECRET_KEY must be set in environment variables")
    return secret_key

app.secret_key = get_secret_key()

# Secure CORS configuration
allowed_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
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

# Rate limiting
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# Secure session configuration
app.config.update(
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production",
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_HTTPONLY=True,
    PERMANENT_SESSION_LIFETIME=3600
)

# Data configuration
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
USERS_FILE = os.path.join(DATA_DIR, "users.json")
CHATLOG_DIR = os.path.join(DATA_DIR, "chatlogs")
os.makedirs(CHATLOG_DIR, exist_ok=True)

# Thread-safe file operations
file_lock = threading.Lock()

# Initialize files if not exists
if not os.path.exists(USERS_FILE):
    with file_lock:
        with open(USERS_FILE, "w") as f:
            json.dump({}, f)

# Enhanced NLP model loading with automatic installation
nlp = None
nlp_model_available = False

def install_spacy_model(model_name="en_core_web_sm"):
    """Install spaCy model if not available"""
    try:
        logger.info(f"Attempting to install spaCy model: {model_name}")
        result = subprocess.run([
            sys.executable, "-m", "spacy", "download", model_name
        ], capture_output=True, text=True, timeout=300)
        
        if result.returncode == 0:
            logger.info(f"Successfully installed spaCy model: {model_name}")
            return True
        else:
            logger.error(f"Failed to install spaCy model: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        logger.error("spaCy model installation timed out")
        return False
    except Exception as e:
        logger.error(f"Error installing spaCy model: {e}")
        return False

def load_nlp_model():
    """Load spaCy model with automatic installation fallback"""
    global nlp, nlp_model_available
    
    models_to_try = ["en_core_web_sm", "en_core_web_md", "en_core_web_lg"]
    
    for model_name in models_to_try:
        try:
            logger.info(f"Attempting to load spaCy model: {model_name}")
            nlp = spacy.load(model_name)
            nlp_model_available = True
            logger.info(f"Successfully loaded spaCy model: {model_name}")
            return True
        except OSError:
            logger.warning(f"spaCy model {model_name} not found, trying to install...")
            if install_spacy_model(model_name):
                try:
                    nlp = spacy.load(model_name)
                    nlp_model_available = True
                    logger.info(f"Successfully loaded spaCy model after installation: {model_name}")
                    return True
                except Exception as e:
                    logger.error(f"Failed to load model after installation: {e}")
                    continue
            else:
                continue
        except Exception as e:
            logger.error(f"Error loading spaCy model {model_name}: {e}")
            continue
    
    # If all models fail, continue without NLP features
    logger.warning("Could not load any spaCy model. NLP features will be limited.")
    nlp = None
    nlp_model_available = False
    return False

# Load NLP model in a separate thread to avoid blocking startup
def initialize_nlp():
    """Initialize NLP model in background thread"""
    load_nlp_model()

# Start NLP initialization in background
threading.Thread(target=initialize_nlp, daemon=True).start()

# Enhanced NLP functions that work with or without spaCy
def analyze_sentiment_basic(text):
    """Basic sentiment analysis without spaCy"""
    if not text:
        return "neutral"
    
    text_lower = text.lower()
    
    # Positive indicators
    positive_words = ['good', 'great', 'happy', 'better', 'fine', 'okay', 'well', 'nice', 'wonderful']
    positive_count = sum(1 for word in positive_words if word in text_lower)
    
    # Negative indicators
    negative_words = ['bad', 'terrible', 'awful', 'sad', 'worse', 'horrible', 'upset', 'angry', 'depressed']
    negative_count = sum(1 for word in negative_words if word in text_lower)
    
    if positive_count > negative_count:
        return "positive"
    elif negative_count > positive_count:
        return "negative"
    else:
        return "neutral"

def analyze_sentiment_advanced(text):
    """Advanced sentiment analysis using spaCy (if available)"""
    global nlp, nlp_model_available
    
    if not nlp_model_available or not nlp:
        return analyze_sentiment_basic(text)
    
    try:
        doc = nlp(text)
        
        # Simple sentiment scoring based on token analysis
        sentiment_score = 0
        for token in doc:
            if token.pos_ == "ADJ":  # Adjectives often carry sentiment
                if token.lemma_ in ['good', 'great', 'wonderful', 'excellent', 'amazing']:
                    sentiment_score += 1
                elif token.lemma_ in ['bad', 'terrible', 'awful', 'horrible', 'sad']:
                    sentiment_score -= 1
        
        if sentiment_score > 0:
            return "positive"
        elif sentiment_score < 0:
            return "negative"
        else:
            return "neutral"
            
    except Exception as e:
        logger.warning(f"Error in advanced sentiment analysis: {e}")
        return analyze_sentiment_basic(text)

def extract_key_phrases(text):
    """Extract key phrases using spaCy if available"""
    global nlp, nlp_model_available
    
    if not nlp_model_available or not nlp:
        # Fallback: simple keyword extraction
        words = text.lower().split()
        important_words = [w for w in words if len(w) > 3 and w not in ['that', 'this', 'with', 'have', 'will', 'been', 'they', 'them']]
        return important_words[:5]
    
    try:
        doc = nlp(text)
        
        # Extract noun phrases and named entities
        key_phrases = []
        
        # Add noun phrases
        for chunk in doc.noun_chunks:
            if len(chunk.text.strip()) > 2:
                key_phrases.append(chunk.text.strip().lower())
        
        # Add named entities
        for ent in doc.ents:
            if ent.label_ in ["PERSON", "ORG", "EVENT", "PRODUCT"]:
                key_phrases.append(ent.text.strip().lower())
        
        return list(set(key_phrases))[:5]  # Remove duplicates and limit to 5
        
    except Exception as e:
        logger.warning(f"Error in key phrase extraction: {e}")
        return []

# Constants
AVATAR_EMOTIONS = {
    "neutral": {"face": "😐", "color": "#4CAF50", "animation": "pulse"},
    "concerned": {"face": "😟", "color": "#FF9800", "animation": "wobble"},
    "caring": {"face": "🥰", "color": "#E91E63", "animation": "heartbeat"},
    "listening": {"face": "👂", "color": "#2196F3", "animation": "bounce"},
    "crisis": {"face": "🚨", "color": "#F44336", "animation": "flash"},
    "calm": {"face": "🧘", "color": "#00BCD4", "animation": "float"},
    "helpful": {"face": "🤝", "color": "#9C27B0", "animation": "bounce"}
}

AVATAR_OPTIONS = {
    "female": ["👩", "👩‍⚕️", "👩‍🎓", "👩‍💼", "👩‍🔬"],
    "male": ["👨", "👨‍⚕️", "👨‍🎓", "👨‍💼", "👨‍🔬"],
    "neutral": ["🧑", "🧑‍⚕️", "🧑‍🎓", "🧑‍💼", "🧑‍🔬", "🤖", "👤"]
}

COLOR_OPTIONS = [
    "#4361ee", "#3f37c9", "#4895ef", "#4cc9f0", 
    "#560bad", "#b5179e", "#f72585", "#7209b7"
]

# Input validation
def validate_username(username):
    if not username or not isinstance(username, str):
        return False, "Username is required"
    
    username = username.strip()
    if len(username) < 2:
        return False, "Username must be at least 2 characters"
    if len(username) > 50:
        return False, "Username must be less than 50 characters"
    if not re.match(r'^[a-zA-Z0-9_-]+$', username):
        return False, "Username can only contain letters, numbers, hyphens, and underscores"
    
    return True, username.lower()

def validate_message(message):
    if not message or not isinstance(message, str):
        return False, "Message is required"
    
    message = message.strip()
    if len(message) < 1:
        return False, "Message cannot be empty"
    if len(message) > 1000:
        return False, "Message too long (max 1000 characters)"
    
    return True, message

# File operations with error handling
def load_users():
    try:
        with file_lock:
            with open(USERS_FILE, "r") as f:
                return json.load(f)
    except FileNotFoundError:
        logger.warning("Users file not found, creating new one")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in users file: {e}")
        return {}
    except Exception as e:
        logger.error(f"Error loading users: {e}")
        return {}

def save_users(users):
    try:
        with file_lock:
            with open(USERS_FILE, "w") as f:
                json.dump(users, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving users: {e}")
        return False

def get_chatlog_path(username):
    safe_username = re.sub(r'[^a-zA-Z0-9_-]', '', username)
    return os.path.join(CHATLOG_DIR, f"{safe_username}.json")

def log_message(username, user_input, response):
    try:
        chatlog_path = get_chatlog_path(username)
        history = []
        
        if os.path.exists(chatlog_path):
            try:
                with open(chatlog_path, "r") as f:
                    history = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                logger.warning(f"Could not load existing chat history for {username}")
                history = []
        
        # Add NLP analysis if available
        sentiment = analyze_sentiment_advanced(user_input)
        key_phrases = extract_key_phrases(user_input)
        
        history.append({
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now().isoformat(),
            "user": user_input[:500],
            "bot": response[:1000],
            "sentiment": sentiment,
            "key_phrases": key_phrases,
            "nlp_available": nlp_model_available
        })
        
        if len(history) > 50:
            history = history[-50:]
        
        with open(chatlog_path, "w") as f:
            json.dump(history, f, indent=2)
            
    except Exception as e:
        logger.error(f"Error logging message for {username}: {e}")

# Content filtering with improved logic
def is_offensive(text):
    if not text or not isinstance(text, str):
        return False
        
    text_lower = text.lower()
    offensive_patterns = [
        r'\b(fuck|shit|damn|hell|ass|bitch|bastard)\b',
        r'\b(idiot|stupid|moron|retard)\b',
        r'\b(kill\s+yourself|kys)\b'
    ]
    
    for pattern in offensive_patterns:
        if re.search(pattern, text_lower):
            return True
    
    return False

def detect_crisis(text):
    if not text or not isinstance(text, str):
        return False
        
    text_lower = text.lower()
    crisis_phrases = [
        r'\b(kill\s+myself|end\s+it\s+all|want\s+to\s+die)\b',
        r'\b(suicide|suicidal|end\s+my\s+life)\b',
        r'\b(harm\s+myself|hurt\s+myself)\b',
        r'\b(can\'?t\s+go\s+on|don\'?t\s+want\s+to\s+live)\b'
    ]
    
    for phrase in crisis_phrases:
        if re.search(phrase, text_lower):
            words = text_lower.split()
            for i, word in enumerate(words):
                if re.search(phrase.replace(r'\b', '').replace(r'\s+', ' '), ' '.join(words[max(0, i-2):i+3])):
                    context = ' '.join(words[max(0, i-3):i+4])
                    if not re.search(r'\b(not|never|don\'?t|won\'?t|wouldn\'?t|isn\'?t)\b', context):
                        return True
    
    return False

def get_crisis_response():
    return (
        "I'm very concerned about what you're sharing. Please reach out for immediate support:\n\n"
        "🆘 Emergency: Call 100 (ind) or your local emergency number\n"
        "📞 National Suicide Prevention Lifeline: 988 (US)\n"
        "💬 Crisis Text Line: Text HOME to 102\n"
        "🌍 International: https://findahelpline.com\n\n"
        "You matter, and help is available. Please reach out right now."
    )

# Utility functions
def generate_avatar():
    all_avatars = []
    for category in AVATAR_OPTIONS.values():
        all_avatars.extend(category)
    return random.choice(all_avatars)

def generate_color():
    return random.choice(COLOR_OPTIONS)

# Enhanced emotion detection with NLP support
def detect_emotion(text, context=None):
    if not text or not isinstance(text, str):
        return "neutral"
        
    text_lower = text.lower()
    
    # Use NLP analysis if available
    sentiment = analyze_sentiment_advanced(text)
    
    # Check for relaxation/calm requests first (most specific)
    if re.search(r'\b(help\s+me\s+relax|relax|calm|breathe|meditation|peaceful)\b', text_lower):
        return "calm"
    
    # Crisis detection
    if re.search(r'\b(suicide|kill|die|end\s+it|harm)\b', text_lower):
        return "crisis"
    
    # Stress/anxiety
    if re.search(r'\b(stress|anxious|overwhelmed|worry|panic|afraid)\b', text_lower):
        return "concerned"
    
    # Sadness/depression
    if re.search(r'\b(sad|depress|hopeless|empty|down|lonely|hurt)\b', text_lower):
        return "caring"
    
    # Listening/communication
    if re.search(r'\b(tell\s+me|listen|hear|understand|talk)\b', text_lower):
        return "listening"
    
    # Simple greetings
    if re.search(r'\b(hi|hello|hey|good\s+(morning|afternoon|evening))\b', text_lower):
        return "neutral"
    
    # Use sentiment analysis to inform emotion if available
    if sentiment == "negative":
        return "caring"
    elif sentiment == "positive":
        return "helpful"
    
    return "neutral"

# Contextual suggestions with NLP enhancement
def get_contextual_suggestions(context, user_input=""):
    if not context or not isinstance(context, dict):
        context = {}
    
    user_input_lower = user_input.lower() if user_input else ""
    
    # Analyze key phrases if NLP is available
    key_phrases = extract_key_phrases(user_input) if user_input else []
    
    # SPECIFIC CONTEXT-BASED SUGGESTIONS
    
    # If user just got help for depression, offer related support
    if context.get("is_depression") or context.get("is_motivation") or context.get("is_mood"):
        return [
            "I need someone to talk to right now",
            "Can you help me create a daily routine?",
            "What are some quick mood boosters?",
            "Help me practice self-compassion"
        ]
    
    # If user is feeling positive, support maintaining wellness
    if context.get("is_positive"):
        return [
            "How can I maintain this good feeling?",
            "What are healthy habits I can build?",
            "Help me appreciate this moment",
            "I want to support others feeling down"
        ]
    
    # Relaxation context - provide specific relaxation techniques
    if (context.get("is_relaxation") or context.get("is_breathing") or
        re.search(r'\b(help\s+me\s+relax|relax|calm|breathe)\b', user_input_lower)):
        return [
            "Guide me through a breathing exercise",
            "Suggest stress relief techniques",
            "Help me with progressive muscle relaxation",
            "What are some mindfulness exercises?"
        ]
    
    # Crisis context
    if context.get("is_crisis"):
        return [
            "I need immediate help",
            "Connect me with crisis resources",
            "I want to talk to someone now",
            "Help me stay safe"
        ]
    
    # Stress context
    if context.get("is_stress") or "stress" in key_phrases:
        return [
            "Help me manage my anxiety",
            "What are coping strategies for stress?",
            "Guide me through deep breathing",
            "How can I calm my mind?"
        ]
    
    # Sleep context
    if context.get("is_sleep") or "sleep" in key_phrases:
        return [
            "Help me sleep better",
            "Suggest a bedtime routine",
            "I have insomnia problems",
            "What helps with sleep anxiety?"
        ]
    
    # Check recent input patterns for better suggestions
    if re.search(r'\b(sad|depression|low|down|hopeless)\b', user_input_lower):
        return [
            "Suggest activities for depression",
            "Help me find motivation", 
            "How can I improve my mood?",
            "I'm feeling very low today"
        ]
    
    if re.search(r'\b(happy|good|better|joy)\b', user_input_lower):
        return [
            "How can I maintain this feeling?",
            "What are some gratitude practices?",
            "Help me build positive habits",
            "I want to help others too"
        ]
    
    if re.search(r'\b(anxiety|worry|panic|overwhelm)\b', user_input_lower):
        return [
            "Help me manage my anxiety",
            "Teach me grounding techniques",
            "Guide me through deep breathing",
            "What helps with panic attacks?"
        ]
    
    # Default suggestions based on common mental health needs
    return [
        "I'm feeling stressed",
        "I've been sad lately", 
        "Help me relax",
        "I can't sleep well"
    ]

# Enhanced response logic with NLP integration
def get_response_based_on_context(user_input, history, context):
    if not user_input:
        return "I'm here to listen. What's on your mind?", {}
        
    user_input_lower = user_input.lower()
    new_context = context.copy() if context else {}
    
    # Add sentiment and key phrase analysis
    sentiment = analyze_sentiment_advanced(user_input)
    key_phrases = extract_key_phrases(user_input)
    
    logger.debug(f"Processing input: '{user_input}' with context: {context}")
    logger.debug(f"Sentiment: {sentiment}, Key phrases: {key_phrases}")
    
    # Store analysis in context
    new_context["last_sentiment"] = sentiment
    new_context["last_key_phrases"] = key_phrases
    
    # SPECIFIC DEPRESSION/MOOD HELP REQUESTS - HIGH PRIORITY
    if re.search(r'\b(suggest\s+activities\s+for\s+depression|activities\s+for\s+depression)\b', user_input_lower):
        new_context["is_depression"] = True
        depression_activity_responses = [
            "Here are some gentle activities that can help with depression:\n\n• **Physical**: Take a 10-minute walk outside, do light stretching, or dance to one favorite song\n• **Creative**: Draw, write in a journal, or try a simple craft\n• **Social**: Call a friend, text someone you care about, or join an online community\n• **Self-care**: Take a warm shower, listen to uplifting music, or practice gratitude\n• **Routine**: Make your bed, organize one small area, or prepare a healthy snack\n\nStart with just one small thing. Which type of activity feels most manageable for you today?",
            "Depression can make everything feel overwhelming, so let's start small. Here are some activities that many people find helpful:\n\n• **Movement**: Even 5 minutes of walking or stretching can boost mood\n• **Sunlight**: Sit by a window or step outside briefly\n• **Connection**: Reach out to one person, even just to say hello\n• **Accomplishment**: Complete one tiny task like washing dishes or making tea\n• **Mindfulness**: Try 3 deep breaths or notice 5 things around you\n\nWhat feels like something you could try today?"
        ]
        return random.choice(depression_activity_responses), new_context
    
    if re.search(r'\b(help\s+me\s+find\s+motivation|find\s+motivation|need\s+motivation)\b', user_input_lower):
        new_context["is_motivation"] = True
        motivation_responses = [
            "Finding motivation when you're struggling can feel impossible, but let's start tiny:\n\n**The 2-Minute Rule**: Choose something that takes less than 2 minutes. Maybe it's:\n• Brushing your teeth\n• Making your bed\n• Sending one text\n• Writing down one thing you're grateful for\n\n**Remember**: Motivation often comes AFTER action, not before. Sometimes we have to start moving first, and the motivation follows. What's one 2-minute thing you could do right now?",
            "I understand how hard it is when motivation feels completely gone. Here's what can help:\n\n**Start microscopic**: Instead of 'exercise,' just put on workout clothes. Instead of 'clean house,' just clear one small surface.\n\n**Use your support**: Tell someone your tiny goal - accountability can be powerful.\n\n**Celebrate small wins**: Finished that 2-minute task? That's genuinely worth celebrating.\n\nWhat's the smallest possible step you could take toward something that matters to you?"
        ]
        return random.choice(motivation_responses), new_context
    
    if re.search(r'\b(how\s+can\s+i\s+improve\s+my\s+mood|improve\s+my\s+mood|boost\s+my\s+mood)\b', user_input_lower):
        new_context["is_mood"] = True
        mood_improvement_responses = [
            "There are several gentle ways to give your mood a little boost:\n\n**Quick mood lifters** (5-10 minutes):\n• Listen to an upbeat song you love\n• Step outside and take 5 deep breaths\n• Watch a funny video or cute animal clips\n• Text someone a compliment\n• Do 10 jumping jacks or stretch\n\n**Longer-term mood support**:\n• Get some sunlight daily\n• Move your body regularly\n• Connect with people you care about\n• Practice gratitude\n• Maintain a sleep routine\n\nWhich of these feels most doable for you right now?",
            "Improving mood often happens through small, consistent actions. Here's a gentle approach:\n\n**Right now**: Try the 5-4-3-2-1 technique - name 5 things you see, 4 you can touch, 3 you hear, 2 you smell, 1 you taste. This grounds you in the present.\n\n**Today**: Do one thing that usually brings you joy, even if it doesn't feel appealing right now.\n\n**This week**: Focus on basics - sleep, nutrition, a bit of movement, and connection with others.\n\nRemember: it's okay if these don't work perfectly. You're trying, and that matters. What feels like the most gentle first step for you?"
        ]
        return random.choice(mood_improvement_responses), new_context
    
    # FEELING VERY LOW - IMMEDIATE SUPPORT
    if re.search(r'\b(feeling\s+very\s+low|i\'?m\s+feeling\s+very\s+low)\b', user_input_lower):
        new_context["is_depression"] = True
        low_feeling_responses = [
            "I'm really glad you reached out and shared that with me. Feeling very low is incredibly difficult, and it takes courage to put that into words.\n\nRight now, you don't have to fix everything or feel better immediately. You just need to get through this moment, and then the next one.\n\n**Immediate comfort**:\n• You are not alone in this\n• This feeling, while intense, is temporary\n• Reaching out like you just did shows real strength\n\nCan you tell me - are you safe right now? And is there one small thing that usually brings you even a tiny bit of comfort?",
            "Thank you for trusting me with how you're feeling. When you're feeling very low, everything can seem overwhelming and hopeless, but I want you to know that these feelings don't define you or your worth.\n\n**Right now, focus on**:\n• Taking slow, deep breaths\n• Staying in this moment instead of worrying about tomorrow\n• Being gentle with yourself\n\nYou don't have to be strong or positive right now. You just have to be here, and you are. What's been the hardest part of today for you?"
        ]
        return random.choice(low_feeling_responses), new_context
    
    # RELAXATION RESPONSES
    if re.search(r'\b(help\s+me\s+relax|relax|calm\s+down|need\s+to\s+relax)\b', user_input_lower):
        new_context["is_relaxation"] = True
        relaxation_responses = [
            "I'd love to help you relax! Let's start with some deep breathing. Try breathing in slowly for 4 counts, holding for 4, then exhaling for 6. Would you like me to guide you through a breathing exercise?",
            "Relaxation is so important. Here are some techniques that can help: deep breathing, progressive muscle relaxation, or mindfulness meditation. Which sounds most appealing to you right now?",
            "Let's create a calm space together. First, find a comfortable position and take three deep breaths with me. In... and out... Feel your shoulders dropping with each exhale. What's making you feel tense today?"
        ]
        return random.choice(relaxation_responses), new_context
    
    # Breathing exercise requests
    if re.search(r'\b(breathing|breathe|breath)\b', user_input_lower):
        new_context["is_breathing"] = True
        breathing_responses = [
            "Breathing exercises are wonderful for relaxation. Try the 4-7-8 technique: breathe in for 4 counts, hold for 7, exhale for 8. This activates your body's relaxation response. Would you like me to guide you through it?",
            "Let's focus on your breath together. Place one hand on your chest, one on your belly. Breathe so that only the bottom hand moves. This engages your diaphragm and triggers relaxation.",
            "Box breathing is very effective: breathe in for 4, hold for 4, out for 4, hold for 4. Like drawing a box with your breath. Shall we try a few rounds together?"
        ]
        return random.choice(breathing_responses), new_context
    
    # SAD LATELY - DEPRESSION SUPPORT
    if re.search(r'\b(i\'?ve\s+been\s+sad\s+lately|been\s+sad\s+lately|sad\s+lately)\b', user_input_lower):
        new_context["is_depression"] = True
        sadness_responses = [
            "I'm sorry you've been carrying sadness lately. It's important that you're recognizing these feelings and reaching out - that takes real emotional awareness and strength.\n\nSadness can feel heavy and persistent, but you don't have to carry it alone. Sometimes sadness is our mind's way of processing difficult things or signaling that we need extra care and support.\n\nWhat do you think might be contributing to these sad feelings? And have you been able to talk to anyone else about what you're going through?",
            "Thank you for sharing that with me. Sadness that lingers can be really draining and make everything feel more difficult.\n\nIt's completely valid to feel sad - your emotions matter and deserve attention. Sometimes when we've been sad for a while, it can help to:\n• Acknowledge the feeling without judgment\n• Consider what support we might need\n• Take extra gentle care of ourselves\n\nWhat has this sadness been like for you? Is it connected to specific things, or does it feel more general?"
        ]
        return random.choice(sadness_responses), new_context
    
    # POSITIVE EMOTIONS - VALIDATE AND EXPLORE
    if re.search(r'\b(happy|joy|good|better|great|wonderful)\b', user_input_lower):
        new_context["is_positive"] = True
        if re.search(r'\b(a bit good|feeling good|happy|joyful)\b', user_input_lower):
            positive_responses = [
                "I'm so glad to hear you're feeling good today! That's wonderful. Sometimes it's really important to acknowledge and appreciate these positive moments, especially if you've been going through difficult times recently.\n\nWhat's been contributing to you feeling good today? I'd love to hear about what's going well for you.",
                "It's really nice to hear that you're feeling happy and joyful! Those are precious feelings, and I'm glad you're experiencing them right now.\n\nFeeling good can sometimes feel almost surprising when we're used to struggling, but you deserve to feel joy and happiness. What's been bringing you these positive feelings?"
            ]
            return random.choice(positive_responses), new_context
    
    # Simple greetings - be welcoming
    if re.search(r'^(hi|hello|hey)$', user_input_lower.strip()):
        greeting_responses = [
            "Hello! I'm so glad you're here. This is a safe space where you can share whatever is on your mind. How are you feeling today?",
            "Hi there! Welcome to our conversation. I'm here to listen and support you. What's been on your mind lately?",
            "Hey! Thank you for reaching out. Sometimes just saying hello can be the first step to feeling better. How can I support you today?"
        ]
        return random.choice(greeting_responses), new_context
    
    # Stress/anxiety patterns
    if re.search(r'\b(stress|overwhelm|anxious|anxiety|worried|panic|afraid)\b', user_input_lower):
        new_context["is_stress"] = True
        stress_responses = [
            "It sounds like you're feeling overwhelmed right now, and that's completely understandable. Stress can feel all-consuming. What's been the biggest source of stress for you lately?",
            "Anxiety can be really challenging to deal with. When you're feeling this way, remember that you're safe in this moment. What usually helps you feel more grounded?",
            "I hear that you're struggling with stress. That takes courage to acknowledge. Let's work together to find some relief. Have you tried any stress management techniques before?"
        ]
        return random.choice(stress_responses), new_context
    
    # General depression/sadness patterns
    if re.search(r'\b(depress|sad|hopeless|empty|down|worthless|lonely)\b', user_input_lower):
        new_context["is_depression"] = True
        depression_responses = [
            "Thank you for sharing something so personal with me. Depression can make everything feel heavy and overwhelming. You're not alone in this, and your feelings are completely valid.",
            "It takes real strength to reach out when you're feeling this way. What's been the hardest part of your day today?",
            "I want you to know that these feelings, while very real and difficult, don't define your worth as a person. Have you been able to talk to anyone else about how you're feeling?"
        ]
        return random.choice(depression_responses), new_context
    
    # Sleep issues
    if re.search(r'\b(sleep|insomnia|tired|exhausted|fatigue|can\'?t\s+sleep)\b', user_input_lower):
        new_context["is_sleep"] = True
        sleep_responses = [
            "Sleep problems can really impact everything else in your life. Poor sleep and mental health are closely connected. What does your current bedtime routine look like?",
            "I understand how frustrating sleep issues can be. Have you noticed any patterns in what helps or hurts your ability to sleep?",
            "Rest is so important for healing and well-being. Let's talk about creating a more restful environment. What's making it hard for you to sleep?"
        ]
        return random.choice(sleep_responses), new_context
    
    # Default empathetic responses with sentiment consideration
    if sentiment == "negative":
        default_responses = [
            "I can sense that you're going through something difficult. Your feelings are valid, and I'm here to support you. What's been weighing on your mind?",
            "It sounds like things have been challenging for you. You don't have to face this alone. What would be most helpful for you right now?",
            "I hear the pain in your words, and I want you to know that I'm here to listen. What's been the hardest part of your day?"
        ]
    else:
        default_responses = [
            "I hear you, and I want you to know that I'm here to listen. Can you tell me more about what you're experiencing right now?",
            "Thank you for sharing that with me. Your feelings matter, and this is a safe space to express them. What's been on your mind?",
            "I appreciate you reaching out and being open with me. Sometimes just talking can help. How long have you been feeling this way?"
        ]
    
    return random.choice(default_responses), new_context

# Authentication decorator
def require_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return decorated_function

# Routes
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_client(path):
    try:
        return send_from_directory("frontend", "index.html")
    except Exception as e:
        logger.error(f"Error serving static file: {e}")
        return "Application not found", 404

@app.route("/api/login", methods=["POST"])
@limiter.limit("10 per minute")
def login():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid request format"}), 400
            
        username_input = data.get("username", "")
        
        is_valid, result = validate_username(username_input)
        if not is_valid:
            return jsonify({"error": result}), 400
            
        username = result
        
        users = load_users()
        if username not in users:
            users[username] = {
                "created": datetime.now().isoformat(),
                "avatar": generate_avatar(),
                "color": generate_color(),
                "last_login": datetime.now().isoformat()
            }
            if not save_users(users):
                return jsonify({"error": "Failed to create user"}), 500
        else:
            users[username]["last_login"] = datetime.now().isoformat()
            save_users(users)

        session.clear()
        session["username"] = username
        session["user_id"] = str(uuid.uuid4())
        session["context"] = {}  # Initialize empty context
        session["login_time"] = datetime.now().isoformat()
        session.permanent = True
        
        logger.info(f"User {username} logged in successfully")
        
        return jsonify({
            "message": f"Welcome back, {username}!",
            "username": username,
            "avatar": users[username]["avatar"],
            "color": users[username]["color"],
            "session_id": session["user_id"],
            "nlp_available": nlp_model_available
        })
        
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route("/api/logout", methods=["POST"])
@require_auth
def logout():
    username = session.get("username")
    session.clear()
    logger.info(f"User {username} logged out")
    return jsonify({"message": "Logged out successfully"})

@app.route("/api/chat", methods=["POST"])
@require_auth
@limiter.limit("30 per minute")
def chat():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid request format"}), 400

        username = session["username"]
        user_input_raw = data.get("message", "")
        
        is_valid, user_input = validate_message(user_input_raw)
        if not is_valid:
            return jsonify({"error": user_input}), 400

        # Load conversation history
        chatlog_path = get_chatlog_path(username)
        history = []
        if os.path.exists(chatlog_path):
            try:
                with open(chatlog_path, "r") as f:
                    history = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load chat history for {username}: {e}")

        # Get current context from session
        context = session.get("context", {})
        logger.debug(f"Current context for {username}: {context}")
        
        # Generate response based on content
        if is_offensive(user_input):
            response = "I understand you might be frustrated. Let's keep our conversation respectful so I can better support you."
            new_context = {**context, "is_offensive": True}
            emotion = "concerned"
        elif detect_crisis(user_input):
            response = get_crisis_response()
            new_context = {**context, "is_crisis": True}
            emotion = "crisis"
            logger.warning(f"Crisis detected for user {username}: {user_input[:100]}")
        else:
            recent_history = history[-3:] if history else []
            response, new_context = get_response_based_on_context(user_input, recent_history, context)
            emotion = detect_emotion(user_input, new_context)

        # Update session context
        session["context"] = new_context
        session.modified = True
        
        logger.debug(f"Updated context for {username}: {new_context}")
        logger.debug(f"Response emotion: {emotion}")
        
        # Get avatar and suggestions
        avatar_data = AVATAR_EMOTIONS.get(emotion, AVATAR_EMOTIONS["neutral"])
        suggestions = get_contextual_suggestions(new_context, user_input)

        # Log the conversation
        log_message(username, user_input, response)
        
        return jsonify({
            "response": response,
            "message_id": str(uuid.uuid4()),
            "avatar": avatar_data,
            "suggestions": suggestions[:4],  # Return up to 4 suggestions
            "emotion": emotion,
            "nlp_analysis": {
                "sentiment": analyze_sentiment_advanced(user_input),
                "key_phrases": extract_key_phrases(user_input),
                "nlp_available": nlp_model_available
            }
        })
        
    except Exception as e:
        logger.error(f"Chat error for user {session.get('username', 'unknown')}: {e}")
        return jsonify({
            "response": "I'm having trouble processing that right now. Could you try rephrasing your message?",
            "message_id": str(uuid.uuid4()),
            "avatar": AVATAR_EMOTIONS["neutral"],
            "suggestions": ["I'm feeling stressed", "Help me relax", "I need support"],
            "emotion": "neutral",
            "nlp_analysis": {
                "sentiment": "neutral",
                "key_phrases": [],
                "nlp_available": nlp_model_available
            }
        })

@app.route("/api/history", methods=["GET"])
@require_auth
def get_history():
    try:
        username = session["username"]
        chatlog_path = get_chatlog_path(username)
        
        history = []
        if os.path.exists(chatlog_path):
            try:
                with open(chatlog_path, "r") as f:
                    history = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load chat history for {username}: {e}")
                
        return jsonify({
            "username": username,
            "history": history[-20:],
            "total_messages": len(history),
            "nlp_available": nlp_model_available
        })
        
    except Exception as e:
        logger.error(f"History error for user {session.get('username', 'unknown')}: {e}")
        return jsonify({"error": "Could not load chat history"}), 500

@app.route("/api/nlp-status", methods=["GET"])
@require_auth
def nlp_status():
    """Get current NLP model status"""
    global nlp_model_available, nlp
    
    model_info = {}
    if nlp_model_available and nlp:
        try:
            model_info = {
                "model_name": nlp.meta.get("name", "unknown"),
                "version": nlp.meta.get("version", "unknown"),
                "language": nlp.meta.get("lang", "unknown")
            }
        except:
            model_info = {"model_name": "loaded", "version": "unknown", "language": "en"}
    
    return jsonify({
        "nlp_available": nlp_model_available,
        "model_info": model_info,
        "features_available": {
            "sentiment_analysis": nlp_model_available,
            "key_phrase_extraction": nlp_model_available,
            "advanced_emotion_detection": nlp_model_available
        }
    })

@app.route("/api/install-nlp", methods=["POST"])
@require_auth
@limiter.limit("3 per hour")
def install_nlp():
    """Manually trigger NLP model installation"""
    try:
        data = request.get_json()
        model_name = data.get("model", "en_core_web_sm") if data else "en_core_web_sm"
        
        # Validate model name
        valid_models = ["en_core_web_sm", "en_core_web_md", "en_core_web_lg"]
        if model_name not in valid_models:
            return jsonify({"error": "Invalid model name"}), 400
        
        logger.info(f"Manual NLP installation requested for model: {model_name}")
        
        # Run installation in background thread
        def install_and_load():
            global nlp_model_available, nlp
            success = install_spacy_model(model_name)
            if success:
                try:
                    nlp = spacy.load(model_name)
                    nlp_model_available = True
                    logger.info(f"Successfully installed and loaded {model_name}")
                except Exception as e:
                    logger.error(f"Failed to load model after installation: {e}")
                    nlp_model_available = False
            else:
                logger.error(f"Failed to install {model_name}")
        
        threading.Thread(target=install_and_load, daemon=True).start()
        
        return jsonify({
            "message": f"Installing {model_name}... This may take a few minutes.",
            "status": "installing"
        })
        
    except Exception as e:
        logger.error(f"NLP installation error: {e}")
        return jsonify({"error": "Failed to install NLP model"}), 500

@app.route("/api/breathing-exercise", methods=["POST"])
@require_auth
@limiter.limit("10 per minute")
def breathing_exercise():
    try:
        data = request.get_json()
        action = data.get("action", "start") if data else "start"
        
        if action == "start":
            session["breathing_active"] = True
            session["breathing_start"] = datetime.now().isoformat()
            session.modified = True
            return jsonify({
                "status": "active",
                "message": "Breathing exercise started. Follow the rhythm."
            })
        elif action == "stop":
            session["breathing_active"] = False
            session.modified = True
            return jsonify({
                "status": "inactive",
                "message": "Great job completing the breathing exercise!"
            })
        else:
            return jsonify({"error": "Invalid action"}), 400
            
    except Exception as e:
        logger.error(f"Breathing exercise error: {e}")
        return jsonify({"error": "Could not process breathing exercise"}), 500

@app.route("/api/breathing-status", methods=["GET"])
@require_auth
def breathing_status():
    return jsonify({
        "active": session.get("breathing_active", False),
        "start_time": session.get("breathing_start")
    })

@app.route("/api/system-status", methods=["GET"])
@require_auth
def system_status():
    """Get overall system status including NLP"""
    return jsonify({
        "server_status": "running",
        "nlp_available": nlp_model_available,
        "features": {
            "basic_chat": True,
            "emotion_detection": True,
            "crisis_detection": True,
            "breathing_exercises": True,
            "advanced_nlp": nlp_model_available,
            "sentiment_analysis": nlp_model_available,
            "key_phrase_extraction": nlp_model_available
        },
        "uptime": datetime.now().isoformat()
    })

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    if not os.environ.get("SECRET_KEY"):
        logger.error("SECRET_KEY environment variable must be set!")
        exit(1)
    
    port = int(os.environ.get("PORT", 7860))
    debug_mode = os.environ.get("FLASK_ENV") != "production"
    
    logger.info(f"Starting Flask app on port {port}")
    logger.info(f"NLP Model available: {nlp_model_available}")
    if nlp_model_available:
        logger.info("Advanced NLP features enabled")
    else:
        logger.info("Running with basic NLP features only")
    
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
