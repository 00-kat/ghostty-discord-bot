import asyncio
from contextlib import suppress

from githubkit import GitHub
from loguru import logger

from app import log
from app.bot import GhosttyBot
from app.config import Config, config_var, gh_var


async def main() -> None:
    config = Config(".env")
    gh = GitHub(config.github_token.get_secret_value())
    with config_var.set(config), gh_var.set(gh):
        log.setup()
        logger.trace("creating GhosttyBot instance for starting bot")
        async with GhosttyBot() as bot:
            logger.debug("starting the bot")
            # Use config_var.get() instead of config as any of the previous calls could
            # have set it to a different value for any reason.
            await bot.start(config_var.get().token.get_secret_value())


with suppress(KeyboardInterrupt):
    asyncio.run(main())
