import discord as dsc

from app.setup import bot, config
from app.utils import is_dm, try_dm


@bot.tree.command(name="accept-invite", description="Accept a pending tester invite.")
@dsc.app_commands.guild_only()
async def accept_invite(interaction: dsc.Interaction) -> None:
    assert not is_dm(interaction.user)

    await try_dm(interaction.user, config.ACCEPT_INVITE_URL, silent=True)
    await try_dm(
        interaction.user,
        "Ghostty is already out! 👉 https://ghostty.org/",
    )
    await interaction.response.send_message("Check your DMs!", ephemeral=True)

    if (log_channel := bot.get_channel(config.LOG_CHANNEL_ID)) is None:
        return
    assert isinstance(log_channel, dsc.TextChannel)
    await log_channel.send(
        f"{interaction.user.mention} accepted the invite!",
        allowed_mentions=dsc.AllowedMentions.none(),
    )
