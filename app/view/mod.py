import discord

from app.setup import bot
from app.utils import get_or_create_webhook, move_message_via_webhook


class SelectChannel(discord.ui.View):
    def __init__(self, message: discord.Message, executor: discord.Member):
        super().__init__()
        self.message = message
        self.executor = executor

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Select a channel",
        min_values=1,
        max_values=1,
    )
    async def select_channel(
        self, interaction: discord.Interaction, sel: discord.ui.ChannelSelect
    ) -> None:
        channel = await bot.fetch_channel(sel.values[0].id)
        if channel.id == self.message.channel.id:
            await interaction.response.send_message(
                "You can't move a message to the same channel.", ephemeral=True
            )
            return

        webhook = await get_or_create_webhook("Ghostty Moderator", channel)
        await move_message_via_webhook(webhook, self.message, self.executor)
        await interaction.response.edit_message(
            content=f"Moved the message to {channel.mention}.", view=None
        )
