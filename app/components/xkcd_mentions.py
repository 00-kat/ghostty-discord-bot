from __future__ import annotations

import asyncio
import datetime as dt
import re
from typing import TYPE_CHECKING, final, override

import discord as dc
import httpx
from discord.ext import commands
from pydantic import BaseModel

from app.common.cache import TTRCache
from app.common.linker import (
    ItemActions,
    MessageLinker,
    ProcessedMessage,
    remove_view_after_delay,
)

if TYPE_CHECKING:
    from app.bot import GhosttyBot

XKCD_REGEX = re.compile(r"\bxkcd#(\d+)", re.IGNORECASE)
XKCD_URL = "https://xkcd.com/{}"


class XKCD(BaseModel):
    day: int
    month: int
    year: int
    img: str
    title: str
    alt: str


class XKCDMentionCache(TTRCache[int, dc.Embed]):
    @override
    async def fetch(self, key: int) -> None:
        url = XKCD_URL.format(key)
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{url}/info.0.json")
        if not resp.is_success:
            error = (
                f"xkcd #{key} does not exist."
                if resp.status_code == 404
                else f"Unable to fetch xkcd #{key}."
            )
            self[key] = dc.Embed(color=dc.Color.red()).set_footer(text=error)
            return

        xkcd = XKCD(**resp.json())
        date = dt.datetime(
            day=xkcd.day, month=xkcd.month, year=xkcd.year, tzinfo=dt.UTC
        )
        self[key] = (
            dc.Embed(title=xkcd.title, url=url)
            .set_image(url=xkcd.img)
            .set_footer(text=f"{xkcd.alt} • {date:%B %-d, %Y}")
        )


@final
class XKCDActions(ItemActions):
    action_singular = "linked this xkcd comic"
    action_plural = "linked these xkcd comics"


@final
class XKCDMentions(commands.Cog):
    def __init__(self, bot: GhosttyBot) -> None:
        self.bot = bot
        self.linker = MessageLinker()
        XKCDActions.linker = self.linker
        self.cache = XKCDMentionCache(hours=12)

    async def process(self, message: dc.Message) -> ProcessedMessage:
        embeds = []
        matches = list(
            dict.fromkeys(m[1] for m in XKCD_REGEX.finditer(message.content))
        )
        omitted = None
        embeds = [
            embed
            for embed in await asyncio.gather(
                *(self.cache.get(int(m)) for m in matches)
            )
            if embed
        ]
        if len(embeds) > 10:
            omitted = dc.Embed(color=dc.Color.orange()).set_footer(
                text=f"{len(embeds) - 9} xkcd comics were omitted."
            )
            # Nine instead of ten to account for the `omitted` embed.
            embeds = embeds[:9]
        if omitted:
            embeds.append(omitted)
        return ProcessedMessage(embeds=embeds, item_count=len(embeds))

    @commands.Cog.listener("on_message")
    async def handle_mentions(self, message: dc.Message) -> None:
        if message.author.bot or self.bot.fails_message_filters(message):
            return
        output = await self.process(message)
        if output.item_count < 1:
            return
        try:
            sent_message = await message.reply(
                embeds=output.embeds,
                mention_author=False,
                view=XKCDActions(message, output.item_count),
            )
        except dc.HTTPException:
            return
        self.linker.link(message, sent_message)
        await remove_view_after_delay(sent_message)

    @commands.Cog.listener()
    async def on_message_delete(self, message: dc.Message) -> None:
        await self.linker.delete(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: dc.Message, after: dc.Message) -> None:
        await self.linker.edit(
            before,
            after,
            message_processor=self.process,
            interactor=self.handle_mentions,
            view_type=XKCDActions,
        )


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(XKCDMentions(bot))
