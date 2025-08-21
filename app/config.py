import os

import dotenv

dotenv.load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]

GITHUB_ORG = os.environ["GITHUB_ORG"]
GITHUB_REPOS = dict(val.split(":") for val in os.environ["GITHUB_REPOS"].split(","))
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_WEBHOOK_URL = os.environ["GITHUB_WEBHOOK_URL"]
GITHUB_WEBHOOK_SECRET = os.environ["GITHUB_WEBHOOK_SECRET"]

ACCEPT_INVITE_URL = os.environ["BOT_ACCEPT_INVITE_URL"]
SENTRY_DSN = os.getenv("SENTRY_DSN")

HELP_CHANNEL_TAG_IDS = {
    name: int(id_)
    for name, id_ in (
        pair.split(":") for pair in os.environ["BOT_HELP_CHANNEL_TAG_IDS"].split(",")
    )
}

HELP_CHANNEL_ID = int(os.environ["BOT_HELP_CHANNEL_ID"])
LOG_CHANNEL_ID = int(os.environ["BOT_LOG_CHANNEL_ID"])
MEDIA_CHANNEL_ID = int(os.environ["BOT_MEDIA_CHANNEL_ID"])
SHOWCASE_CHANNEL_ID = int(os.environ["BOT_SHOWCASE_CHANNEL_ID"])
WEBHOOK_CHANNEL_ID = int(os.environ["BOT_WEBHOOK_CHANNEL_ID"])

MOD_ROLE_ID = int(os.environ["BOT_MOD_ROLE_ID"])
HELPER_ROLE_ID = int(os.environ["BOT_HELPER_ROLE_ID"])
