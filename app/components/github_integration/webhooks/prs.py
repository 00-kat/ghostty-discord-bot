from __future__ import annotations

import datetime as dt
import difflib
from itertools import dropwhile
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

from loguru import logger

from app.components.github_integration.models import GitHubUser
from app.components.github_integration.webhooks.utils import (
    EmbedContent,
    Footer,
    send_embed,
)
from app.utils import truncate

if TYPE_CHECKING:
    from monalisten import Monalisten, events

    from app.bot import EmojiName, GhosttyBot

HUNK_CODEBLOCK_OVERHEAD = len("```diff\n\n```\n")


class PRLike(Protocol):
    number: int
    title: str
    html_url: str
    draft: Any
    merged_at: Any
    state: Any


def pr_footer(
    pr: PRLike, *, emoji: EmojiName | None = None, from_review: bool = False
) -> Footer:
    if emoji is None:
        # pull_request_review(_comment) events have pull_request objects that don't have
        # the .merged field, so we have to fall back to checking if .merged_at is truthy
        merged = pr.merged_at is not None if from_review else cast("Any", pr).merged
        state = cast("Literal['open', 'closed']", pr.state)
        emoji = "pull_" + ("draft" if pr.draft else "merged" if merged else state)
    return Footer(emoji, f"PR #{pr.number}: {pr.title}")


def pr_embed_content(
    pr: PRLike, template: str, body: str | None = None
) -> EmbedContent:
    return EmbedContent(template.format(f"PR #{pr.number}"), pr.html_url, body)


