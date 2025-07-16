from better_profanity import profanity

profanity.load_censor_words()

def is_offensive(text):
    return profanity.contains_profanity(text)
