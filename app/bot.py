import asyncio
import datetime as dt
import importlib
import importlib.util
import pkgutil
import sys
from functools import cached_property
from pathlib import Path
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    LiteralString,
    cast,
    final,
    get_args,
    override,
)

import discord as dc
import sentry_sdk
from discord.ext import commands
from loguru import logger

from app.status import BotStatus
from toolbox.discord import pretty_print_account, try_dm
from toolbox.errors import handle_error, interaction_error_handler
from toolbox.messages import REGULAR_MESSAGE_TYPES

if TYPE_CHECKING:
    from app.config import Config, WebhookFeedType
    from toolbox.discord import Account
    from toolbox.misc import GH

EmojiName = Literal[
    "commit",
    "discussion",
    "discussion_answered",
    "discussion_duplicate",
    "discussion_outdated",
    "issue_closed_completed",
    "issue_closed_unplanned",
    "issue_open",
    "pull_closed",
    "pull_draft",
    "pull_merged",
    "pull_open",
]

_EMOJI_NAMES = frozenset(get_args(EmojiName))

# This set contains all emojis that were previously used but are no longer used by the
# bot. NOTE: when REMOVING or RENAMING an emoji name from the above literal, add it to
# this set. If an emoji with this name is found in the bot's application emojis, it will
# be removed automatically to clean up old emojis.
_OUTDATED_EMOJI_NAMES = frozenset[LiteralString]({
    # <- place outdated emoji names here (with a trailing comma).
})

# There must not be any overlap between the emoji names and outdated emoji names.
assert not _EMOJI_NAMES & _OUTDATED_EMOJI_NAMES, (
    "EmojiName args and _OUTDATED_EMOJI_NAMES overlap"
)

type Emojis = MappingProxyType[EmojiName, dc.Emoji | str]


