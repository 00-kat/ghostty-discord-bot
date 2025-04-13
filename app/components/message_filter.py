import re
from collections.abc import Callable
from typing import NamedTuple, cast

import discord

from app.setup import config
from app.utils import format_or_file, try_dm

URL_REGEX = re.compile(
    r"https?:\/\/(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)"
)
MESSAGE_DELETION_TEMPLATE = (
    "Hey! Your message in {} was deleted because it did not contain {}."
    " Make sure to include {}, and respond in threads.\n"
)
MESSAGE_CONTENT_NOTICE = "Here's the message you tried to send:"
COPY_TEXT_HINT = (
    "-# **Hint:** You can get your original message with formatting preserved "
    'by using the "Copy Text" action on right-click.'
)
REGULAR_MESSAGE_TYPES = frozenset(
    {discord.MessageType.default, discord.MessageType.reply}
)


class MessageFilter(NamedTuple):
    channel_id: int
    filter: Callable[[discord.Message], object]
    template_fillers: tuple[str, str]


MESSAGE_FILTERS = (
    # Delete non-image messages in #showcase
    MessageFilter(
        config.SHOWCASE_CHANNEL_ID,
        lambda msg: cast("discord.Message", msg).attachments,
        ("any attachments", "a screenshot or a video"),
    ),
    # Delete non-link messages in #media
    MessageFilter(
        config.MEDIA_CHANNEL_ID,
        lambda msg: URL_REGEX.search(cast("discord.Message", msg).content),
        ("a link", "a link"),
    ),
)


async def check_message_filters(message: discord.Message) -> bool:
    for msg_filter in MESSAGE_FILTERS:
        if message.channel.id != msg_filter.channel_id or msg_filter.filter(message):
            continue

        await message.delete()

        # Don't DM the user if it's a system message
        # (e.g. "@user started a thread")
        if message.type not in REGULAR_MESSAGE_TYPES:
            continue

        assert isinstance(message.channel, discord.TextChannel)

        notification = MESSAGE_DELETION_TEMPLATE.format(
            message.channel.mention, *msg_filter.template_fillers
        )
        if content_size := len(message.content):
            notification += MESSAGE_CONTENT_NOTICE
        await try_dm(message.author, notification, silent=content_size > 0)

        if content_size > 0:
            content, file = format_or_file(message.content)
            await try_dm(message.author, content, file=file)
            await try_dm(message.author, COPY_TEXT_HINT, silent=True)

        return True
    return False
