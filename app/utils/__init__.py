from __future__ import annotations

import asyncio
import datetime as dt
import re
from collections import defaultdict
from contextlib import suppress
from textwrap import shorten
from typing import TYPE_CHECKING, Any

import discord

from .message_data import MessageData, scrape_message_data
from .webhooks import (
    GuildTextChannel,
    format_or_file,
    get_ghostty_guild,
    get_or_create_webhook,
    move_message_via_webhook,
)
from app.setup import config

__all__ = (
    "Account",
    "DeleteMessage",
    "GuildTextChannel",
    "MessageData",
    "MessageLinker",
    "escape_special",
    "format_or_file",
    "get_ghostty_guild",
    "get_or_create_webhook",
    "is_dm",
    "is_helper",
    "is_mod",
    "move_message_via_webhook",
    "remove_view_after_timeout",
    "scrape_message_data",
    "try_dm",
)

if TYPE_CHECKING:
    from typing_extensions import TypeIs


_INVITE_LINK_REGEX = re.compile(r"\b(?:https?://)?(discord\.gg/[^\s]+)\b")
_ORDERED_LIST_REGEX = re.compile(r"^(\d+)\. (.*)")

type Account = discord.User | discord.Member


class MessageLinker:
    def __init__(self) -> None:
        self._refs = defaultdict[discord.Message, list[discord.Message]](list)

    def get(self, original: discord.Message) -> list[discord.Message]:
        return self._refs[original]

    def link(self, original: discord.Message, *replies: discord.Message) -> None:
        self._refs[original].extend(replies)

    def unlink(self, original: discord.Message) -> None:
        del self._refs[original]

    def get_original_message(self, reply: discord.Message) -> discord.Message | None:
        return next(
            (msg for msg, replies in self._refs.items() if reply in replies), None
        )

    def unlink_from_reply(self, reply: discord.Message) -> None:
        if (original_message := self.get_original_message(reply)) is not None:
            self.unlink(original_message)

    def unlink_if_expired(self, reply: discord.Message) -> bool:
        # Stop reacting to message updates after 24 hours
        last_updated = reply.edited_at or reply.created_at
        if dt.datetime.now(tz=dt.UTC) - last_updated > dt.timedelta(hours=24):
            self.unlink_from_reply(reply)
            return True
        return False


class DeleteMessage(discord.ui.View):
    linker: MessageLinker
    action_singular: str
    action_plural: str

    def __init__(self, message: discord.Message, item_count: int) -> None:
        super().__init__()
        self.message = message
        self.item_count = item_count

    @discord.ui.button(
        label="Delete",
        emoji="🗑️",
        style=discord.ButtonStyle.gray,
    )
    async def delete(
        self, interaction: discord.Interaction, _: discord.ui.Button[DeleteMessage]
    ) -> None:
        assert not is_dm(interaction.user)
        if interaction.user.id == self.message.author.id or is_mod(interaction.user):
            assert interaction.message
            await interaction.message.delete()
            self.linker.unlink_from_reply(interaction.message)
            return

        await interaction.response.send_message(
            "Only the person who "
            + (self.action_singular if self.item_count == 1 else self.action_plural)
            + " can remove this message.",
            ephemeral=True,
        )


def is_dm(account: Account) -> TypeIs[discord.User]:
    return not isinstance(account, discord.Member)


def is_mod(member: discord.Member) -> bool:
    return member.get_role(config.MOD_ROLE_ID) is not None


def is_helper(member: discord.Member) -> bool:
    return member.get_role(config.HELPER_ROLE_ID) is not None


async def try_dm(account: Account, content: str, **extras: Any) -> None:
    if account.bot:
        return
    try:
        await account.send(content, **extras)
    except discord.Forbidden:
        print(f"Failed to DM {account} with: {shorten(content, width=50)}")


async def remove_view_after_timeout(
    message: discord.Message,
    timeout: float = 30.0,  # noqa: ASYNC109
) -> None:
    await asyncio.sleep(timeout)
    with suppress(discord.NotFound, discord.HTTPException):
        await message.edit(view=None)


def dynamic_timestamp(dt: dt.datetime, fmt: str | None = None) -> str:
    fmt = f":{fmt}" if fmt is not None else ""
    return f"<t:{int(dt.timestamp())}{fmt}>"


def escape_special(content: str) -> str:
    """
    Escape all text that Discord considers to be special.

    Consider adding the following kwargs to `send()`-like functions too:
        suppress_embeds=True,
        allowed_mentions=discord.AllowedMentions.none(),
    """
    escaped = discord.utils.escape_mentions(content)
    escaped = discord.utils.escape_markdown(escaped)
    # escape_mentions() doesn't deal with anything other than username
    # mentions.
    escaped = escaped.replace("<", r"\<").replace(">", r"\>")
    # Invite links are not embeds and are hence not suppressed by that flag.
    escaped = _INVITE_LINK_REGEX.sub(r"<https://\1>", escaped)
    # escape_markdown() doesn't deal with ordered lists.
    return "\n".join(
        _ORDERED_LIST_REGEX.sub(r"\1\. \2", line) for line in escaped.splitlines()
    )


def truncate(s: str, length: int, *, suffix: str = "…") -> str:
    if len(s) <= length:
        return s
    return s[: length - len(suffix)] + suffix
