"""
App configuration file. Load environment variables from .env file.
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
APP_PORT = os.getenv("APP_PORT", "2000")
APP_PASSWORD = os.getenv("APP_PASSWORD")
GROUPCHAT_NAME = os.getenv("GROUPCHAT_NAME", "WBOR MGMT")

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")
RABBITMQ_EXCHANGE = os.getenv("RABBITMQ_EXCHANGE", "source_exchange")
RABBITMQ_DL_EXCHANGE = os.getenv("RABBITMQ_DL_EXCHANGE", "dead_letter_exchange")
ACK_URL = os.getenv("ACK_URL", "http://wbor-twilio:5000/acknowledge")
TWILIO_SOURCE = os.getenv("TWILIO_SOURCE", "twilio")

GROUPME_BOT_ID = os.getenv("GROUPME_BOT_ID")
GROUPME_ACCESS_TOKEN = os.getenv("GROUPME_ACCESS_TOKEN")
GROUPME_CHARACTER_LIMIT = abs(int(os.getenv("GROUPME_CHARACTER_LIMIT", "900")))

GROUPME_API = "https://api.groupme.com/v3/bots/post"
GROUPME_IMAGE_API = "https://image.groupme.com/pictures"


# Routing keys we don't want to deal with globally
GLOBAL_BLOCKLIST = [
    "source.twilio.sms.outgoing",
    "source.twilio.call-events",
    "source.twilio.voice-intelligence",
]

# The /send endpoint should not allow messages if the `source` is in this list
SEND_BLOCKLIST = ["twilio"]
