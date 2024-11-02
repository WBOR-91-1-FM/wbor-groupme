"""
GroupMe Handler.
- Consumes messages from the RabbitMQ queue to forward to a GroupMe group chat.
"""

import os
import logging
import json
from datetime import datetime, timezone
import time
import requests
import pika
import pika.exceptions
import pytz
from flask import Flask
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
APP_PORT = os.getenv("APP_PORT", "2000")
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "wbor-rabbitmq")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")
GROUPME_QUEUE = os.getenv("GROUPME_QUEUE", "groupme")
GROUPME_BOT_ID = os.getenv("GROUPME_BOT_ID")
GROUPME_CHARACTER_LIMIT = abs(int(os.getenv("GROUPME_CHARACTER_LIMIT", "970")))

GROUPME_API = "https://api.groupme.com/v3/bots/post"

# Logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Define a handler to output to the console
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)


class EasternTimeFormatter(logging.Formatter):
    """Custom log formatter to display timestamps in Eastern Time"""

    def formatTime(self, record, datefmt=None):
        # Convert UTC to Eastern Time
        eastern = pytz.timezone("America/New_York")
        utc_dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        eastern_dt = utc_dt.astimezone(eastern)
        # Use ISO 8601 format
        return eastern_dt.isoformat()


formatter = EasternTimeFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
logging.getLogger("werkzeug").setLevel(logging.INFO)

app = Flask(__name__)


def send_message(body):
    """
    Send a message to the GroupMe group chat.

    Parameters:
    - body (str): The message to send

    Throws:
    - requests.exceptions.RequestException: If the message fails to send
    """
    try:
        logger.debug("Sending message: %s", body)

        # GroupMe has a character limit. Split the message into segments if it exceeds the limit.
        segments = []
        for i in range(0, len(body), GROUPME_CHARACTER_LIMIT):
            segments.append(body[i : i + GROUPME_CHARACTER_LIMIT])

        total_segments = len(segments)

        for index, segment in enumerate(segments, start=1):
            # Add segment label and end marker if there are multiple segments
            segment_label = (
                f"({index}/{total_segments}):\n" if total_segments > 1 else ""
            )  # Max 17 chars.
            end_marker = "\n---------" if index == total_segments else ""  # 10 chars.

            data = {
                "text": f"{segment_label}{segment}{end_marker}",
                "bot_id": GROUPME_BOT_ID,
            }
            headers = {"Content-Type": "application/json"}

            # Send the message
            response = requests.post(
                GROUPME_API, data=json.dumps(data), headers=headers, timeout=10
            )
            response.raise_for_status()

        logger.debug("Sent!")
    except requests.exceptions.RequestException as e:
        logger.error("Failed to send message: %s", e)


def callback(_ch, _method, _properties, body):
    """Callback function to process messages from the RabbitMQ queue."""
    logger.info("Callback triggered.")

    try:
        message = json.loads(body)
        logger.debug("Received message: %s", message)

        sender_number = message.get("From")
        logger.debug("Processing message from %s", sender_number)

        body = message.get("Body")
        send_message(body)
    except (json.JSONDecodeError, KeyError) as e:
        logger.error("Failed to execute callback: %s", e)


def consume_messages():
    """Consume messages from the RabbitMQ queue."""
    while True:
        logger.debug("Attempting to connect to RabbitMQ...")
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
        parameters = pika.ConnectionParameters(
            host=RABBITMQ_HOST, credentials=credentials
        )
        try:
            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()
            channel.queue_declare(queue=GROUPME_QUEUE, durable=True)
            channel.basic_consume(
                queue=GROUPME_QUEUE, on_message_callback=callback, auto_ack=True
            )
            logger.info("Now ready to consume messages.")
            channel.start_consuming()
        except pika.exceptions.AMQPConnectionError as e:
            logger.error("Failed to connect to RabbitMQ: %s", e)
            logger.info("Retrying in 5 seconds...")
            time.sleep(5)


@app.route("/")
def hello_world():
    """Serve a simple static Hello World page at the root"""
    return "<h1>wbor-groupme is online!</h1>"


if __name__ == "__main__":
    logger.info("Starting Flask app and RabbitMQ consumer...")
    consume_messages()
    app.run(host="0.0.0.0", port=APP_PORT)
