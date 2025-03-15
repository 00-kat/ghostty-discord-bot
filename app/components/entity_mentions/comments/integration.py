from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from .fetching import get_comments
from app.components.entity_mentions.fmt import get_entity_emoji
from app.utils import (
    DeleteMessage,
    MessageLinker,
    create_delete_hook,
    create_edit_hook,
    remove_view_after_timeout,
)

if TYPE_CHECKING:
    from app.components.entity_mentions.models import Comment


comment_linker = MessageLinker()


class DeleteMention(DeleteMessage):
    linker = comment_linker
    action_singular = "linked this comment"
    action_plural = "linked these comments"


def comment_to_embed(comment: Comment) -> discord.Embed:
    title = (
        f"{emoji} {comment.entity.title}"
        if (emoji := get_entity_emoji(comment.entity))
        else comment.entity.title
    )
    return (
        discord.Embed(
            description=comment.body,
            title=title,
            url=comment.html_url,
            timestamp=comment.created_at,
            color=comment.color,
        )
        .set_author(**comment.author.model_dump())
        .set_footer(text=f"{comment.kind} on {comment.entity_gist}")
    )


async def reply_with_comments(message: discord.Message) -> None:
    if message.author.bot:
        return
    embeds = [
        comment_to_embed(comment) async for comment in get_comments(message.content)
    ]
    if not embeds:
        return
    if len(embeds) > 10:
        omitted = len(embeds) - 10
        note = f"{omitted} comment{'s were' if omitted > 1 else ' was'} omitted"
        embeds = embeds[:10]
    else:
        note = None
    sent_message = await message.reply(
        content=note,
        embeds=embeds,
        mention_author=False,
        view=DeleteMention(message, len(embeds)),
    )
    await message.edit(suppress=True)
    comment_linker.link(message, sent_message)
    await remove_view_after_timeout(sent_message)


async def comment_processor(msg: discord.Message) -> tuple[list[discord.Embed], int]:
    comments = [comment_to_embed(i) async for i in get_comments(msg.content)]
    return comments, len(comments)


entity_comment_delete_hook = create_delete_hook(linker=comment_linker)

entity_comment_edit_hook = create_edit_hook(
    linker=comment_linker,
    message_processor=comment_processor,
    interactor=reply_with_comments,
    view_type=DeleteMention,
    embed_mode=True,
)
