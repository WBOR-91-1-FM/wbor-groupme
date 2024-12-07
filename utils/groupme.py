"""
Module for handling GroupMe-specific message sending and processing.
"""

import time
import requests
from utils.logging import configure_logging
from utils.message import MessageUtils
from rabbitmq.publisher import publish_log_pg
from config import (
    GROUPCHAT_NAME,
    GROUPME_API,
    GROUPME_IMAGE_API,
    GROUPME_BOT_ID,
    GROUPME_ACCESS_TOKEN,
    GROUPME_CHARACTER_LIMIT,
)

logger = configure_logging(__name__)


class GroupMe:
    """
    Handles GroupMe-specific message sending and processing.
    """

    @staticmethod
    def upload_image(image_url, uid):
        """
        Upload an image to GroupMe's image service.

        Parameters:
        - image_url (str): The URL of the image to upload

        Returns:
        - dict: The JSON response from the GroupMe API, including the GroupMe image URL
        - None: If the upload fails

        Throws:
        - ValueError: If the image file type is unsupported
        - Exception: If the image fails to download from Twilio
        """
        mime_types = {
            "image/gif": ".gif",
            "image/jpeg": ".jpeg",
            "image/png": ".png",
        }

        try:
            # Download the image from a URL (in this case, Twilio's MediaUrl)
            image_response = requests.get(image_url, stream=True, timeout=10)
            if image_response.status_code != 200:
                raise requests.exceptions.RequestException(
                    f"Failed to download image from {image_url}: \
                    {image_response.status_code}"
                )

            content_type = image_response.headers.get("Content-Type", "").lower()
            file_extension = mime_types.get(content_type)

            if not file_extension:
                logger.warning(
                    "Unsupported content type `%s`. "
                    "Must be one of: image/gif, image/jpeg, image/png",
                    content_type,
                )
                return None

            headers = {
                "X-Access-Token": GROUPME_ACCESS_TOKEN,
                "Content-Type": content_type,
            }

            # Upload the downloaded image to GroupMe
            response = requests.post(
                GROUPME_IMAGE_API,
                headers=headers,
                data=image_response.content,
                timeout=10,
            )

            if response.status_code == 200:
                logger.debug("Upload successful: %s", response.json())
                return response.json()
            logger.warning(
                "Upload failed: %s - %s", response.status_code, response.text
            )

            publish_log_pg(
                image_response.content,
                response.status_code,
                uid,
                key="groupme.img",
            )
            return None
        except requests.exceptions.RequestException as e:
            logger.error(
                "Exception occurred while processing image %s: %s", image_url, e
            )
            return None

    @staticmethod
    def split_message(body):
        """
        Split a message body string if it exceeds GroupMe's character limit.

        Parameters:
        - body (str): The message string

        Returns:
        - list: A list of message segment strings
        """
        segments = [
            body[i : i + GROUPME_CHARACTER_LIMIT]
            for i in range(0, len(body), GROUPME_CHARACTER_LIMIT)
        ]
        return segments

    @staticmethod
    def send_text_segments(segments, uid):
        """
        Send each text segment to GroupMe.
        Pre-process the text to include segment labels (if applicable) and an end marker.
        A delay is added between each segment to prevent rate limiting.

        Parameters:
        - segments (list): A list of message segment strings
        - uid (str): The unique message ID (generated by message originator)

        Returns:
        - None
        """
        before_dash_split = uid.split("-", 1)[0]  # Get the first part of the UID

        total_segments = len(segments)
        for index, segment in enumerate(segments, start=1):
            segment_label = (
                f"({index}/{total_segments}):\n" if total_segments > 1 else ""
            )
            end_marker = (
                f"\n---UID---\n{before_dash_split}\n---------"
                if index == total_segments
                else ""
            )
            data = {
                "text": f'{segment_label}"{segment}"{end_marker}',
            }
            GroupMe.send_to_groupme(data, uid=uid)
            time.sleep(0.1)  # Rate limit to prevent GroupMe API rate limiting

    @staticmethod
    def send_images(images):
        """
        Send images to GroupMe if any are present.
        A delay is added between each image to prevent rate limiting.

        Parameters:
        - images (list): A list of image URLs from GroupMe's image service

        Returns:
        - None
        """
        for image_url in images:
            # Construct body for image sending
            image_data = {
                "picture_url": image_url,
                "text": "",
            }
            GroupMe.send_to_groupme(image_data)
            time.sleep(0.1)

    @staticmethod
    def send_to_groupme(body, uid=MessageUtils.gen_uuid(), bot_id=GROUPME_BOT_ID):
        """
        Make the actual HTTP POST request to GroupMe API. Logs the request in Postgres.

        Parameters:
        - body (dict): The message body to send.
            Assumes it is constructed, only needs the bot ID.
        - bot_id (str): The GroupMe bot ID from the group to send the message to

        Returns:
        - None

        Throws:
        - requests.exceptions.RequestException: If the HTTP POST request fails
        """
        body["bot_id"] = bot_id

        response = requests.post(GROUPME_API, json=body, timeout=10)

        if response.status_code in {200, 202}:
            if body.get("text"):
                logger.info(
                    "Message sent successfully to %s:\n\n%s\n",
                    GROUPCHAT_NAME,
                    body.get("text"),
                )
            elif body.get("picture_url"):
                logger.info("Image sent successfully: %s", body.get("picture_url"))
        else:
            logger.error(
                "Failed to send message: %s - %s", response.status_code, response.text
            )
        publish_log_pg(body, response.status_code, uid, key="groupme.msg")
