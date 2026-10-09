"""The deterministic outer loop (\u00a74.6 ritual).

Main loop body, verbatim from the doc::

    1. endpoint = queue.pop_front()
    2. history  = findings_store.get(endpoint)
    3. bundle (endpoint, history) into slot #3 of the fresh-session seed
    4. fresh LLM session, up to the per-session budget
    5. parse guardrailed {verdict, reason_for_verdict, enqueue: [...]}
    6. APPEND a new record to findings_store[endpoint]  (never overwrite)
    7. reify enqueues; update ScanDigest; append to ScanTrace

The function :func:`run_scan` ties the queue, findings store, digest,
trace, kbapi client, and session together \u2014 and nothing else. All
the policy decisions (seeding, bucketing, pair-edge semantics,
inconclusive handling) live in the per-step helpers below, one
helper per \u00a74.6 bullet so the file reads top-down the same way
the doc does.
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
import pathlib
import time
import typing

from agent.loop.digest import ScanDigest
from agent.loop.findings import FindingsStore
from agent.loop.kbapi import KbapiClient
from agent.loop.queue import TwoLaneDeque
from agent.loop.seeder import seed_initial_queue
from agent.loop.session import (
    DEFAULT_ENQUEUE_BUDGET,
    DEFAULT_KBAPI_QUERY_BUDGET,
    DEFAULT_MODEL,
    DEFAULT_OPENAI_TIMEOUT_SECONDS,
    DEFAULT_WALL_CLOCK_SECONDS,
    SessionResult,
    openai_api_key_present,
    run_item_session,
)
from agent.loop.trace import ScanTrace, default_trace_root
from agent.loop.types import (
    EndpointRef,
    ProvenanceArrival,
    SessionRecord,
    Verdict,
)


_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scan-level knobs. Keep the surface tiny: everything the CLI exposes is
# bundled on :class:`ScanConfig`. Session-level knobs live on
# :mod:`agent.loop.session` so they can be reused by any future caller
# that drives one session at a time (e.g. a REPL for post-mortem replay).
# ---------------------------------------------------------------------------


# pylint: disable=too-many-instance-attributes
@dataclasses.dataclass(frozen=True)
class ScanConfig:
    kb_location: str
    kbapi_url: str = "http://localhost:3000/api"
    model: str = DEFAULT_MODEL
    kbapi_query_budget: int = DEFAULT_KBAPI_QUERY_BUDGET
    enqueue_budget: int = DEFAULT_ENQUEUE_BUDGET
    wall_clock_per_session_s: float = DEFAULT_WALL_CLOCK_SECONDS
    openai_timeout_s: float = DEFAULT_OPENAI_TIMEOUT_SECONDS
    # Hard caps so even a runaway queue cannot burn forever. Set to
    # ``None`` to disable.
    max_items: typing.Optional[int] = None
    max_wall_clock_s: typing.Optional[float] = None
    # Where the ScanTrace lands. ``None`` -> default under
    # ``agent/.scan_traces/<kb-basename>/<timestamp>/``.
    trace_root: typing.Optional[pathlib.Path] = None


@dataclasses.dataclass
class ScanResult:
    """Everything a caller might want to inspect after the loop ends."""

    items_processed: int
    queue_remaining: int
    trace_root: pathlib.Path
    verdict_counts: dict[Verdict, int]


# ---------------------------------------------------------------------------
# The public entry point.
# ---------------------------------------------------------------------------


def run_scan(config: ScanConfig) -> ScanResult:  # pylint: disable=too-many-locals
    """Drive the three-actor runtime end-to-end on one kb snapshot.

    The function is intentionally boring: every meaningful decision
    is isolated in a helper. The body reads as the \u00a74.6 ritual.
    """
    if not openai_api_key_present():
        raise RuntimeError(
            "OPENAI_API_KEY not set in the environment; cannot run fresh LLM "
            "sessions. Export it or load it from a .env file first."
        )

    kbapi = KbapiClient(config.kb_location, url=config.kbapi_url)
    queue = TwoLaneDeque()
    findings = FindingsStore()
    digest = ScanDigest()

    trace_root = config.trace_root or default_trace_root(config.kb_location)
    trace = ScanTrace(
        root=trace_root,
        kb_location=config.kb_location,
        kb_pointer={"kb_location": config.kb_location},
    )

    try:
        trace.scan_started()
        _seed(queue=queue, digest=digest, trace=trace, kbapi=kbapi)
        return _drive(
            queue=queue,
            findings=findings,
            digest=digest,
            trace=trace,
            kbapi=kbapi,
            config=config,
        )
    finally:
        trace.close()


# ---------------------------------------------------------------------------
# Step 0 \u2014 seed the initial queue (\u00a72.2).
# ---------------------------------------------------------------------------


def _seed(
    *,
    queue: TwoLaneDeque,
    digest: ScanDigest,
    trace: ScanTrace,
    kbapi: KbapiClient,
) -> None:
    # ``findings`` is intentionally absent here: seed-time entries live
    # on the queue + digest only; the per-endpoint history is populated
    # by the first fresh session on each endpoint (\u00a74.6 ritual).
    seeded = seed_initial_queue(kbapi)
    for ref in seeded:
        queue.push_back(ref)
    digest.bootstrap_from_seed(seeded)
    trace.queue_seeded(queue.snapshot_ids())
    _log.info("seeded %d endpoints (A \u222a B surface)", len(seeded))


# ---------------------------------------------------------------------------
# Step 1\u20137 \u2014 pop / bundle / fresh session / persist / reify enqueues.
# ---------------------------------------------------------------------------


def _drive(  # pylint: disable=too-many-arguments,too-many-locals,too-many-branches,too-many-positional-arguments
    *,
    queue: TwoLaneDeque,
    findings: FindingsStore,
    digest: ScanDigest,
    trace: ScanTrace,
    kbapi: KbapiClient,
    config: ScanConfig,
) -> ScanResult:
    started = time.monotonic()
    item_id = 0
    verdict_counts: dict[Verdict, int] = {v: 0 for v in Verdict}

    while True:
        if config.max_items is not None and item_id >= config.max_items:
            _log.info("hit --max-items=%d; stopping", config.max_items)
            break
        if (
            config.max_wall_clock_s is not None
            and (time.monotonic() - started) >= config.max_wall_clock_s
        ):
            _log.info(
                "hit --max-wall-clock-s=%.1f; stopping",
                config.max_wall_clock_s,
            )
            break

        endpoint = queue.pop_front()
        if endpoint is None:
            _log.info("queue drained after %d items; stopping", item_id)
            break

        item_id += 1
        trace.item_popped(item_id, endpoint)
        snapshot = digest.snapshot()
        trace.digest_snapshot(item_id, snapshot)

        history = findings.get(endpoint)
        hook = _TraceHook(trace, item_id)
        session_result = run_item_session(
            endpoint=endpoint,
            history=history,
            digest_snapshot=snapshot,
            kbapi_client=kbapi,
            model=config.model,
            kbapi_query_budget=config.kbapi_query_budget,
            enqueue_budget=config.enqueue_budget,
            wall_clock_seconds=config.wall_clock_per_session_s,
            openai_timeout_seconds=config.openai_timeout_s,
            trace_hook=hook,
        )

        trace.llm_verdict(item_id, session_result.response)
        record = _record_from_session(item_id, session_result)
        findings.append_session(endpoint, record)
        verdict_counts[session_result.response.verdict] += 1

        _reify_enqueues(
            queue=queue,
            findings=findings,
            trace=trace,
            item_id=item_id,
            parent=endpoint,
            session_result=session_result,
        )

        digest.record_item(session_result.response, session_result.kb_responses)
        trace.item_completed(item_id, endpoint, record)

        # Forced inconclusive => re-enqueue at the back per \u00a72.4.
        # ``requeue_back`` bypasses the pair-edge dedup set; without it
        # a pop-and-retry would be silently swallowed as a duplicate.
        if session_result.forced_inconclusive:
            queue.requeue_back(endpoint)

    trace.scan_completed(
        items_processed=item_id,
        queue_remaining=len(queue),
    )
    return ScanResult(
        items_processed=item_id,
        queue_remaining=len(queue),
        trace_root=trace.root,
        verdict_counts=verdict_counts,
    )


# ---------------------------------------------------------------------------
# Enqueue reification (\u00a74.7: provenance on H2, not H1; H1 is not
# re-enqueued).
# ---------------------------------------------------------------------------


def _reify_enqueues(  # pylint: disable=too-many-arguments
    *,
    queue: TwoLaneDeque,
    findings: FindingsStore,
    trace: ScanTrace,
    item_id: int,
    parent: EndpointRef,
    session_result: SessionResult,
) -> None:
    """Apply each LlmResponse.enqueue proposal.

    Three outcomes are possible per proposal:

    * **Accepted** \u2014 the H2 is new to the queue. Push on the hinted
      lane; write a :class:`ProvenanceArrival` stub into H2's history
      so H2's eventual fresh session sees where it came from.
    * **Deduplicated** \u2014 the H2 was already queued or already
      processed earlier. Record the arrival (another H1 pointed at
      the same H2, that is itself a signal) but do not re-enqueue.
    * **Rejected** \u2014 the proposal is beyond the per-session enqueue
      budget. Logged in the trace with ``accepted=false``.
    """
    accepted = 0
    for proposal in session_result.response.enqueue:
        if accepted >= _enqueue_budget_for(session_result):
            trace.enqueue(item_id, proposal, accepted=False)
            continue
        child = proposal.item
        # Attach the parent's endpoint id automatically if the LLM
        # didn't bother to carry it explicitly \u2014 the outer loop
        # knows the parent, so we don't force the model to.
        if proposal.provenance is None:
            # No provenance means this isn't actually a pair-edge; we
            # still accept the enqueue so the loop stays general.
            synthesized_provenance = None
        elif not proposal.provenance.parent:
            synthesized_provenance = proposal.provenance.model_copy(
                update={"parent": parent.endpoint_id},
            )
        else:
            synthesized_provenance = proposal.provenance

        was_new = queue.push(child, proposal.hint)
        trace.enqueue(item_id, proposal, accepted=True)
        accepted += 1

        if synthesized_provenance is not None:
            arrival = ProvenanceArrival(
                recorded_at=_now_iso(),
                provenance=synthesized_provenance,
                announced_by_session=item_id,
                hint_used=proposal.hint,
                cause=proposal.cause,
            )
            findings.append_provenance(child, arrival)
            _log.debug(
                "pair-edge: %s -> %s via %s (new=%s)",
                parent.endpoint_id,
                child.endpoint_id,
                synthesized_provenance.mechanism,
                was_new,
            )


def _enqueue_budget_for(_session_result: SessionResult) -> int:
    """Future hook for a dynamic enqueue budget. For now, use the
    static session default; the session-level budget already lives
    on the OpenAI-side system prompt."""
    return DEFAULT_ENQUEUE_BUDGET


# ---------------------------------------------------------------------------
# tiny helpers
# ---------------------------------------------------------------------------


class _TraceHook:
    """Adapter between :mod:`agent.loop.session`'s hook protocol and
    the full :class:`ScanTrace` writer. Keeps the session module
    unaware of the trace's event vocabulary."""

    def __init__(self, trace: ScanTrace, item_id: int) -> None:
        self._trace = trace
        self._item_id = item_id

    def kbapi_call(self, call_index: int, query: dict[str, typing.Any]) -> None:
        self._trace.kbapi_call(self._item_id, call_index, query)

    def kbapi_reply(self, call_index: int, reply: dict[str, typing.Any]) -> None:
        self._trace.kbapi_reply(self._item_id, call_index, reply)


def _record_from_session(item_id: int, result: SessionResult) -> SessionRecord:
    return SessionRecord(
        session_id=item_id,
        popped_at=_now_iso(),
        verdict=result.response.verdict,
        reason_for_verdict=result.response.reason_for_verdict,
        kb_queries=result.kb_queries,
        kb_responses=result.kb_responses,
        enqueued_out=list(result.response.enqueue),
        kb_query_budget_used=result.kb_query_budget_used,
        wall_clock_seconds=result.wall_clock_seconds,
        forced_inconclusive=result.forced_inconclusive,
    )


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
