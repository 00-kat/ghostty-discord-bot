import asyncio
import datetime as dt
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field

import discord


@dataclass(frozen=True, slots=True, kw_only=True)
class ProcessedMessage:
    item_count: int
    content: str = ""
    files: list[discord.File] = field(default_factory=list[discord.File])
    embeds: list[discord.Embed] = field(default_factory=list[discord.Embed])


async def remove_view_after_timeout(
    message: discord.Message,
    timeout: float = 30.0,  # noqa: ASYNC109
) -> None:
    await asyncio.sleep(timeout)
    with suppress(discord.NotFound, discord.HTTPException):
        await message.edit(view=None)


class MessageLinker:
    def __init__(self) -> None:
        self._refs: dict[discord.Message, discord.Message] = {}
        self._frozen = set[discord.Message]()

    @property
    def expiry_threshold(self) -> dt.datetime:
        return dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=24)

    def freeze(self, message: discord.Message) -> None:
        self._frozen.add(message)

    def unfreeze(self, message: discord.Message) -> None:
        self._frozen.discard(message)

    def is_frozen(self, message: discord.Message) -> bool:
        return message in self._frozen

    def get(self, original: discord.Message) -> discord.Message | None:
        return self._refs.get(original)

    def link(self, original: discord.Message, reply: discord.Message) -> None:
        if original in self._refs:
            msg = f"message {original.id} already has a reply linked"
            raise ValueError(msg)
        self._refs[original] = reply

    def unlink(self, original: discord.Message) -> None:
        self._refs.pop(original, None)

    def get_original_message(self, reply: discord.Message) -> discord.Message | None:
        return next(
            (msg for msg, reply_ in self._refs.items() if reply == reply_), None
        )

    def unlink_from_reply(self, reply: discord.Message) -> None:
        if (original_message := self.get_original_message(reply)) is not None:
            self.unlink(original_message)

    def is_expired(self, message: discord.Message) -> bool:
        return message.created_at < self.expiry_threshold


def create_edit_hook(
    *,
    linker: MessageLinker,
    message_processor: Callable[[discord.Message], Awaitable[ProcessedMessage]],
    interactor: Callable[[discord.Message], Awaitable[None]],
    view_type: Callable[[discord.Message, int], discord.ui.View],
    view_timeout: float = 30.0,
) -> Callable[[discord.Message, discord.Message], Awaitable[None]]:
    async def edit_hook(before: discord.Message, after: discord.Message) -> None:
        if before.content == after.content:
            return

        if linker.is_expired(before):
            # The original message wasn't updated recently enough
            linker.unlink(before)
            return

        old_output = await message_processor(before)
        new_output = await message_processor(after)
        if old_output == new_output:
            # Message changed but objects are the same
            return

        if not (reply := linker.get(before)):
            if linker.is_frozen(before):
                return
            if old_output.item_count > 0:
                # The message was removed from the linker at some point (most likely
                # when the reply was deleted)
                return
            # There were no objects before, so treat this as a new message
            await interactor(after)
            return

        if linker.is_expired(reply):
            # The original message was updated recently enough, but the edits did not
            # affect the reply, so we can assume it's expired
            linker.unlink_from_reply(reply)
            linker.unfreeze(before)
            return

        if linker.is_frozen(before):
            return

        # Some processors use negative values to symbolize special error values, so this
        # can't be `== 0`. An example of this is the snippet_message() function in the
        # file app/components/github_integration/code_links.py
        if new_output.item_count <= 0:
            # All objects were edited out
            linker.unlink(before)
            await reply.delete()
            return

        await reply.edit(
            content=new_output.content,
            embeds=new_output.embeds,
            attachments=new_output.files,
            suppress=not new_output.embeds,
            view=view_type(after, new_output.item_count),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await remove_view_after_timeout(reply, view_timeout)

    return edit_hook


def create_delete_hook(
    *, linker: MessageLinker
) -> Callable[[discord.Message], Awaitable[None]]:
    async def delete_hook(message: discord.Message) -> None:
        if message.author.bot and (original := linker.get_original_message(message)):
            linker.unlink(original)
            linker.unfreeze(original)
        elif (reply := linker.get(message)) and not linker.is_frozen(message):
            if linker.is_expired(message):
                linker.unlink(message)
            else:
                # We don't need to do any unlinking here because reply.delete() triggers
                # on_message_delete which runs the current hook again, and since replies
                # are bot messages, linker.unlink_from_reply() handles unlinking for us.
                await reply.delete()
        linker.unfreeze(message)

    return delete_hook
