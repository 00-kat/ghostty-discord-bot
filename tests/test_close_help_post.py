import datetime as dt
from types import SimpleNamespace
from typing import Any

import pytest
from githubkit.exception import RequestFailed

from tests.utils import kitposer as kp

from app.components.close_help_post import mention_entity
from app.components.github_integration.mentions.discussions import DISCUSSION_QUERY
from app.components.github_integration.models import GitHubUser


def fill_entity(**kwargs: Any) -> SimpleNamespace:
    defaults: dict[str, Any] = {
        "number": 0,
        "title": "",
        "body": None,
        "html_url": "https://github.com/trag1c/zig-codeblocks/issues/1",
        "user": GitHubUser(login="", url="", icon_url=""),
        "created_at": dt.datetime(1, 1, 1, tzinfo=dt.UTC),
        "state": False,
        "state_reason": None,
        "draft": False,
        "merged": False,
        "answer": None,
        "additions": 0,
        "deletions": 0,
        "changed_files": 0,
        "labels": [],
    }
    return SimpleNamespace(defaults | kwargs)


# Calling __new__ to skip initialization and having to pass in a proper Response object
failed_request = RequestFailed.__new__(RequestFailed)
repo = ("ghostty-org", "ghostty")
gh_env = kp.KitPoser({
    "/rest/pulls/async_get": {
        kp.Call(*repo, 1234): fill_entity(number=1234),
    },
    "/rest/issues/async_get": {
        kp.Call(*repo, 2354): failed_request,
        kp.Call(*repo, 1234): fill_entity(number=1234, pull_request=True),
        kp.Call(*repo, 189): fill_entity(number=189, pull_request=False),
    },
    "/graphql/arequest": {
        kp.Call(
            DISCUSSION_QUERY,
            variables={"number": 2354, "org": "ghostty-org", "repo": "ghostty"},
            __kitposer_wrap__=False,
        ): {"repository": {"discussion": fill_entity(number=2354).__dict__}},
    },
})


@pytest.mark.parametrize(
    ("entity_id", "kind"),
    [(189, "Issue"), (1234, "Pull Request"), (2354, "Discussion")],
)
@pytest.mark.asyncio
async def test_mention_entity(
    entity_id: int,
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
    bot_env: SimpleNamespace,
) -> None:
    mentions_subpkg_path = "app.components.github_integration.mentions"
    monkeypatch.setattr(f"{mentions_subpkg_path}.resolution.config", bot_env)
    monkeypatch.setattr(f"{mentions_subpkg_path}.cache.gh", gh_env)
    monkeypatch.setattr(f"{mentions_subpkg_path}.discussions.gh", gh_env)

    msg_content = await mention_entity(entity_id)

    assert msg_content is not None
    assert f"{kind} [#{entity_id}]" in msg_content


@pytest.mark.parametrize("entity_id", [-13, 1023, 8192])
@pytest.mark.asyncio
async def test_mention_missing_entity(
    entity_id: int, monkeypatch: pytest.MonkeyPatch, bot_env: SimpleNamespace
) -> None:
    mentions_subpkg_path = "app.components.github_integration.mentions"
    monkeypatch.setattr(f"{mentions_subpkg_path}.resolution.config", bot_env)
    monkeypatch.setattr(f"{mentions_subpkg_path}.cache.gh", gh_env)
    monkeypatch.setattr(f"{mentions_subpkg_path}.discussions.gh", gh_env)

    msg_content = await mention_entity(entity_id)

    assert msg_content is None
