"""
Consumer module for RabbitMQ.
"""

import json
import time
import sys
import pika
import pika.exceptions
from utils.logging import configure_logging
from utils.message import MessageUtils
from config import (
    TWILIO_SOURCE,
    RABBITMQ_HOST,
    RABBITMQ_USER,
    RABBITMQ_PASS,
    RABBITMQ_EXCHANGE,
    BLOCKLIST,
)
from .util import assert_exchange, send_acknowledgment
from .handlers import MESSAGE_HANDLERS, SOURCES

logger = configure_logging(__name__)


def callback(ch, method, properties, body):
    """
    Callback function to process messages from the RabbitMQ queue.

    If a message has the header `alreadysent`, it is assumed to have been sent
    and at this point is only logged. Otherwise, the message is sanitized and processed.

    Treatment for all messages not already sent:
    - Sanitize the message body (for unsent messages)
    - Process the message using the appropriate handler

    Parameters:
    - body: The message body

    Returns:
    - None

    Throws:
    - json.JSONDecodeError: If the message body is not valid JSON
    - KeyError: If the message body is missing required keys
    """

    try:
        message = json.loads(body)
        logger.debug(
            "Received message (w/ routing key `%s`): %s", method.routing_key, message
        )

        # Ensure it is not in the routing key blocklist
        # Strip "source." from the routing key
        copy = method.routing_key
        stripped_key = copy.replace("source.", "")
        if stripped_key in BLOCKLIST:
            logger.warning(
                "Routing key `%s` is in the blocklist. Message rejected.",
                method.routing_key,
            )
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return

        # Verify required fields

        # "From" if from Twilio, "source" otherwise
        sender = message.get("From") or message.get("source")

        # If both the sender and the message body (body or Body) are missing,
        # the message is rejected and it won't be requeued.
        # Twilio capitalizes `Body`, while other sources use `body`
        if not sender and (not message.get("body") or not message.get("Body")):
            logger.debug(
                "Message missing required fields: %s, delivery_tag: %s",
                message,
                method.delivery_tag,
            )
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return
        original_body = message.get("Body") or message.get("body")
        logger.info(
            "Processing message from `%s`: %s - UID: %s",
            sender,
            original_body,
            message.get("wbor_message_id"),
        )

        # Verify the message type and source
        # Must be either an incoming SMS or a standard message

        # Add other sources as needed in the future (e.g. AzuraCast)
        if (
            not message.get("source")
            == TWILIO_SOURCE  # Added in the wbor-twilio /sms endpoint
            and not message.get("source") == "standard"
        ):
            logger.debug("message.source: %s", message.get("source"))
            logger.warning(
                "Matching condition not met: %s, delivery_tag: %s",
                message,
                method.delivery_tag,
            )
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return

        # Sanitize the message body only if it hasn't been sent yet
        # Otherwise, log it as is
        alreadysent = properties.headers.get("alreadysent", False)
        if not alreadysent:
            if "Body" in message or "body" in message:
                original_body = message.get("Body") or message.get("body")
                sanitized_body = MessageUtils.sanitize_string(original_body)
                if original_body != sanitized_body:
                    logger.debug(
                        "Sanitized unprintable characters in message body: %s -> %s",
                        original_body,
                        sanitized_body,
                    )
                if message.get("Body"):
                    message["Body"] = sanitized_body
                else:
                    message["body"] = sanitized_body

        # Generate a UUID if one is not provided
        if not message.get("wbor_message_id"):
            message["wbor_message_id"] = MessageUtils.gen_uuid()

        # Determine and invoke the appropriate handle
        # NOTE that the routing key[1] is the same as the body source field
        logger.debug("Handler query provided: `%s`", method.routing_key.split(".")[1])
        # `source.twilio.#` -> `twilio` or `source.standard.#` -> `standard`
        handler = MESSAGE_HANDLERS[method.routing_key.split(".")[1]]

        # `source.twilio.sms.incoming` -> `sms.incoming`
        subkey = ".".join(method.routing_key.split(".")[2:])

        # Validate success of handler.process_message
        result = handler.process_message(message, subkey, alreadysent)
        if result:
            # Send acknowledgment back to producer in cases where it is needed
            # e.g. for wbor-groupme-producer
            reply_to = properties.reply_to
            correlation_id = properties.correlation_id
            if reply_to and correlation_id:
                logger.debug(
                    "Sending acknowledgment for: %s", message.get("wbor_message_id")
                )
                send_acknowledgment(message, reply_to, correlation_id)

            ch.basic_ack(delivery_tag=method.delivery_tag)
            logger.info(
                "Message processed, logged, and acknowledged: %s",
                message.get("wbor_message_id"),
            )
        else:
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            logger.warning(
                "Message processing failed. Message requeued: %s",
                message.get("wbor_message_id"),
            )
    except (json.JSONDecodeError, KeyError) as e:
        logger.error("Failed to execute callback: %s", e)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def consume_messages():
    """
    Consume messages from the RabbitMQ queues.

    Sets up the connection and channel for each source, defined in SOURCES.
    Binds the queue to the EXCHANGE and starts consuming messages via callback.

    The callback function processes the message and acknowledges it if successful.
    """
    while True:
        logger.debug("Attempting to connect to RabbitMQ...")
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
        parameters = pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            credentials=credentials,
            client_properties={"connection_name": "GroupMeConsumerConnection"},
        )
        try:
            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()
            assert_exchange(channel)

            # Declare and bind queues dynamically
            for source, routing_key in SOURCES.items():
                queue_name = f"{source}"
                channel.queue_declare(queue=queue_name, durable=True)
                logger.debug("Queue declared: %s", queue_name)
                channel.queue_bind(
                    exchange=RABBITMQ_EXCHANGE,
                    queue=queue_name,
                    routing_key=routing_key,
                )
                logger.debug(
                    "Queue `%s` bound to `%s` with routing key %s",
                    queue_name,
                    RABBITMQ_EXCHANGE,
                    routing_key,
                )
                channel.basic_consume(
                    queue=queue_name,
                    on_message_callback=callback,
                    auto_ack=False,
                    consumer_tag=f"{source}_consumer",
                )

            logger.info("Connected to RabbitMQ & queues bound. Now consuming...")
            channel.start_consuming()
        except pika.exceptions.AMQPConnectionError as conn_error:
            error_message = str(conn_error)
            logger.error(
                "(Retrying in 5 seconds) Failed to connect to RabbitMQ: %s",
                error_message,
            )
            if "CONNECTION_FORCED" in error_message and "shutdown" in error_message:
                logger.critical(
                    "Broker shut down the connection. Shutting down consumer."
                )
                sys.exit(1)  # Exit the process to avoid infinite retries
            if "ACCESS_REFUSED" in error_message:
                logger.critical(
                    "Access refused. Check RabbitMQ user permissions. Shutting down consumer."
                )
                sys.exit(1)
            time.sleep(5)
