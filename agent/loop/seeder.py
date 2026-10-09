"""Initial queue = complete A \u222a B source surface (\u00a72.2).

At t=0 we fire six kbapi queries \u2014
``{Unauthenticated, Authenticated} \u00d7 {Get, Post, Put}HandlerRequestObject``
\u2014 and materialize every match as an :class:`EndpointRef` on the
work queue. Bucket C H2s are **not** seeded; they enter later via
pair-edge discoveries from in-flight sessions (\u00a74.7).

Verbal one-liner from \u00a72.2: *"we don't paginate. We enqueue."*
"""

from __future__ import annotations

import logging
import typing

from agent.loop.kbapi import KbapiClient, KbapiError
from agent.loop.types import EndpointBucket, EndpointRef, Location


_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# One row per (method, bucket, query_tag). Each row names the Content.hs
# field accessors we need to project a match into an :class:`EndpointRef`.
# When a new HTTP verb gets its own kbapi query (PATCH / DELETE / HEAD /
# OPTIONS), this is the only place in the loop that needs updating \u2014
# add a row, no caller churn.
# ---------------------------------------------------------------------------


class _SeedShape(typing.NamedTuple):
    method: typing.Literal["GET", "POST", "PUT"]
    bucket: EndpointBucket
    query_tag: str
    result_tag: str
    matches_field: str
    handler_loc_field: str
    url_field: str
    # Only set for authenticated buckets.
    auth_func_name_field: typing.Optional[str] = None
    auth_evidence_field: typing.Optional[str] = None


_SEED_SHAPES: tuple[_SeedShape, ...] = (
    _SeedShape(
        method="GET",
        bucket=EndpointBucket.PRE_AUTH,
        query_tag="UnauthenticatedHttpGetHandlerRequestObject",
        result_tag="FoundUnauthenticatedHttpGetHandlerRequestObject",
        matches_field="foundUnauthenticatedHttpGetHandlerRequestObjectMatches",
        handler_loc_field="foundHttpGetHandlerLocation",
        url_field="foundHttpGetHandlerRequestObjectMatchUrl",
    ),
    _SeedShape(
        method="GET",
        bucket=EndpointBucket.AUTHENTICATED,
        query_tag="AuthenticatedHttpGetHandlerRequestObject",
        result_tag="FoundAuthenticatedHttpGetHandlerRequestObject",
        matches_field="foundAuthenticatedHttpGetHandlerRequestObjectMatches",
        handler_loc_field="foundAuthenticatedHttpGetHandlerLocation",
        url_field="foundAuthenticatedHttpGetHandlerRequestObjectMatchUrl",
        auth_func_name_field="foundAuthenticatedHttpGetHandlerAuthenticatingFunctionName",
        auth_evidence_field="foundAuthenticatedHttpGetHandlerAuthEvidence",
    ),
    _SeedShape(
        method="POST",
        bucket=EndpointBucket.PRE_AUTH,
        query_tag="UnauthenticatedHttpPostHandlerRequestObject",
        result_tag="FoundUnauthenticatedHttpPostHandlerRequestObject",
        matches_field="foundUnauthenticatedHttpPostHandlerRequestObjectMatches",
        handler_loc_field="foundHttpPostHandlerLocation",
        url_field="foundHttpPostHandlerRequestObjectMatchUrl",
    ),
    _SeedShape(
        method="POST",
        bucket=EndpointBucket.AUTHENTICATED,
        query_tag="AuthenticatedHttpPostHandlerRequestObject",
        result_tag="FoundAuthenticatedHttpPostHandlerRequestObject",
        matches_field="foundAuthenticatedHttpPostHandlerRequestObjectMatches",
        handler_loc_field="foundAuthenticatedHttpPostHandlerLocation",
        url_field="foundAuthenticatedHttpPostHandlerRequestObjectMatchUrl",
        auth_func_name_field="foundAuthenticatedHttpPostHandlerAuthenticatingFunctionName",
        auth_evidence_field="foundAuthenticatedHttpPostHandlerAuthEvidence",
    ),
    _SeedShape(
        method="PUT",
        bucket=EndpointBucket.PRE_AUTH,
        query_tag="UnauthenticatedHttpPutHandlerRequestObject",
        result_tag="FoundUnauthenticatedHttpPutHandlerRequestObject",
        matches_field="foundUnauthenticatedHttpPutHandlerRequestObjectMatches",
        handler_loc_field="foundHttpPutHandlerLocation",
        url_field="foundHttpPutHandlerRequestObjectMatchUrl",
    ),
    _SeedShape(
        method="PUT",
        bucket=EndpointBucket.AUTHENTICATED,
        query_tag="AuthenticatedHttpPutHandlerRequestObject",
        result_tag="FoundAuthenticatedHttpPutHandlerRequestObject",
        matches_field="foundAuthenticatedHttpPutHandlerRequestObjectMatches",
        handler_loc_field="foundAuthenticatedHttpPutHandlerLocation",
        url_field="foundAuthenticatedHttpPutHandlerRequestObjectMatchUrl",
        auth_func_name_field="foundAuthenticatedHttpPutHandlerAuthenticatingFunctionName",
        auth_evidence_field="foundAuthenticatedHttpPutHandlerAuthEvidence",
    ),
)


