import asyncio
import datetime as dt
import re

import discord
import httpx

from app.utils import (
    DeleteMessage,
    MessageLinker,
    TTRCache,
    create_delete_hook,
    create_edit_hook,
    remove_view_after_timeout,
)

XKCD_REGEX = re.compile(r"\bxkcd#(\d+)", re.IGNORECASE)


class XKCDMentionCache(TTRCache[int, discord.Embed]):
    async def fetch(self, key: int) -> None:
        url = f"https://xkcd.com/{key}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{url}/info.0.json")

        xkcd = resp.json()
        date = dt.datetime(
            day=int(xkcd["day"]),
            month=int(xkcd["month"]),
            year=int(xkcd["year"]),
            tzinfo=dt.UTC,
        ).strftime("%B %-d, %Y")
        self[key] = (
            discord.Embed(title=xkcd["title"], url=url)
            .set_image(url=xkcd["img"])
            .set_footer(text=f"{xkcd['alt']} • {date}")
        )


xkcd_mention_cache = XKCDMentionCache(hours=12)
xkcd_mention_linker = MessageLinker()


class DeleteXKCDMention(DeleteMessage):
    linker = xkcd_mention_linker
    action_singular = "linked this XKCD comic"
    action_plural = "linked these XKCD comics"


async def xkcd_mention_message(
    message: discord.Message,
) -> tuple[list[discord.Embed], int]:
    matches = (
        xkcd_mention_cache.get(int(m[1])) for m in XKCD_REGEX.finditer(message.content)
    )
    embeds = await asyncio.gather(*matches)
    return embeds, len(embeds)


async def handle_xkcd_mentions(message: discord.Message) -> None:
    if message.author.bot:
        return
    embeds, count = await xkcd_mention_message(message)
    if count < 1:
        return
    try:
        sent_message = await message.reply(
            embeds=embeds, mention_author=False, view=DeleteXKCDMention(message, count)
        )
    except discord.HTTPException:
        return
    xkcd_mention_linker.link(message, sent_message)
    await remove_view_after_timeout(sent_message)


xkcd_mention_delete_hook = create_delete_hook(linker=xkcd_mention_linker)

xkcd_mention_edit_hook = create_edit_hook(
    linker=xkcd_mention_linker,
    message_processor=xkcd_mention_message,
    interactor=handle_xkcd_mentions,
    view_type=DeleteXKCDMention,
    embed_mode=True,
)
