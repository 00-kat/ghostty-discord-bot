from typing import TYPE_CHECKING, cast

from app.config import Config, config_var

if TYPE_CHECKING:
    from contextvars import Token

    from app.bot import GhosttyBot


def config() -> Token[Config]:
    """
    Intended to be used as a context manager:

        with config():
            ...
    """
    return config_var.set(Config(".env.example", bot=cast("GhosttyBot", object())))
