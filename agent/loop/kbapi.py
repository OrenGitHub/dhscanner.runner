"""Thin HTTP client against the queryengine kbapi.

Mirrors the request shape ``agent/explore.py`` and ``agent/test.py``
already use: ``POST http://localhost:3000/api?kb_location=<kb>`` with
JSON body ``{"tag": "...", "contents": {...}}`` per
``dhscanner.packages/dhscanner.kbapi/src/Kbapi.hs``.

The outer loop treats this as a *pure function* of
``(kb_location, query)`` (\u00a72.2): stateless on the server side, no
cursors, no pagination. Every call is independently replayable from
the ScanTrace.
"""

from __future__ import annotations

import http
import json
import logging
import time
import typing

import requests


DEFAULT_URL: typing.Final[str] = "http://localhost:3000/api"
DEFAULT_TIMEOUT_SECONDS: typing.Final[float] = 30.0

_log = logging.getLogger(__name__)


class KbapiError(RuntimeError):
    """Any non-2xx or malformed-JSON kbapi reply. The outer loop
    surfaces this to the LLM session as a tool error so the model
    can try a different query within its remaining budget."""


class KbapiClient:
    def __init__(
        self,
        kb_location: str,
        *,
        url: str = DEFAULT_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._kb_location = kb_location
        self._url = url
        self._timeout = timeout_seconds
        self._session = requests.Session()

    @property
    def kb_location(self) -> str:
        return self._kb_location

    def query(self, tag: str, contents: dict[str, typing.Any]) -> dict[str, typing.Any]:
        """Fire one query. Returns the parsed JSON reply.

        Both ``tag`` and ``contents`` are forwarded verbatim \u2014 the
        kbapi tagged-union discipline (Kbapi.Query) is enforced
        server-side, so we don't duplicate the enum here. If an
        unknown tag ends up on the wire the queryengine will reject
        it and we surface that rejection as a :class:`KbapiError`.
        """
        body = {"tag": tag, "contents": contents}
        params = {"kb_location": self._kb_location}
        started = time.monotonic()
        try:
            resp = self._session.post(
                self._url,
                params=params,
                json=body,
                timeout=self._timeout,
            )
        except requests.exceptions.RequestException as exc:
            raise KbapiError(f"kbapi request failed: {exc}") from exc
        elapsed = time.monotonic() - started
        if resp.status_code != http.HTTPStatus.OK:
            raise KbapiError(
                f"kbapi returned HTTP {resp.status_code} after {elapsed:.3f}s "
                f"for tag={tag!r}"
            )
        try:
            reply = resp.json()
        except json.JSONDecodeError as exc:
            raise KbapiError(f"kbapi returned invalid JSON: {exc}") from exc
        if not isinstance(reply, dict):
            raise KbapiError(f"kbapi reply is not a JSON object: {type(reply).__name__}")
        _log.debug("kbapi %s -> %s (%.3fs)", tag, reply.get("tag"), elapsed)
        return reply
