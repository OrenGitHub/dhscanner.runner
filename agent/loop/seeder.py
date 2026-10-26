"""Initial queue = complete A \u222a B source surface (\u00a72.2).

At t=0 we fire one kbapi query \u2014 ``SelectHttpHandlers`` over every verb,
authenticated or not \u2014 and materialize every match as an
:class:`EndpointRef` on the work queue. Bucket C H2s are **not** seeded;
they enter later via pair-edge discoveries from in-flight sessions (\u00a74.7).

Verbal one-liner from \u00a72.2: *"we don't paginate. We enqueue."*
"""

from __future__ import annotations

import logging
import typing

from agent.loop.kbapi import KbapiClient, KbapiError
from agent.loop.types import EndpointBucket, EndpointRef, Location


_log = logging.getLogger(__name__)


# Deliberately permissive upper bound. The queryengine clamps match
# counts server-side anyway, and \u00a72.2 wants \"every bucket-A and
# bucket-B endpoint\" so pagination is explicitly rejected.
_SEED_LIMIT: typing.Final[int] = 10_000

_METHODS: typing.Final[dict[str, typing.Literal["GET", "POST", "PUT", "DELETE", "PATCH", "UNKNOWN"]]] = {
    "Get": "GET",
    "Post": "POST",
    "Put": "PUT",
    "Delete": "DELETE",
    "Patch": "PATCH",
    # reached by a request, verb registered elsewhere ( eg a servlet
    # method taking `HttpServletRequest request` ), url '{?}'
    "Unknown": "UNKNOWN",
}

_SEED_QUERY: typing.Final[dict[str, typing.Any]] = {
    "verbs": ["Get", "Post", "Put", "Delete", "Patch", "Unknown"],
    "authentications": ["Unauthenticated", "Authenticated"],
    "routeContainsUrlParts": None,
    "maxNumHttpHandlers": _SEED_LIMIT,
}


def seed_initial_queue(client: KbapiClient) -> list[EndpointRef]:
    """Fire the seed query. Return the endpoint set.

    Deduplicated on :pyattr:`EndpointRef.endpoint_id` so that a handler
    reported twice ( eg two mappings with the same url ) lands on the
    queue exactly once.
    """
    try:
        reply = client.query("SelectHttpHandlers", _SEED_QUERY)
    except KbapiError as exc:
        _log.warning("seed query SelectHttpHandlers failed: %s", exc)
        return []
    seen: dict[str, EndpointRef] = {}
    for ref in _project_matches(reply):
        if ref.endpoint_id not in seen:
            seen[ref.endpoint_id] = ref
    return list(seen.values())


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


def _project_matches(reply: dict[str, typing.Any]) -> list[EndpointRef]:
    tag = reply.get("tag")
    if tag != "FoundHttpHandlers":
        _log.warning("seed reply tag mismatch: expected FoundHttpHandlers, got %s", tag)
        return []
    contents = reply.get("contents") or {}
    out: list[EndpointRef] = []
    for match in contents.get("matches") or []:
        ref = _project_match(match)
        if ref is not None:
            out.append(ref)
    return out


def _project_match(match: typing.Any) -> typing.Optional[EndpointRef]:
    if not isinstance(match, dict):
        return None
    method = _METHODS.get(str(match.get("httpHandlerVerb")))
    url = match.get("httpHandlerUrl")
    if method is None or not isinstance(url, str):
        return None
    try:
        loc = Location.model_validate(match.get("httpHandlerLocation"))
    except Exception:  # pylint: disable=broad-except
        # Malformed KB payload \u2014 skip the match, not the whole
        # seed. The ScanTrace will still carry the raw reply.
        return None
    auth = match.get("httpHandlerAuth")
    inputs = match.get("httpHandlerUserInputs")
    return EndpointRef(
        method=method,
        url=url,
        handler_location=loc,
        bucket=EndpointBucket.AUTHENTICATED if isinstance(auth, dict) else EndpointBucket.PRE_AUTH,
        auth_func_name=auth.get("authenticationFunctionName") if isinstance(auth, dict) else None,
        auth_evidence=auth.get("authenticationEvidence") if isinstance(auth, dict) else None,
        user_inputs=[i for i in inputs if isinstance(i, dict)] if isinstance(inputs, list) else [],
    )
