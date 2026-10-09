"""ScanDigest counts layer (\u00a73.2, SHIPPED).

This is the outer-loop-owned, outer-loop-updated *learned prior over
this specific codebase*. Only the counts layer ships for the 2026
talk; the notes layer is retained in doc form as future work (\u00a73.9).

Discipline (\u00a73.3, locked):

* Outer loop mutates deterministically after each item completes.
  Aggregation is a *pure function* of (previous digest, KB responses
  this item, LLM verdict this item).
* LLM never writes the digest. It *reads* a frozen snapshot per
  item (\u00a73.3 last paragraph) and may narrate the counts in its
  :pyattr:`LlmResponse.reason_for_verdict`, but it cannot mutate.
* Snapshots are what the trace persists per item (\u00a74.1 point 4).
"""

from __future__ import annotations

import collections
import typing

from agent.loop.types import (
    EndpointBucket,
    EndpointRef,
    LlmResponse,
    ScanDigestSnapshot,
    Verdict,
)


# Length of the rolling verdict tail that lives in each snapshot. The
# full list is in the ScanTrace already; this is just the recency hint
# the LLM gets to see.
_VERDICT_TAIL: typing.Final[int] = 20


class ScanDigest:
    """The outer loop's mutable digest state.

    Keep this class dumb: it only knows how to count. Any downstream
    anomaly-prioritization or query-widening logic (\u00a73.5, \u00a73.7)
    is a separate module that *reads* snapshots.
    """

    def __init__(self) -> None:
        self._items_processed: int = 0
        self._sinks_seen: int = 0
        self._sink_family: collections.Counter[str] = collections.Counter()
        self._auth_pattern: collections.Counter[str] = collections.Counter()
        self._response_status: collections.Counter[str] = collections.Counter()
        self._framework: dict[str, typing.Any] = {}
        self._verdict_tail: collections.deque[Verdict] = collections.deque(
            maxlen=_VERDICT_TAIL,
        )

    # ---- update hooks ---------------------------------------------------

    def bootstrap_from_seed(self, seeded_endpoints: list[EndpointRef]) -> None:
        """Cold-start bootstrap from the initial-queue surface (\u00a73.4).

        Not a full KB structural fingerprint yet \u2014 that would need
        the queryengine to grow a dedicated digest-primer predicate.
        For now we at least seed the auth-pattern distribution from
        the bucket labels we already have, so item #1's LLM has a
        non-empty prior.
        """
        for ref in seeded_endpoints:
            if ref.bucket is EndpointBucket.AUTHENTICATED:
                # The auth_func_name on the ref is what the kbgen-side
                # recognizer bound (e.g. 'authenticateRequest',
                # 'checkAuth') \u2014 that is literally the auth-pattern
                # fingerprint for this codebase.
                key = ref.auth_func_name or "authenticated_unknown"
                self._auth_pattern[key] += 1
            elif ref.bucket is EndpointBucket.PRE_AUTH:
                self._auth_pattern["unauth"] += 1

    def record_item(
        self,
        response: LlmResponse,
        kb_responses: typing.Iterable[dict[str, typing.Any]],
    ) -> None:
        """Fold one completed session into the digest.

        ``kb_responses`` is the raw list of queryengine replies the
        LLM pulled during its session; we scan it for the structural
        signals the counts layer tracks today.
        """
        self._items_processed += 1
        self._verdict_tail.append(response.verdict)
        for kb_reply in kb_responses:
            self._fold_kb_reply(kb_reply)

    # ---- read-only snapshot ---------------------------------------------

    def snapshot(self) -> ScanDigestSnapshot:
        return ScanDigestSnapshot(
            items_processed=self._items_processed,
            sinks_seen=self._sinks_seen,
            sink_family_distribution=dict(self._sink_family),
            auth_pattern_distribution=dict(self._auth_pattern),
            response_status_vocabulary=dict(self._response_status),
            framework_fingerprint=dict(self._framework),
            verdict_distribution_last_20=list(self._verdict_tail),
        )

    # ---- internals ------------------------------------------------------

    def _fold_kb_reply(self, kb_reply: dict[str, typing.Any]) -> None:
        """Fold one queryengine reply into the counters.

        Deliberately defensive \u2014 the kbapi tags evolve independently
        of this driver, so we treat unknown tags as a silent miss
        rather than raising. The ScanTrace keeps the raw reply either
        way, so nothing is lost.
        """
        tag = kb_reply.get("tag")
        contents = kb_reply.get("contents") or {}
        if tag == "FoundControlFlowReachableSqlSink":
            # Shape per Content.hs \u2014
            # FoundControlFlowReachableSqlSink { total, countsByKind, matches }
            total = contents.get("foundControlFlowReachableSqlSinkTotal", 0)
            if isinstance(total, int):
                self._sinks_seen += total
            for kc in contents.get("foundControlFlowReachableSqlSinkCountsByKind") or []:
                kind = (kc.get("sqlSinkKindCountKind") or "").strip() or "unknown"
                cnt = kc.get("sqlSinkKindCountCount", 0)
                if isinstance(cnt, int):
                    self._sink_family[f"sql.{kind}"] += cnt
        elif tag == "FoundControlFlowReachableFileActionSink":
            total = contents.get("foundControlFlowReachableFileActionSinkTotal", 0)
            if isinstance(total, int):
                self._sinks_seen += total
            for kc in contents.get("foundControlFlowReachableFileActionSinkCountsByKind") or []:
                kind = (kc.get("fileActionKindCountKind") or "").strip() or "unknown"
                cnt = kc.get("fileActionKindCountCount", 0)
                if isinstance(cnt, int):
                    self._sink_family[f"file_action.{kind}"] += cnt
        # Future tags fold here as leaf-adds, same pattern. Unknown
        # tags intentionally do nothing \u2014 ScanTrace still has them.
