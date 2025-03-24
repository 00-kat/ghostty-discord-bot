"""Toolkit for monkeypatching githubkit requests"""

from collections.abc import Awaitable
from typing import Any, Self, cast


class PoserSetupError(RuntimeError):
    pass


class KitResponse[T]:
    def __init__(self, value: T) -> None:
        self._value = value

    @property
    def parsed_data(self) -> T:
        return self._value


async def fake_request[T](obj: T) -> Awaitable[T]:
    return obj  # pyright: ignore [reportReturnType]


class Call:
    make_async: bool
    make_kitresponse: bool

    def __init__(self, *args: object, **kwargs: object) -> None:
        self._a = args
        self._kw = kwargs
        self.make_async = cast(bool, kwargs.pop("__kitposer_async__", True))
        self.make_kitresponse = cast(bool, kwargs.pop("__kitposer_wrap__", True))

    def __hash__(self) -> int:
        return hash((str(self._a), str(self._kw)))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Call):
            return NotImplemented
        return hash(self) == hash(other)


class KitPoser:
    def __init__(
        self, responses: dict[str, dict[Call, Any]], context: str = ""
    ) -> None:
        self.responses = responses
        self._context = context

    def __getattr__(self, attr: str) -> Self:
        context = f"{self._context}/{attr}"
        return type(self)(self.responses, context)

    def __call__(self, *a: object, **kw: object) -> Any:
        if self._context not in self.responses:
            msg = f"Unexpected call for context {self._context!r}"
            raise PoserSetupError(msg)

        blackbox = self.responses[self._context]
        # HACK: Fetching the original key instead of doing "Call(*a, **kw) in blackbox"
        # to preserve the __kitposer_*__ settings.
        arg_store = next((call for call in blackbox if call == Call(*a, **kw)), None)
        if arg_store is None:
            msg = f"Unexpected case for call context {self._context!r}: {a}; {kw}"
            raise PoserSetupError(msg)

        result = blackbox[arg_store]
        if isinstance(result, BaseException):
            raise result

        if arg_store.make_kitresponse:
            result = KitResponse(result)
        if arg_store.make_async:
            result = fake_request(result)

        return result
