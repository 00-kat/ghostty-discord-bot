from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, cast

import pytest

from tests.fixtures.hooks import TrackedCallable
from tests.hooks.utils import spawn_message

if TYPE_CHECKING:
    from unittest.mock import Mock

    from tests.fixtures.hooks import EditHook

    from app.common.linker import MessageLinker


@pytest.mark.asyncio
async def test_same_content(linker: MessageLinker, edit_hook: EditHook) -> None:
    msg = spawn_message(content="foo")
    msg2 = spawn_message(content="foo")
    linker.is_expired = TrackedCallable(linker.is_expired)

    await edit_hook(msg, msg2)
    assert not linker.is_expired.called


@pytest.mark.asyncio
async def test_message_expired(linker: MessageLinker, edit_hook: EditHook) -> None:
    msg = spawn_message(content="foo", age=dt.timedelta(days=2))
    msg2 = spawn_message(content="bar")
    linker.link(msg, msg)

    await edit_hook(msg, msg2)

    assert linker.is_expired(msg)
    assert not edit_hook.message_processor.called
    assert not linker.refs


@pytest.mark.asyncio
async def test_different_content_same_items(
    linker: MessageLinker, edit_hook: EditHook
) -> None:
    msg = spawn_message(content="foo 1")
    msg2 = spawn_message(content="bar 1")
    linker.get = TrackedCallable(linker.get)

    await edit_hook(msg, msg2)

    assert not linker.get.called


@pytest.mark.asyncio
async def test_different_items_unlinked_frozen(
    linker: MessageLinker, edit_hook: EditHook
) -> None:
    msg = spawn_message(content="foo 1")
    msg2 = spawn_message(content="foo 2")
    linker.is_expired = TrackedCallable(linker.is_expired)
    linker.freeze(msg)

    await edit_hook(msg, msg2)

    assert not edit_hook.interactor.called
    assert linker.is_expired.calls == 1


@pytest.mark.asyncio
async def test_different_items_unlinked_prior(
    linker: MessageLinker, edit_hook: EditHook
) -> None:
    msg = spawn_message(content="foo 1")
    msg2 = spawn_message(content="foo 2")
    linker.is_frozen = TrackedCallable(linker.is_frozen)

    await edit_hook(msg, msg2)

    assert linker.is_frozen.called
    assert not edit_hook.interactor.called


@pytest.mark.asyncio
async def test_new_items_edited_in(
    linker: MessageLinker, edit_hook: EditHook, capsys: pytest.CaptureFixture[str]
) -> None:
    msg = spawn_message(content="foo")
    msg2 = spawn_message(content="foo 1")
    linker.is_expired = TrackedCallable(linker.is_expired)

    await edit_hook(msg, msg2)

    assert linker.is_expired.calls == 1
    assert capsys.readouterr().out == "0x1\n"
    assert edit_hook.interactor.called


@pytest.mark.asyncio
async def test_different_items_linked_frozen(
    linker: MessageLinker, edit_hook: EditHook
) -> None:
    msg = spawn_message(content="foo 1")
    msg2 = spawn_message(content="foo 2")
    reply = cast("Mock", spawn_message(content="0x1"))
    linker.link(msg, reply)
    linker.freeze(msg)
    linker.is_frozen = TrackedCallable(linker.is_frozen)

    await edit_hook(msg, msg2)

    assert not reply.edit.called
    assert linker.is_frozen.calls == 1


@pytest.mark.asyncio
async def test_items_edited_out(linker: MessageLinker, edit_hook: EditHook) -> None:
    msg = spawn_message(content="foo 1")
    msg2 = spawn_message(content="foo")
    reply = cast("Mock", spawn_message(content="0x1"))
    linker.link(msg, reply)

    await edit_hook(msg, msg2)

    assert not linker.refs
    assert reply.delete.called


@pytest.mark.asyncio
async def test_items_edited(linker: MessageLinker, edit_hook: EditHook) -> None:
    msg = spawn_message(content="foo 1")
    msg2 = spawn_message(content="foo 2")
    reply = cast("Mock", spawn_message(content="0x1"))
    linker.link(msg, reply)

    await edit_hook(msg, msg2)

    assert reply.edit.call_count == 2
