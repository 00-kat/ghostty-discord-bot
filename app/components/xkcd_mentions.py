from __future__ import annotations

import asyncio
import datetime as dt
import re

import discord
import httpx
from pydantic import BaseModel

from app.utils import (
    DeleteMessage,
    MessageLinker,
    TTRCache,
    create_delete_hook,
    create_edit_hook,
    remove_view_after_timeout,
)

SECONDS_IN_HOUR = 3600
XKCD_REGEX = re.compile(r"\bxkcd#(\d+)", re.IGNORECASE)
XKCD_URL = "https://xkcd.com/{}"


class XKCD(BaseModel):
    day: int
    month: int
    year: int
    img: str
    title: str
    transcript: str
    alt: str


class XKCDMentionCache(TTRCache[int, tuple[discord.Embed, str | None]]):
    async def fetch(self, key: int) -> None:
        url = XKCD_URL.format(key)
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{url}/info.0.json")
        if not resp.is_success:
            error = (
                f"XKCD #{key} does not exist."
                if resp.status_code == 404
                else f"Unable to fetch XKCD #{key}."
            )
            embed = discord.Embed(color=discord.Color.red()).set_footer(text=error)
            self[key] = (embed, None)
            return

        xkcd = XKCD(**resp.json())
        date = dt.datetime(
            day=xkcd.day,
            month=xkcd.month,
            year=xkcd.year,
            tzinfo=dt.UTC,
        ).strftime("%B %-d, %Y")
        self[key] = (
            discord.Embed(title=xkcd.title, url=url)
            .set_image(url=xkcd.img)
            .set_footer(text=f"{xkcd.alt} • {date}"),
            xkcd.transcript,
        )


xkcd_mention_cache = XKCDMentionCache(hours=12)
xkcd_mention_linker = MessageLinker()


def format_transcript(
    comic: int | str, name: str, transcript: str | None
) -> discord.Embed:
    embed = discord.Embed(
        title=name,
        url=XKCD_URL.format(comic),
        description=transcript or "This comic has no transcript.",
    )
    if not transcript:
        embed.color = discord.Color.red()
    if len(embed) > 6000:
        embed.color = discord.Color.red()
        embed.description = "This comic's transcript is too long to send."
    return embed


class TranscriptPicker(discord.ui.View):
    select: discord.ui.Select[TranscriptPicker]

    def __init__(self, transcripts: dict[int, tuple[str, str | None]]) -> None:
        super().__init__()
        self.transcripts = transcripts
        self._add_selection_box()

    def _add_selection_box(self) -> None:
        self.select = discord.ui.Select(
            placeholder="Select XKCD comics", max_values=len(self.transcripts)
        )
        for number, (name, _) in self.transcripts.items():
            self.select.add_option(label=name, value=str(number))
        self.select.callback = self._callback
        self.add_item(self.select)

    async def _callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            embeds=[
                format_transcript(comic, *self.transcripts[int(comic)])
                for comic in self.select.values
            ],
            view=None,
        )


class XKCDMentionActions(DeleteMessage):
    linker = xkcd_mention_linker
    action_singular = "linked this XKCD comic"
    action_plural = "linked these XKCD comics"

    async def _get_transcripts(
        self, embeds: list[discord.Embed]
    ) -> tuple[dict[int, tuple[str, str | None]], int]:
        transcripts: dict[int, tuple[str, str | None]] = {}
        failed = 0
        for embed in embeds:
            if not (embed.url and embed.title):
                continue
            number = int(embed.url.rstrip("/").rpartition("/")[2])
            _, transcript = await xkcd_mention_cache.get(number)
            if transcript is None:
                continue
            if not transcript:
                failed += 1
                transcript = None
            transcripts[number] = (embed.title, transcript)
        return transcripts, failed

    @discord.ui.button(
        label="Show Transcript", emoji="📜", style=discord.ButtonStyle.gray
    )
    async def show_transcript(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[XKCDMentionActions],
    ) -> None:
        reply, *_ = self.linker.get(self.message)
        transcripts, failed = await self._get_transcripts(reply.embeds)
        match len(transcripts) - failed:
            case 0:
                # None of the XKCD comics have a transcript available.
                await interaction.response.send_message(
                    "There are no transcripts available.", ephemeral=True
                )
            case 1:
                # Exactly one XKCD comic has a transcript available.
                # NOTE: this does not mean that there is only one comic, which
                # is why a list comprehension is still needed. When there is no
                # transcript, the embed simply contains an error message.
                await interaction.response.send_message(
                    embeds=[
                        format_transcript(comic, name, transcript)
                        for comic, (name, transcript) in transcripts.items()
                    ],
                    ephemeral=True,
                )
            case _:
                await interaction.response.send_message(
                    view=TranscriptPicker(transcripts),
                    ephemeral=True,
                )


async def xkcd_mention_message(
    message: discord.Message,
) -> tuple[list[discord.Embed], int]:
    embeds = []
    matches = list(dict.fromkeys(m[1] for m in XKCD_REGEX.finditer(message.content)))
    omitted = None
    if len(matches) > 10:
        omitted = discord.Embed(color=discord.Color.orange()).set_footer(
            text=f"{len(matches) - 9} XKCD comics were omitted."
        )
        # Nine instead of ten to account for the `omitted` embed.
        matches = matches[:9]
    tasks = (xkcd_mention_cache.get(int(m)) for m in matches)
    embeds = [embed for embed, _ in await asyncio.gather(*tasks)]
    if omitted:
        embeds.append(omitted)
    return embeds, len(embeds)


async def handle_xkcd_mentions(message: discord.Message) -> None:
    if message.author.bot:
        return
    embeds, count = await xkcd_mention_message(message)
    if count < 1:
        return
    try:
        sent_message = await message.reply(
            embeds=embeds, mention_author=False, view=XKCDMentionActions(message, count)
        )
    except discord.HTTPException:
        return
    xkcd_mention_linker.link(message, sent_message)
    await remove_view_after_timeout(sent_message, SECONDS_IN_HOUR)


xkcd_mention_delete_hook = create_delete_hook(linker=xkcd_mention_linker)

xkcd_mention_edit_hook = create_edit_hook(
    linker=xkcd_mention_linker,
    message_processor=xkcd_mention_message,
    interactor=handle_xkcd_mentions,
    view_type=XKCDMentionActions,
    embed_mode=True,
)