def register_hooks(bot: GhosttyBot, webhook: Monalisten) -> None:  # noqa: C901, PLR0915
    @webhook.event.pull_request.opened
    async def _(event: events.PullRequestOpened) -> None:
        pr = event.pull_request
        await send_embed(
            bot,
            event.sender,
            pr_embed_content(pr, "opened {}", pr.body),
            pr_footer(pr, emoji="pull_open"),
            color="green",
        )

    @webhook.event.pull_request.closed
    async def _(event: events.PullRequestClosed) -> None:
        pr = event.pull_request
        action, color = ("merged", "purple") if pr.merged else ("closed", "red")
        await send_embed(
            bot,
            event.sender,
            pr_embed_content(pr, f"{action} {{}}"),
            pr_footer(pr, emoji="pull_" + action),
            color=color,
        )

    @webhook.event.pull_request.reopened
    async def _(event: events.PullRequestReopened) -> None:
        pr = event.pull_request
        await send_embed(
            bot,
            event.sender,
            pr_embed_content(pr, "reopened {}"),
            pr_footer(pr, emoji="pull_open"),
            color="green",
        )

    @webhook.event.pull_request.edited
    async def _(event: events.PullRequestEdited) -> None:
        pr, changes = event.pull_request, event.changes

        if pr.created_at > dt.datetime.now(tz=dt.UTC) - dt.timedelta(minutes=15):
            return

        if changes.body and changes.body.from_:
            # Escape code block to avoid breaking diff
            from_file = changes.body.from_.replace("`", r"\`").splitlines(keepends=True)
            to_file = (
                pr.body.replace("`", r"\`").splitlines(keepends=True) if pr.body else ""
            )
            diff = "".join(
                difflib.unified_diff(
                    from_file,
                    to_file,
                    fromfile=changes.title.from_ if changes.title else pr.title,
                    tofile=pr.title,
                    tofiledate=pr.created_at.isoformat(),
                )
            )
            diff = truncate(diff, 500 - len("```diff\n\n```"))
            content = f"```diff\n{diff}\n```"
        elif changes.title:
            content = f'Renamed from "{changes.title.from_}" to "{pr.title}"'
        else:
            return

        assert event.sender
        await send_embed(
            bot,
            event.sender,
            pr_embed_content(pr, "edited {}", content),
            pr_footer(pr),
        )

    @webhook.event.pull_request.converted_to_draft
    async def _(event: events.PullRequestConvertedToDraft) -> None:
        pr = event.pull_request
        await send_embed(
            bot,
            event.sender,
            pr_embed_content(pr, "converted {} to draft"),
            pr_footer(pr, emoji="pull_draft"),
            color="gray",
        )

    @webhook.event.pull_request.ready_for_review
    async def _(event: events.PullRequestReadyForReview) -> None:
        pr = event.pull_request
        await send_embed(
            bot,
            event.sender,
            pr_embed_content(pr, "marked {} as ready for review"),
            pr_footer(pr, emoji="pull_open"),
            color="green",
        )

    @webhook.event.pull_request.locked
    async def _(event: events.PullRequestLocked) -> None:
        pr = event.pull_request
        template = "locked {}"
        if reason := pr.active_lock_reason:
            template += f" as {reason}"
        await send_embed(
            bot,
            event.sender,
            pr_embed_content(pr, template),
            pr_footer(pr),
            color="orange",
        )

    @webhook.event.pull_request.unlocked
    async def _(event: events.PullRequestUnlocked) -> None:
        pr = event.pull_request
        await send_embed(
            bot,
            event.sender,
            pr_embed_content(pr, "unlocked {}"),
            pr_footer(pr),
            color="blue",
        )

    @webhook.event.pull_request.review_requested
    async def _(event: events.PullRequestReviewRequested) -> None:
        pr = event.pull_request
        content = f"from {_format_reviewer(event)}"
        await send_embed(
            bot,
            event.sender,
            pr_embed_content(pr, "requested review for {}", content),
            pr_footer(pr),
        )

    @webhook.event.pull_request.review_request_removed
    async def _(event: events.PullRequestReviewRequestRemoved) -> None:
        pr = event.pull_request
        content = f"from {_format_reviewer(event)}"
        await send_embed(
            bot,
            event.sender,
            pr_embed_content(pr, "removed review request for {}", content),
            pr_footer(pr),
        )

    @webhook.event.pull_request_review.submitted
    async def _(event: events.PullRequestReviewSubmitted) -> None:
        pr, review = event.pull_request, event.review

        if review.state == "commented" and not review.body:
            # We most definitely have some pull_request_review_comment event(s)
            # happening at the same time, so an empty review like this can be ignored to
            # reduce spam.
            return

        match review.state:
            case "approved":
                color, title = "green", "approved"
            case "commented":
                color, title = None, "reviewed"
            case "changes_requested":
                color, title = "red", "requested changes in"
            case s:
                logger.warning("unexpected review state: {}", s)
                return

        emoji = "pull_" + (
            "draft" if pr.draft else "merged" if pr.merged_at else pr.state
        )
        await send_embed(
            bot,
            event.sender,
            EmbedContent(f"{title} PR #{pr.number}", review.html_url, review.body),
            pr_footer(pr, emoji=emoji),
            color=color,
        )

    @webhook.event.pull_request_review.dismissed
    async def _(event: events.PullRequestReviewDismissed) -> None:
        pr = event.pull_request
        emoji = "pull_" + (
            "draft" if pr.draft else "merged" if pr.merged_at else pr.state
        )
        review_author = (
            GitHubUser(**event.review.user.model_dump())
            if event.review.user
            else GitHubUser.default()
        )
        await send_embed(
            bot,
            event.sender,
            pr_embed_content(
                pr, "dismissed a {} review", f"authored by {review_author.hyperlink}"
            ),
            pr_footer(pr, emoji=emoji),
            color="orange",
        )

    @webhook.event.pull_request_review_comment.created
    async def _(event: events.PullRequestReviewCommentCreated) -> None:
        pr, content = event.pull_request, event.comment.body

        hunk = _reduce_diff_hunk(event.comment.diff_hunk)
        if 500 - len(content) - len(hunk) - HUNK_CODEBLOCK_OVERHEAD >= 0:
            # We can fit a hunk!
            content = f"```diff\n{hunk}\n```\n{content}"

        await send_embed(
            bot,
            event.sender,
            EmbedContent(
                f"left a review comment on PR #{pr.number}",
                event.comment.html_url,
                content,
            ),
            pr_footer(pr, from_review=True),
        )


def _reduce_diff_hunk(hunk: str) -> str:
    def missing_diff_marker(line: str) -> bool:
        return not line.startswith(("-", "+"))

    hunk_lines = [*dropwhile(missing_diff_marker, hunk.splitlines())]
    return "\n".join([*dropwhile(missing_diff_marker, hunk_lines[::-1])][::-1])


# Abusing `Any`/`getattr`/`hasattr` here because the API models are insufferable
def _format_reviewer(event: Any) -> str:
    if hasattr(event, "requested_team"):
        return f"the `{event.requested_team.name}` team"
    if requested_reviewer := getattr(event, "requested_reviewer", None):
        return GitHubUser(**requested_reviewer.model_dump()).hyperlink
    return "`?`"
