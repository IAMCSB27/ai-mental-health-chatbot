from profanity_check import predict

def is_offensive(text):
    return predict([text])[0] == 1