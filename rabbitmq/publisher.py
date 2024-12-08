"""
RabbitMQ Publisher module.
"""

import json
import pika
import pika.exceptions
from utils.logging import configure_logging
from config import RABBITMQ_HOST, RABBITMQ_USER, RABBITMQ_PASS, RABBITMQ_EXCHANGE
from rabbitmq.util import assert_exchange


logger = configure_logging(__name__)


def publish_message(
    request_body,
    routing_key,
    connection_name="GroupMePublisherConnection",
    extra_properties=None,
):
    """
    Publish a message to RabbitMQ.

    Parameters:
    - request_body (dict): The message request body to publish
    - routing_key (str): The routing key for the message
        - e.g. `standard` from /send
    - connection_name (str): RabbitMQ connection name (default: "GroupMePublisherConnection")
    - extra_properties (dict, optional): Additional properties for the message (e.g., headers)

    Returns:
    - None
    """

    # Append "source." to the routing key
    routing_key = f"source.{routing_key}"

    try:
        logger.debug("Connecting to RabbitMQ...")
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
        parameters = pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            credentials=credentials,
            client_properties={"connection_name": connection_name},
        )
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        logger.debug("RabbitMQ connected!")
        assert_exchange(channel)

        logger.debug("Attempting to publish message with routing key: %s", routing_key)
        properties = pika.BasicProperties(
            headers={"x-retry-count": 0},  # Initialize retry count for other consumers
            delivery_mode=2,  # Make the message persistent
        )
        if extra_properties:
            properties.headers.update(extra_properties)

        channel.basic_publish(
            exchange=RABBITMQ_EXCHANGE,
            routing_key=routing_key,
            body=json.dumps(request_body).encode(),
            properties=properties,
        )
        logger.info("Message published: %s", request_body)
        connection.close()
    except pika.exceptions.AMQPConnectionError as e:
        logger.error(
            'Connection error when publishing to exchange with routing key "%s": %s',
            routing_key,
            e,
        )
    except json.JSONDecodeError as e:
        logger.error("JSON encoding error for message %s: %s", request_body, e)


def publish_log_pg(body, source, statuscode, uid, routing_key="groupme", sub_key="log"):
    """
    Log message actions in Postgres by publishing to the RabbitMQ exchange.

    `groupme.img` are image service API calls, whereas,
    `groupme.msg` are GroupMe message service API calls.

    Parameters:
    - body (dict): The body to publish
    - source (str): The source of the body
        - e.g. "groupme", "twilio", "standard"
    - statuscode (int): The status code of the body
    - uid (str): The unique identifier for the body
    - routing_key (str): The routing key for the body, defaults to "groupme"
    - sub_key (str): The sub-key for the body, defaults to "log"
    """
    publish_message(
        request_body={
            **body,
            "source": source,
            "code": statuscode,
            "type": sub_key,
            "uid": uid,
        },
        routing_key=routing_key,
        connection_name="GroupMeLogPublisherConnection",
    )