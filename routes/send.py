"""
Send message module.
"""

from flask import Blueprint, request
from utils.message import MessageUtils
from utils.logging import configure_logging
from rabbitmq.publisher import publish_message
from config import APP_PASSWORD

logger = configure_logging(__name__)

send = Blueprint("send", __name__)


@send.route("/send", methods=["POST"])
def send_message():
    """
    Send a message via a bot. Meant for sources that do not use RabbitMQ or is impractical to use.
    Queue is local to this service (in consumer.py).

    Logs the message in Postgres with:
    - Source (e.g. Twilio)
    - UID (unique message ID)
    - Timestamp
    - Text
    - Images (if any)

    Request body includes the following fields:
    - body (str): The message text to send
    - password (str): The password to authenticate the request
    - source (str): The source of the message (e.g. "Twilio")
        - The source string provided is used as the routing key for RabbitMQ!
    - (optional) images (list): A list of image URLs to send
    - (optional) wbor_message_id (str): The unique message ID (generated by message originator)
        - If not provided (the case for non-RabbitMQ messages), a UID will be generated

    Returns:
    - str: "OK" if the message was sent successfully
    - str: "Unauthorized" if the password is incorrect
    - str: "Bad Request" if the request body is missing required fields
    - str: "Internal Server Error" if the message failed to send
    """
    body = request.json

    # Ensure `password` is present and correct
    if body.get("password") != APP_PASSWORD:
        logger.warning(
            "Unauthorized access attempt with password: %s", body.get("password")
        )
        return "Unauthorized"
    body.remove("password")  # Strip password from the request body - no longer needed
    logger.info("Send callback received: %s", body)

    # Check required fields
    required_fields = ["body", "source"]
    missing_fields = [field for field in required_fields if field not in body]
    if missing_fields:
        logger.error("Bad Request: Missing required fields: %s", missing_fields)
        return "Bad Request"

    # Ensure any other fields are either `images` or `wbor_message_id`
    extra_fields = [field for field in body.keys() if field not in required_fields]
    if extra_fields and extra_fields not in ["images", "wbor_message_id"]:
        logger.error("Bad Request: Unexpected fields: %s", extra_fields)
        return "Bad Request"

    # Generate or use the provided UID
    sender_uid = body.get("wbor_message_id")
    if sender_uid is None:
        sender_uid = MessageUtils.gen_uuid()
        logger.debug("No UID provided - generated new UID: %s", sender_uid)
        body["wbor_message_id"] = sender_uid
    else:
        logger.debug("UID provided by source: %s", sender_uid)

    # At this point, we know the request body is valid
    # The only remaining fields are `body`, `source`, `images`, and `wbor_message_id`
    logger.info("Publishing to RabbitMQ: %s", sender_uid)
    publish_message(body, body.get("source"))
    return "OK"