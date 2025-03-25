import datetime as dt
from collections.abc import Sequence
from typing import cast

import discord
from discord.ext import tasks

from app.components.status import bot_status
from app.setup import bot, config
from app.utils import post_is_solved


@tasks.loop(hours=1)
async def autoclose_solved_posts() -> None:
    closed_posts: list[discord.Thread] = []
    failures: list[discord.Thread] = []

    one_day_ago = dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=24)
    three_days_ago = dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=24 * 3)

    help_channel = cast(discord.ForumChannel, bot.get_channel(config.HELP_CHANNEL_ID))
    open_posts = len(help_channel.threads)
    for post in help_channel.threads:
        if post.last_message_id is None:
            failures.append(post)
            continue
        post_time = discord.utils.snowflake_time(post.last_message_id)
        if post.archived or not post_is_solved(post):
            if post_time < three_days_ago:
                await post.add_tags(
                    discord.ForumTag(name="stale"),
                    reason="Post inactive for over three days.",
                )
            continue
        if post_time < one_day_ago:
            await post.edit(archived=True)
            closed_posts.append(post)

    log_channel = cast(discord.TextChannel, bot.get_channel(config.LOG_CHANNEL_ID))
    bot_status.last_scan_results = (
        dt.datetime.now(tz=dt.UTC),
        open_posts,
        len(closed_posts),
    )
    msg = f"Scanned {open_posts:,} open posts in {help_channel.mention}.\n"
    if closed_posts:
        msg += f"Automatically closed {_post_list(closed_posts)}"
    if failures:
        msg += f"Failed to check {_post_list(failures)}"
    await log_channel.send(msg)


def _post_list(posts: Sequence[discord.Thread]) -> str:
    return (
        f"{len(posts)} solved posts:\n"
        + "".join(f"* {post.mention}\n" for post in posts[:30])
        + (f"* [...] ({len(posts) - 30:,} more)\n" if len(posts) > 30 else "")
    )
