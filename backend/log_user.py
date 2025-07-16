import csv
from datetime import datetime

def log_message(user_input, bot_response):
    with open("chat_log.csv", "a") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now(), user_input, bot_response])