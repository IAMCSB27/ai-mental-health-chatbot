from profanity_check.profanity_check import predict

def is_offensive(text):
    result = predict([text])
    return result[0] == 1