# Deliberately permissive upper bound. The queryengine clamps match
# counts server-side anyway, and \u00a72.2 wants \"every bucket-A and
# bucket-B endpoint\" so pagination is explicitly rejected.
_SEED_PER_QUERY_LIMIT: typing.Final[int] = 10_000


def seed_initial_queue(client: KbapiClient) -> list[EndpointRef]:
    """Fire all six seed queries. Return the concatenated endpoint set.

    Deduplicated on :pyattr:`EndpointRef.endpoint_id` so that an
    endpoint that happens to match both an auth and a pre-auth
    recognizer (shouldn't happen, but let's be defensive) lands on
    the queue exactly once.
    """
    seen: dict[str, EndpointRef] = {}
    for shape in _SEED_SHAPES:
        try:
            reply = client.query(
                shape.query_tag,
                _seed_contents(shape),
            )
        except KbapiError as exc:
            _log.warning("seed query %s failed: %s", shape.query_tag, exc)
            continue
        for ref in _project_matches(reply, shape):
            if ref.endpoint_id not in seen:
                seen[ref.endpoint_id] = ref
    return list(seen.values())


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


def _seed_contents(shape: _SeedShape) -> dict[str, typing.Any]:
    """Build the ``contents`` payload for one of the six seed queries.

    All six share the same two-field shape (``urlParts``, ``limit``)
    just under a different field-name prefix \u2014 we take advantage of
    the regularity rather than hand-write six payloads.
    """
    # Haskell field prefix: foo + XxxUrlParts / XxxLimit. We derive it
    # from the Query tag by lowercasing the first char \u2014 same
    # convention Aeson uses.
    prefix = shape.query_tag[0].lower() + shape.query_tag[1:]
    return {
        f"{prefix}UrlParts": [],
        f"{prefix}Limit": _SEED_PER_QUERY_LIMIT,
    }


def _project_matches(
    reply: dict[str, typing.Any],
    shape: _SeedShape,
) -> list[EndpointRef]:
    tag = reply.get("tag")
    if tag != shape.result_tag:
        _log.warning(
            "seed reply tag mismatch: expected %s, got %s", shape.result_tag, tag,
        )
        return []
    contents = reply.get("contents") or {}
    matches = contents.get(shape.matches_field) or []
    out: list[EndpointRef] = []
    for match in matches:
        if not isinstance(match, dict):
            continue
        loc_dict = match.get(shape.handler_loc_field)
        if not isinstance(loc_dict, dict):
            continue
        url = match.get(shape.url_field)
        if not isinstance(url, str):
            continue
        try:
            loc = Location.model_validate(loc_dict)
        except Exception:  # pylint: disable=broad-except
            # Malformed KB payload \u2014 skip the match, not the whole
            # seed. The ScanTrace will still carry the raw reply.
            continue
        auth_func_name: typing.Optional[str] = None
        auth_evidence: typing.Optional[dict[str, typing.Any]] = None
        if shape.auth_func_name_field is not None:
            maybe_name = match.get(shape.auth_func_name_field)
            if isinstance(maybe_name, str):
                auth_func_name = maybe_name
        if shape.auth_evidence_field is not None:
            maybe_evidence = match.get(shape.auth_evidence_field)
            if isinstance(maybe_evidence, dict):
                auth_evidence = maybe_evidence
        out.append(
            EndpointRef(
                method=shape.method,
                url=url,
                handler_location=loc,
                bucket=shape.bucket,
                auth_func_name=auth_func_name,
                auth_evidence=auth_evidence,
            ),
        )
    return out
