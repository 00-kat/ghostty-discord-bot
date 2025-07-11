import re
from io import BytesIO
from typing import Self

import discord
from zig_codeblocks import (
    DEFAULT_THEME,
    CodeBlock,
    extract_codeblocks,
    highlight_zig_code,
    process_markdown,
)

from app.utils import ItemActions, MessageLinker, remove_view_after_timeout
from app.utils.hooks import ProcessedMessage, create_delete_hook, create_edit_hook
from app.utils.webhooks import get_or_create_webhook, move_message_via_webhook

MAX_CONTENT = 51_200  # 50 KiB
MAX_ZIG_FILE_SIZE = 8_388_608  # 8 MiB
FILE_HIGHLIGHT_NOTE = 'On desktop, click "View whole file" to see the highlighting.'

# This pattern is intentionally simple; it's only meant to operate on sequences produced
# by zig-codeblocks which will never appear in any other form.
SGR_PATTERN = re.compile(r"\x1b\[[0-9;]+m")
THEME = DEFAULT_THEME.copy()
del THEME["Comment"]

codeblock_linker = MessageLinker()
frozen_messages = set[discord.Message]()


def apply_discord_wa(source: str) -> str:
    # From Qwerasd:
    #   Oh is it a safeguard against catastrophic backtracking?
    #   [...]
    #   I got distracted and checked the Discord source and this is the logic,
    #   highlighting is disabled under these circumstances:
    #   * The src contains 15 or more consecutive slashes
    #   * The src contains a line with 1000 or more characters
    #   * The src contains more than 30 slashes with anything in between as long as
    #     it's not a line that isn't in the form ^\s*\/\/.* and contains a character
    #     other than /
    # These replace calls are an attempt to work around these limitations.
    return source.replace("///", "\x1b[0m///").replace("// ", "\x1b[0m// ")


class CodeblockActions(ItemActions):
    linker = codeblock_linker
    action_singular = "sent this code block"
    action_plural = "sent these code blocks"

    def __init__(self, message: discord.Message, item_count: int) -> None:
        super().__init__(message, item_count)
        replaced_content = apply_discord_wa(process_markdown(message.content, THEME))
        if message.attachments or len(replaced_content) > 2000:
            self.replace.disabled = True
        else:
            self._replaced_message_content = replaced_content

    @discord.ui.button(label="Replace my message", emoji="🔄")
    async def replace(
        self, interaction: discord.Interaction, _: discord.ui.Button[Self]
    ) -> None:
        if await self._reject_early(interaction, "replace"):
            return

        assert interaction.message
        channel = interaction.message.channel
        webhook_channel, thread = (
            (channel.parent, channel)
            if isinstance(channel, discord.Thread)
            else (channel, discord.utils.MISSING)
        )
        assert isinstance(webhook_channel, discord.TextChannel | discord.ForumChannel)

        webhook = await get_or_create_webhook(webhook_channel)
        self.message.content = self._replaced_message_content
        await move_message_via_webhook(
            webhook, self.message, thread=thread, include_move_marks=False
        )


async def codeblock_processor(message: discord.Message) -> ProcessedMessage:
    attachments: list[discord.File] = []
    for att in message.attachments:
        if not att.filename.endswith(".zig") or att.size > MAX_ZIG_FILE_SIZE:
            continue
        content = (await att.read())[:MAX_CONTENT]
        if content.count(b"\n") <= 5 and len(content) <= 1900:
            message.content = f"{CodeBlock('zig', content.decode())}\n{message.content}"
            continue
        attachments.append(
            discord.File(
                BytesIO(highlight_zig_code(content, THEME).encode()),
                att.filename + ".ansi",
            )
        )

    codeblocks = list(extract_codeblocks(message.content))
    if (
        codeblocks
        and len(message.content) <= 2000
        and any(block.lang == "zig" for block in codeblocks)
    ):
        highlighted_codeblocks = [
            CodeBlock("ansi", apply_discord_wa(highlight_zig_code(c.body, THEME)))
            for c in codeblocks
        ]
        max_length = 2000 - (len(FILE_HIGHLIGHT_NOTE) - 1 if attachments else 0)
        while len(code := "\n\n".join(map(str, highlighted_codeblocks))) > max_length:
            file = discord.File(
                BytesIO(highlighted_codeblocks.pop().body.encode()),
                filename=f"{len(highlighted_codeblocks)}.ansi",
            )
            attachments.append(file)
        if attachments:
            code += f"\n{FILE_HIGHLIGHT_NOTE}"
        return ProcessedMessage(
            content=code,
            files=attachments,
            item_count=len(highlighted_codeblocks) + len(attachments),
        )
    if attachments:
        return ProcessedMessage(
            content=FILE_HIGHLIGHT_NOTE, files=attachments, item_count=len(attachments)
        )
    return ProcessedMessage(item_count=0)


async def check_for_zig_code(message: discord.Message) -> None:
    if message.author.bot:
        return
    output = await codeblock_processor(message)
    if not output.item_count:
        return
    reply = await message.reply(
        output.content,
        view=CodeblockActions(message, output.item_count),
        files=output.files,
        mention_author=False,
    )
    codeblock_linker.link(message, reply)
    await remove_view_after_timeout(reply, 60)


zig_codeblock_delete_hook = create_delete_hook(linker=codeblock_linker)

zig_codeblock_edit_hook = create_edit_hook(
    linker=codeblock_linker,
    message_processor=codeblock_processor,
    interactor=check_for_zig_code,
    view_type=CodeblockActions,
    view_timeout=60,
)
