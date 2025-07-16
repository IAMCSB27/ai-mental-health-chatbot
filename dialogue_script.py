import random

fallback_responses = [
    "I'm here for you. Would you like to talk more about it?",
    "That must be difficult. You're not alone.",
    "Take a deep breath. You're doing your best."
]

def get_fallback_response():
    return random.choice(fallback_responses)