@final
class GhosttyBot(commands.Bot):
    def __init__(self, config: Config, gh: GH) -> None:
        intents = dc.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(
            command_prefix=[],
            intents=intents,
            allowed_mentions=dc.AllowedMentions(everyone=False, roles=False),
        )

        self.tree.on_error = interaction_error_handler
        self.config = config
        self.gh = gh
        self.bot_status = BotStatus()

        self._ghostty_emojis: dict[EmojiName, dc.Emoji | str]
        self._ghostty_emojis = dict.fromkeys(_EMOJI_NAMES, "❓")
        self.ghostty_emojis: Emojis = MappingProxyType(self._ghostty_emojis)
        self.emojis_loaded = asyncio.Event()

    @override
    async def on_error(self, event_method: str, /, *args: Any, **kwargs: Any) -> None:
        handle_error(cast("BaseException", sys.exception()))

    @override
    async def load_extension(self, name: str, *, package: str | None = None) -> None:
        short_name = name.removeprefix("app.components.")
        logger.debug("loading extension {}", short_name)
        with sentry_sdk.start_span(op="bot.load_extension", name=short_name):
            await super().load_extension(name, package=package)

    async def _try_extension(
        self,
        operation: Literal["load", "unload"],
        name: str,
        *,
        package: str | None = None,
        user: Account | None = None,
    ) -> bool:
        extension_operation = (
            self.load_extension if operation == "load" else self.unload_extension
        )
        try:
            await extension_operation(name, package=package)
        except commands.ExtensionFailed as error:
            logger.opt(exception=error).exception(
                (f"{pretty_print_account(user)} " if user else "")
                + f"failed to {operation} `{name}`"
            )
        except commands.ExtensionError as error:
            message = (
                f"{user} " if user else ""
            ) + f"failed to {operation} `{name}`: {error}"
            logger.warning(message)
        else:
            return True
        return False

    async def try_load_extension(
        self, name: str, *, package: str | None = None, user: Account | None = None
    ) -> bool:
        return await self._try_extension("load", name, package=package, user=user)

    async def try_unload_extension(
        self, name: str, *, package: str | None = None, user: Account | None = None
    ) -> bool:
        return await self._try_extension("unload", name, package=package, user=user)

    @override
    async def setup_hook(self) -> None:
        with sentry_sdk.start_transaction(op="bot.setup", name="Initial load"):
            await self.bot_status.load_git_data()
            async with asyncio.TaskGroup() as group:
                for extension in self.get_component_extension_names():
                    group.create_task(self.load_extension(extension))
        logger.info("loaded {} extensions", len(self.extensions))

    async def on_ready(self) -> None:
        self.bot_status.last_login_time = dt.datetime.now(tz=dt.UTC)
        await self.load_emojis()
        logger.info("logged in as {}", self.user)

    @cached_property
    def ghostty_guild(self) -> dc.Guild:
        logger.debug("fetching ghostty guild")
        if self.config.guild_id and (guild := self.get_guild(self.config.guild_id)):
            logger.trace("found ghostty guild")
            return guild
        logger.info(
            "BOT_GUILD_ID unset or specified guild not found; using bot's first guild: "
            "{} (ID: {})",
            self.guilds[0].name,
            self.guilds[0].id,
        )
        return self.guilds[0]

    @cached_property
    def log_channel(self) -> dc.TextChannel:
        logger.debug("fetching log channel")
        channel = self.get_channel(self.config.log_channel_id)
        assert isinstance(channel, dc.TextChannel)
        return channel

    @cached_property
    def help_channel(self) -> dc.ForumChannel:
        logger.debug("fetching help channel")
        channel = self.get_channel(self.config.help_channel_id)
        assert isinstance(channel, dc.ForumChannel)
        return channel

    @cached_property
    def webhook_channels(self) -> dict[WebhookFeedType, dc.TextChannel]:
        channels: dict[WebhookFeedType, dc.TextChannel] = {}
        for feed_type, id_ in self.config.webhook_channel_ids.items():
            logger.debug("fetching {feed_type} webhook channel", feed_type)
            channel = self.ghostty_guild.get_channel(id_)
            if not isinstance(channel, dc.TextChannel):
                msg = (
                    "expected {} webhook channel to be a text channel"
                    if channel
                    else "failed to find {} webhook channel"
                )
                raise TypeError(msg.format(feed_type))
            channels[feed_type] = channel
        return channels

    def is_privileged(self, member: dc.Member) -> bool:
        return not (
            member.get_role(self.config.mod_role_id) is None
            and member.get_role(self.config.helper_role_id) is None
        )

    def is_ghostty_mod(self, user: Account) -> bool:
        member = self.ghostty_guild.get_member(user.id)
        return (
            member is not None and member.get_role(self.config.mod_role_id) is not None
        )

    def _fails_message_filters(self, message: dc.Message) -> bool:
        # This can't be the MessageFilter cog type because that would cause an import
        # cycle.
        message_filter: Any = self.get_cog("MessageFilter")
        return bool(message_filter and message_filter.check(message))

    @override
    async def on_message(self, message: dc.Message, /) -> None:
        if message.author.bot or message.type not in REGULAR_MESSAGE_TYPES:
            return

        # Simple test
        if message.guild is None and message.content == "ping":
            logger.debug("ping sent by {}", pretty_print_account(message.author))
            await try_dm(message.author, "pong")
            return

        if not self._fails_message_filters(message):
            self.dispatch("message_filter_passed", message)

    @classmethod
    def get_component_extension_names(cls) -> frozenset[str]:
        modules: set[str] = set()
        for module_info in pkgutil.walk_packages(
            [Path(__file__).parent / "components"], "app.components."
        ):
            if cls.is_valid_extension(module_info.name):
                modules.add(module_info.name)

        return frozenset(modules)

    @staticmethod
    def is_valid_extension(extension: str) -> bool:
        return (
            extension.startswith("app.components.")
            and bool(importlib.util.find_spec(extension))
            and callable(getattr(importlib.import_module(extension), "setup", None))
        )

    async def load_emojis(self) -> None:
        self.emojis_loaded.clear()

        emojis_path = Path(__file__).parent.parent / "emojis"  # it's outside `app`.
        emoji_files = {
            emoji: (emojis_path / f"{emoji}.png").read_bytes() for emoji in _EMOJI_NAMES
        }

        for emoji in await self.fetch_application_emojis():
            if emoji.name in _OUTDATED_EMOJI_NAMES:
                logger.info("removing outdated emoji '{}'", emoji.name)
                await emoji.delete()
                continue
            if emoji.name not in _EMOJI_NAMES:
                logger.debug("skipping emoji '{}'", emoji.name)
                continue
            try:
                if await emoji.read() != emoji_files[emoji.name]:
                    logger.info("updating out-of-date emoji '{}'", emoji.name)
                    # Discord doesn't support changing an emoji's contents, so reupload
                    # the new one under the same name.
                    await emoji.delete()
                    updated_emoji = await self.create_application_emoji(
                        name=emoji.name, image=emoji_files[emoji.name]
                    )
                else:
                    updated_emoji = emoji
            except Exception as e:  # noqa: BLE001
                # Don't break the other emojis if reading or reuploading a single emoji
                # fails.
                logger.opt(exception=e).error("failed to update emoji '{}'", emoji.name)
            else:
                self._ghostty_emojis[cast("EmojiName", emoji.name)] = updated_emoji
                logger.debug("loaded emoji '{}'", emoji.name)

        for emoji in self._ghostty_emojis:
            if self._ghostty_emojis[emoji] != "❓":
                # The emoji isn't missing.
                continue
            logger.info("uploading missing emoji '{}'", emoji)
            try:
                self._ghostty_emojis[emoji] = await self.create_application_emoji(
                    name=emoji, image=emoji_files[emoji]
                )
                logger.debug("loaded emoji '{}'", emoji)
            except Exception as e:  # noqa: BLE001
                # Don't break the other missing emojis if uploading one fails.
                logger.opt(exception=e).error(
                    "failed to upload missing emoji '{}'", emoji
                )

        self.emojis_loaded.set()
