"""Pydantic I/O contracts for the outer loop.

Everything crossing an actor boundary (LLM -> outer loop,
outer loop -> trace, outer loop -> findings store) is one of
these models. Nothing else in the package should hand-roll a dict
or a dataclass that lives on the wire -- all serialization goes
through here so the ScanTrace stays greppable and the \u00a72.4
*"LLM output JSON schema guardrailed"* invariant holds in one place.
"""

from __future__ import annotations

import enum
import typing

import pydantic


# ---------------------------------------------------------------------------
# KB-side primitives (mirror the Haskell `Location` record from
# dhscanner.packages/dhscanner.kbapi/src/Content.hs so queryengine replies
# round-trip into our models without hand-written adapters).
# ---------------------------------------------------------------------------


class Location(pydantic.BaseModel):
    """A source-code location, as emitted by the queryengine.

    Field names mirror the Haskell record exactly so a Content.hs
    JSON payload parses with ``Location.model_validate(d)``.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    filename: str
    lineStart: int
    lineEnd: int
    colStart: int
    colEnd: int


# ---------------------------------------------------------------------------
# Endpoint identity + queue items (\u00a72.2 initial seed, \u00a72.4 enqueue schema).
# ---------------------------------------------------------------------------


class EndpointBucket(str, enum.Enum):
    """Three-way endpoint taxonomy (\u00a74.8 of ``OWASP26_NOTES.md``)."""

    PRE_AUTH = "pre_auth"
    AUTHENTICATED = "authenticated"
    CAPABILITY_VERIFIED = "capability_verified"


class EndpointRef(pydantic.BaseModel):
    """Stable, serializable reference to one endpoint.

    ``endpoint_id`` (a derived property, not a stored field) is the
    key used by :class:`FindingsStore`; two refs with the same method,
    url, and handler location are the same endpoint even if the
    bucket label changes mid-scan (e.g. recognizer widening lifts an
    endpoint from pre-auth to authenticated between runs).
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    method: typing.Literal["GET", "POST", "PUT"]
    url: str
    handler_location: Location
    bucket: EndpointBucket
    # Only populated for bucket B. We keep it a free-form dict here so
    # the Haskell-side `AuthEvidence` tagged union (ByHeaderNullCheck /
    # ByAllButOneBadReturn / future constructors) round-trips without
    # us having to re-declare each constructor Python-side.
    auth_func_name: typing.Optional[str] = None
    auth_evidence: typing.Optional[dict[str, typing.Any]] = None

    @property
    def endpoint_id(self) -> str:
        loc = self.handler_location
        return f"{self.method} {self.url} @ {loc.filename}:{loc.lineStart}"


# ---------------------------------------------------------------------------
# LLM output schema (\u00a72.4, locked). The outer loop refuses to act on any
# model reply that does not validate against ``LlmResponse``.
# ---------------------------------------------------------------------------


class Verdict(str, enum.Enum):
    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    DEFER = "defer"
    INCONCLUSIVE = "inconclusive"


class Hint(str, enum.Enum):
    FRONT = "front"
    BACK = "back"


class Provenance(pydantic.BaseModel):
    """Pair-edge provenance (\u00a74.7).

    When H1's session discovers an in-codebase callback H2, this
    is written onto *H2's* findings history, not H1's.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    parent: str  # endpoint_id of H1
    mechanism: str  # free-form, e.g. "url_signing", "oauth_state", "jwt_capability"


class EnqueueProposal(pydantic.BaseModel):
    """One pair-edge enqueue request from the LLM.

    ``hint`` is advisory; the outer loop reifies it deterministically
    into push_front / push_back (\u00a72.1). The LLM never writes the
    queue directly.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    item: EndpointRef
    hint: Hint = Hint.BACK
    provenance: typing.Optional[Provenance] = None
    cause: str


class LlmResponse(pydantic.BaseModel):
    """The one and only shape of an LLM reply the outer loop accepts.

    Guardrailed by provider structured-output mode on the way in; if
    the model emits anything else, the outer loop treats the item
    as ``inconclusive`` and re-enqueues it at the back (\u00a72.4).
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    verdict: Verdict
    reason_for_verdict: str
    enqueue: list[EnqueueProposal] = pydantic.Field(default_factory=list)


# ---------------------------------------------------------------------------
# Findings-store records (\u00a74.6). Append-only. The history is a
# discriminated union of two record kinds:
#
# * ``session``             \u2014 one entry per fresh LLM session on this
#                              endpoint (verdict + reason + kbapi I/O).
# * ``provenance_arrival``  \u2014 one entry whenever another endpoint's
#                              session enqueued THIS endpoint as a
#                              pair-edge target (\u00a74.7: provenance
#                              lives on the child).
#
# Both kinds are first-class history entries so the next fresh session
# on this endpoint sees a complete picture of \"what happened to me
# before and why I'm on the queue in the first place\" without any
# out-of-band bookkeeping.
# ---------------------------------------------------------------------------


class SessionRecord(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="ignore")

    kind: typing.Literal["session"] = "session"
    session_id: int
    popped_at: str  # ISO-8601
    verdict: Verdict
    reason_for_verdict: str
    kb_queries: list[dict[str, typing.Any]] = pydantic.Field(default_factory=list)
    kb_responses: list[dict[str, typing.Any]] = pydantic.Field(default_factory=list)
    enqueued_out: list[EnqueueProposal] = pydantic.Field(default_factory=list)
    # Soft cost bookkeeping; useful post-mortem.
    kb_query_budget_used: int = 0
    wall_clock_seconds: float = 0.0
    # True iff this record is a synthetic ``inconclusive`` the outer
    # loop forced because the per-session budget fired (\u00a72.4).
    forced_inconclusive: bool = False


class ProvenanceArrival(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="ignore")

    kind: typing.Literal["provenance_arrival"] = "provenance_arrival"
    recorded_at: str  # ISO-8601
    provenance: Provenance
    # The sessionid of the H1 that announced this pair-edge, so the
    # next fresh session on H2 can cross-reference the parent's
    # record in the ScanTrace if it wants more context.
    announced_by_session: int
    # The lane the outer loop pushed this item onto. ``front`` is the
    # default per \u00a74.7 (urgent-lane bucket-C discovery).
    hint_used: Hint
    cause: str


HistoryEntry = typing.Annotated[
    typing.Union[SessionRecord, ProvenanceArrival],
    pydantic.Field(discriminator="kind"),
]


# Kept as an alias so the old spelling imports keep working during the
# transition. New callers should prefer :class:`SessionRecord`.
FindingsRecord = SessionRecord


# ---------------------------------------------------------------------------
# ScanDigest counts snapshot (\u00a73.2, SHIPPED).
# ---------------------------------------------------------------------------


class ScanDigestSnapshot(pydantic.BaseModel):
    """A frozen moment-in-time view of the digest.

    The outer loop injects one of these into every fresh LLM session
    (\u00a73.3: *"LLM sees a frozen snapshot per item"*) and persists
    one next to every ScanTrace event (\u00a74.1 point 2 \u2014 O(1)
    inspection vs. O(N) replay).
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    items_processed: int = 0
    sinks_seen: int = 0
    sink_family_distribution: dict[str, int] = pydantic.Field(default_factory=dict)
    auth_pattern_distribution: dict[str, int] = pydantic.Field(default_factory=dict)
    response_status_vocabulary: dict[str, int] = pydantic.Field(default_factory=dict)
    framework_fingerprint: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    verdict_distribution_last_20: list[Verdict] = pydantic.Field(default_factory=list)
