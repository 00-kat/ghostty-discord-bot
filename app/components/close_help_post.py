from types import SimpleNamespace
from typing import TYPE_CHECKING, Literal, cast, final

import discord as dc
from discord import app_commands
from discord.ext import commands

from app.components.github_integration import fmt
from app.utils import is_dm, is_helper, is_mod

if TYPE_CHECKING:
    from app.bot import GhosttyBot
    from app.components.docs import Docs

# https://discord.com/developers/docs/topics/opcodes-and-status-codes#http-http-response-codes
INVALID_REQUEST_DATA = 400
# https://discord.com/developers/docs/topics/opcodes-and-status-codes#json
INVALID_FORM_BODY = 50035

POST_TITLE_TOO_LONG = (
    "I couldn't change the post title as it was over 100 characters after modification."
)


@final
@app_commands.guild_only()
class Close(commands.GroupCog, group_name="close"):
    def __init__(self, bot: "GhosttyBot") -> None:
        self.description = "Mark current post as resolved."
        self.bot = bot

    @app_commands.command(name="solved", description="Mark post as solved.")
    @app_commands.describe(config_option="Config option name (optional)")
    async def solved(
        self, interaction: dc.Interaction, config_option: str | None = None
    ) -> None:
        if config_option:
            docs = cast("Docs | None", self.bot.cogs.get("Docs"))
            if not docs:
                await interaction.response.send_message(
                    "Docs are disabled", ephemeral=True
                )
                return
            try:
                additional_reply = docs.get_docs_link("option", config_option)
            except ValueError:
                await interaction.response.send_message(
                    f"Invalid config option: `{config_option}`", ephemeral=True
                )
                return
            title_prefix = f"[SOLVED: {config_option}]"
        else:
            title_prefix = additional_reply = None
        await self.close_post(interaction, "solved", title_prefix, additional_reply)

    @app_commands.command(name="moved", description="Mark post as moved to GitHub.")
    @app_commands.describe(entity_id="New GitHub entity number")
    async def moved(self, interaction: dc.Interaction, entity_id: int) -> None:
        if not (additional_reply := await self.mention_entity(entity_id)):
            await interaction.response.send_message(
                f"Entity #{entity_id} does not exist.", ephemeral=True
            )
            return
        await self.close_post(
            interaction,
            "moved",
            title_prefix=f"[MOVED: #{entity_id}]",
            additional_reply=additional_reply,
        )

    @app_commands.command(name="duplicate", description="Mark post as duplicate.")
    @app_commands.describe(
        original="The original GitHub entity (number) or help post (ID or link)"
    )
    async def duplicate(self, interaction: dc.Interaction, original: str) -> None:
        *_, str_id = original.rpartition("/")
        try:
            id_ = int(str_id)
        except ValueError:
            await interaction.response.send_message("Invalid ID.", ephemeral=True)
            return
        if len(str_id) < 10:
            # GitHub entity number
            title_prefix = f"[DUPLICATE: #{id_}]"
            if not (additional_reply := await self.mention_entity(int(id_))):
                await interaction.response.send_message(
                    f"Entity #{id_} does not exist.", ephemeral=True
                )
                return
        else:
            # Help post ID
            title_prefix = None
            additional_reply = f"Duplicate of: <#{id_}>"
        await self.close_post(interaction, "duplicate", title_prefix, additional_reply)

    @app_commands.command(name="stale", description="Mark post as stale.")
    async def stale(self, interaction: dc.Interaction) -> None:
        await self.close_post(interaction, "stale")

    @app_commands.command(name="wontfix", description="Mark post as stale.")
    async def wontfix(self, interaction: dc.Interaction) -> None:
        await self.close_post(interaction, "stale", "[WON'T FIX]")

    @app_commands.command(name="upstream", description="Mark post as stale.")
    async def upstream(self, interaction: dc.Interaction) -> None:
        await self.close_post(interaction, "stale", "[UPSTREAM]")

    async def close_post(
        self,
        interaction: dc.Interaction,
        tag: Literal["solved", "moved", "duplicate", "stale"],
        title_prefix: str | None = None,
        additional_reply: str | None = None,
    ) -> None:
        post = interaction.channel
        user = interaction.user

        assert not is_dm(user)
        if not isinstance(post, dc.Thread) or not (
            is_mod(user) or is_helper(user) or user.id == post.owner_id
        ):
            await interaction.response.send_message(
                (
                    "This command can only be used in"
                    f" <#{self.bot.config.help_channel_id}> "
                    "posts, by helpers or the thread owner."
                ),
                ephemeral=True,
            )
            return
        assert isinstance(post, dc.Thread)
        assert post.parent_id == self.bot.config.help_channel_id

        help_tags = {
            tag
            for tag in cast("dc.ForumChannel", post.parent).available_tags
            if tag.id in self.bot.config.help_channel_tag_ids.values()
        }

        if set(post.applied_tags) & help_tags:
            await interaction.response.send_message(
                "This post was already resolved.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        desired_tag_id = self.bot.config.help_channel_tag_ids[tag]
        await post.add_tags(next(tag for tag in help_tags if tag.id == desired_tag_id))

        if title_prefix is None:
            title_prefix = f"[{tag.upper()}]"

        try:
            await post.edit(name=f"{title_prefix} {post.name}")
            followup = "Post closed."
        except dc.HTTPException as e:
            # Re-raise if it's not because the new post title was invalid.
            if e.status != INVALID_REQUEST_DATA or e.code != INVALID_FORM_BODY:
                raise

            # HACK: there does not appear to be any way to get the actual error without
            # parsing the returned string or using a private field. This is likely
            # a limitation of discord.py, as the Discord API documentation mentions:
            #     Some of these errors may include additional details in the form of
            #     Error Messages provided by an errors object.
            # in https://discord.com/developers/docs/topics/opcodes-and-status-codes#json.
            # Both approaches are going to be tried... here be dragons.
            try:
                returned_error = cast("str", e._errors["name"]["_errors"][0]["message"])  # pyright: ignore [reportOptionalSubscript, reportPrivateUsage] # noqa: SLF001
            except (AttributeError, LookupError, TypeError):
                returned_error = str(e)

            if "or fewer in length" not in returned_error.casefold():
                raise  # The error wasn't that the post title was too long.

            followup = POST_TITLE_TOO_LONG

            delim = ";" if ":" in title_prefix else ":"
            title_prefix = title_prefix.strip("[]").lower()
            additional_reply = f"\n{additional_reply}" if additional_reply else ""
            additional_reply = f"**Closed{delim} {title_prefix}**.{additional_reply}"

        if additional_reply:
            await post.send(additional_reply)

        await interaction.followup.send(followup, ephemeral=True)

    @staticmethod
    async def mention_entity(entity_id: int) -> str | None:
        output = await fmt.entity_message(
            # Forging a message to use the entity mention logic
            cast("dc.Message", SimpleNamespace(content=f"#{entity_id}"))
        )
        return output.content or None


async def setup(bot: "GhosttyBot") -> None:
    await bot.add_cog(Close(bot))
