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
# The per-query bound, sent to the queryengine ( `?timeout_seconds=` ) :
# it stops swipl and answers HTTP 504, never an empty answer. Measured on
# a 1.2k-file Java repo ( 589 queries ) : every dataflow path found took
# <= 1.7 s; the seed query ~39 s alone, more with 10 loops in parallel.
DEFAULT_QUERY_TIMEOUT_SECONDS: typing.Final[int] = 45
DEFAULT_SEED_QUERY_TIMEOUT_SECONDS: typing.Final[int] = 60
# The http client waits this much longer than the bound it sent, so the
# 504 arrives instead of a client side timeout.
_HTTP_GRACE_SECONDS: typing.Final[float] = 15.0

_log = logging.getLogger(__name__)

# `WithDataFlowPath.Content` ( kbapi >= 2.0.0 ) : `NoDataFlowPath`, or the
# path under the field its constructor names
_DATAFLOW_PATH_FIELDS: typing.Final[dict[str, str]] = {
    "PlainDataFlowPath": "plainDataFlowPath",
    "DbWriteDataFlowPath": "dbWriteDataFlowPath",
}


def dataflow_path(content: typing.Any) -> typing.Optional[list[typing.Any]]:
    """The path of a ``FoundDataFlowPath`` reply's contents, ``None`` when there is none."""
    if not isinstance(content, dict):
        return None
    field = _DATAFLOW_PATH_FIELDS.get(str(content.get("tag")))
    inner = content.get("contents")
    path = inner.get(field) if field is not None and isinstance(inner, dict) else None
    return path if isinstance(path, list) else None


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
        query_timeout_seconds: int = DEFAULT_QUERY_TIMEOUT_SECONDS,
    ) -> None:
        self._kb_location = kb_location
        self._url = url
        self._query_timeout = query_timeout_seconds
        self._session = requests.Session()

    @property
    def kb_location(self) -> str:
        return self._kb_location

    def query(
        self,
        tag: str,
        contents: dict[str, typing.Any],
        *,
        timeout_seconds: typing.Optional[int] = None,
    ) -> dict[str, typing.Any]:
        """Fire one query. Returns the parsed JSON reply.

        ``timeout_seconds`` overrides the client's per-query bound for
        this one query ( eg the seed ).

        Both ``tag`` and ``contents`` are forwarded verbatim \u2014 the
        kbapi tagged-union discipline (Kbapi.Query) is enforced
        server-side, so we don't duplicate the enum here. If an
        unknown tag ends up on the wire the queryengine will reject
        it and we surface that rejection as a :class:`KbapiError`.
        """
        body: dict[str, typing.Any] = {"tag": tag, "contents": contents}
        bound = timeout_seconds or self._query_timeout
        params = {"kb_location": self._kb_location, "timeout_seconds": str(bound)}
        started = time.monotonic()
        try:
            resp = self._session.post(
                self._url,
                params=params,
                json=body,
                timeout=bound + _HTTP_GRACE_SECONDS,
            )
        except requests.exceptions.RequestException as exc:
            raise KbapiError(f"kbapi request failed: {exc}") from exc
        elapsed = time.monotonic() - started
        if resp.status_code != http.HTTPStatus.OK:
            # the body says why, eg qe's 504 "DataFlowPath timed out after
            # 45 s ( no answer, NOT an empty answer )" : the model reads it
            raise KbapiError(
                f"kbapi returned HTTP {resp.status_code} after {elapsed:.3f}s "
                f"for tag={tag!r}: {resp.text[:300]}"
            )
        try:
            reply = resp.json()
        except json.JSONDecodeError as exc:
            raise KbapiError(f"kbapi returned invalid JSON: {exc}") from exc
        if not isinstance(reply, dict):
            raise KbapiError(f"kbapi reply is not a JSON object: {type(reply).__name__}")
        _log.debug("kbapi %s -> %s (%.3fs)", tag, reply.get("tag"), elapsed)
        return reply
