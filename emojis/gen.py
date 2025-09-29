#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "pydantic-settings>=2.10.1,<3",
#   "loguru~=0.7.0",
#   "svg.py~=1.9.0",
#   "cairosvg~=2.8.2",
# ]
# ///

# NOTE: don't forget to update EmojiName (and potentially _OUTDATED_EMOJI_NAMES) in
# app/bot.py when adding or removing emojis!

import os
import sys
from pathlib import Path
from typing import Literal, get_args

import cairosvg
import svg
from loguru import logger
from pydantic import Field
from pydantic_settings import BaseSettings, CliPositionalArg

EmojiName = Literal["commit", "issue_closed_unplanned"]


class Settings(
    BaseSettings,
    cli_parse_args=True,
    cli_enforce_required=True,
    cli_prog_name="emojis/gen.py",
    cli_kebab_case=True,
    cli_implicit_flags=True,
):
    """Generate emoji files used by the bot"""

    emojis: CliPositionalArg[list[EmojiName]] = Field(
        # Convert to a list so that the help text default doesn't show a tuple.
        list(get_args(EmojiName)),
        description="emojis to generate",
    )

    size: int = Field(128, description="size of emojis, in pixels")
    padding: float = Field(
        6.0, description="amount of padding around emojis, in pixels"
    )
    stroke_width: float = Field(
        12.0, description="stroke width used for primary strokes, in pixels"
    )
    ornament_stroke_width: float = Field(
        5.0,
        description="stroke width used for ornaments (such as symbols inside issue "
        "icons), in pixels",
    )

    gray: str = "#9198A1"
    purple: str = "#AB7DF8"
    green: str = "#3FB950"
    red: str = "#F85149"
    commit_gray: str = Field("#808080", description="color used for commit emoji")


def commit(s: Settings) -> svg.SVG:
    scale = 256 / s.size
    return svg.SVG(
        width=s.size,
        height=s.size,
        viewBox="-128 -128 256 256",
        elements=[
            svg.Circle(
                r=52,
                stroke=s.commit_gray,
                stroke_width=s.stroke_width * scale,
                fill="none",
            ),
            svg.Line(
                x1=-52,
                x2=-128,
                stroke=s.commit_gray,
                stroke_width=s.stroke_width * scale,
                stroke_linecap="round",
            ),
            svg.Line(
                x1=52,
                x2=128,
                stroke=s.commit_gray,
                stroke_width=s.stroke_width * scale,
                stroke_linecap="round",
            ),
        ],
    )


def check(s: Settings, intersection_x: int, intersection_y: int) -> svg.Polyline:
    # TODO
    pass


def issue_circle(s: Settings, color: str) -> svg.Circle:
    return svg.Circle(
        cx=s.size / 2,
        cy=s.size / 2,
        r=s.size / 2 - s.padding,
        stroke=color,
        stroke_width=s.stroke_width,
        fill="none",
    )


def issue_closed_unplanned(s: Settings) -> svg.SVG:
    return svg.SVG(
        width=s.size,
        height=s.size,
        elements=[issue_circle(s, s.gray)],
    )


def main() -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        # While $LOGURU_LEVEL is checked at import time, it doesn't override this value,
        # so manually handle it.
        level=os.getenv("LOGURU_LEVEL") or os.getenv("LOG_LEVEL") or "INFO",
    )

    logger.debug("parsing cli args")
    settings = Settings()
    for emoji in settings.emojis:
        logger.info("generating emoji '{}'", emoji)
        emoji_svg = globals()[emoji](settings)
        path = Path(__file__).parent / f"{emoji}.png"
        logger.debug("writing emoji '{}' as png to path {}", emoji, path)
        cairosvg.svg2png(bytestring=str(emoji_svg), write_to=str(path))


if __name__ == "__main__":
    main()
