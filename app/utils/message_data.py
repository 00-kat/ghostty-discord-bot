# PPE is strongly recommended in this file. Blindfolds are even better.

from __future__ import annotations

from contextlib import suppress
from io import BytesIO
from typing import Self

import discord

MAX_ATTACHMENT_SIZE = 67_108_864  # 64 MiB


class MessageData(discord.Message):
    files: list[discord.File]
    skipped_attachments: int

    def __init__(self, message: discord.Message) -> None:
        # This code cannot be in the scrape() constructor itself as the
        # subclass' __init__() *should not* be called, and overriding the
        # __init__() is the most elegant solution.
        for attr in dir(message):
            val = getattr(type(self), attr)
            if (
                # Don't break the class.
                attr == "__class__"
                # Acquired already by the subclass declaration.
                or isinstance(val, property)
                or callable(val)
            ):
                continue
            with suppress(AttributeError):
                # At the time of writing, the only things which cause an AttributeError
                # to be thrown are `call` and everything that starts with `_cs_`.
                setattr(self, attr, getattr(message, attr))

    @classmethod
    async def scrape(cls, message: discord.Message) -> Self:
        # This code cannot go in __init__ as it is async.
        msg_data = cls(message)
        await msg_data._get_files(message.attachments)
        return msg_data

    async def _get_files(self, attachments: list[discord.Attachment]) -> None:
        files: list[discord.File] = []
        skipped_attachments = 0
        for file in attachments:
            if file.size > MAX_ATTACHMENT_SIZE:
                skipped_attachments += 1
                continue
            fp = BytesIO(await file.read())
            files.append(discord.File(fp, filename=file.filename))
        self.files = files
        self.skipped_attachments = skipped_attachments
