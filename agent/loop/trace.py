"""ScanTrace writer (\u00a74).

The on-disk evidence chain *per scan*. One JSONL file + optional
sidecar snapshot files, laid out under::

    agent/.scan_traces/<kb-basename>/<timestamp>/
        trace.jsonl
        digest_snapshots/item_<nnn>.json

Design (\u00a74.1):

* JSONL = one event per line, streamable + greppable.
* Digest snapshots live in sidecar files because they're O(1)-lookup
  payloads an auditor wants to open directly without replaying the
  trace to the right point.
* The writer flushes aggressively (per event). The trace survives a
  crash mid-scan.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import pathlib
import time
import typing

from agent.loop.types import (
    EndpointRef,
    EnqueueProposal,
    LlmResponse,
    ScanDigestSnapshot,
    SessionRecord,
)


# ---------------------------------------------------------------------------
# Event names \u2014 one place for the discriminator strings so grepping the
# trace is a stable interface.
# ---------------------------------------------------------------------------


class Event(str):
    SCAN_STARTED = "scan_started"
    QUEUE_SEEDED = "queue_seeded"
    ITEM_POPPED = "item_popped"
    KBAPI_CALL = "kbapi_call"
    KBAPI_REPLY = "kbapi_reply"
    LLM_VERDICT = "llm_verdict"
    ENQUEUE = "enqueue"
    DIGEST_SNAPSHOT = "digest_snapshot"
    ITEM_COMPLETED = "item_completed"
    SCAN_COMPLETED = "scan_completed"


@dataclasses.dataclass
class ScanTrace:
    """Append-only JSONL writer. One instance per scan."""

    root: pathlib.Path
    kb_location: str
    kb_pointer: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    _fh: typing.TextIO = dataclasses.field(init=False, repr=False)
    _digest_dir: pathlib.Path = dataclasses.field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._digest_dir = self.root / "digest_snapshots"
        self._digest_dir.mkdir(parents=True, exist_ok=True)
        self._fh = (self.root / "trace.jsonl").open("w", encoding="utf-8")

    # ---- primitives ------------------------------------------------------

    def _emit(self, event: str, **payload: typing.Any) -> None:
        line = {
            "event": event,
            "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            **payload,
        }
        self._fh.write(json.dumps(line, default=_json_default))
        self._fh.write("\n")
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        except OSError:
            pass

    # ---- the four layers of \u00a74 ----------------------------------------

    def scan_started(self) -> None:
        self._emit(
            Event.SCAN_STARTED,
            kb_location=self.kb_location,
            kb_pointer=self.kb_pointer,
        )

    def queue_seeded(self, initial_ids: list[str]) -> None:
        self._emit(Event.QUEUE_SEEDED, initial_size=len(initial_ids), items=initial_ids)

    def item_popped(self, item_id: int, endpoint: EndpointRef) -> None:
        self._emit(Event.ITEM_POPPED, item=item_id, endpoint=endpoint.model_dump())

    def kbapi_call(self, item_id: int, call_index: int, query: dict[str, typing.Any]) -> None:
        self._emit(Event.KBAPI_CALL, item=item_id, call=call_index, query=query)

    def kbapi_reply(self, item_id: int, call_index: int, reply: dict[str, typing.Any]) -> None:
        self._emit(Event.KBAPI_REPLY, item=item_id, call=call_index, reply=reply)

    def llm_verdict(self, item_id: int, response: LlmResponse) -> None:
        self._emit(
            Event.LLM_VERDICT,
            item=item_id,
            verdict=response.verdict.value,
            reason_for_verdict=response.reason_for_verdict,
        )

    def enqueue(
        self,
        item_id: int,
        proposal: EnqueueProposal,
        accepted: bool,
    ) -> None:
        self._emit(
            Event.ENQUEUE,
            item=item_id,
            accepted=accepted,
            hint=proposal.hint.value,
            cause=proposal.cause,
            target=proposal.item.endpoint_id,
            provenance=proposal.provenance.model_dump() if proposal.provenance else None,
        )

    def digest_snapshot(self, item_id: int, snapshot: ScanDigestSnapshot) -> None:
        """Persist the digest both inline (so trace replay is possible)
        and as an O(1)-indexable sidecar (\u00a74.1 point 1)."""
        sidecar = self._digest_dir / f"item_{item_id:04d}.json"
        with sidecar.open("w", encoding="utf-8") as fh:
            json.dump(snapshot.model_dump(), fh, default=_json_default, indent=2)
        self._emit(
            Event.DIGEST_SNAPSHOT,
            item=item_id,
            snapshot=snapshot.model_dump(),
            sidecar=str(sidecar.relative_to(self.root)),
        )

    def item_completed(
        self,
        item_id: int,
        endpoint: EndpointRef,
        record: SessionRecord,
    ) -> None:
        self._emit(
            Event.ITEM_COMPLETED,
            item=item_id,
            endpoint_id=endpoint.endpoint_id,
            record=record.model_dump(),
        )

    def scan_completed(self, items_processed: int, queue_remaining: int) -> None:
        self._emit(
            Event.SCAN_COMPLETED,
            items_processed=items_processed,
            queue_remaining=queue_remaining,
        )


def default_trace_root(kb_location: str) -> pathlib.Path:
    """Mirror the layout ``agent/launcher.py`` already uses for its
    own artefacts (``agent/.launch_logs/<basename>/<timestamp>/``).
    Timestamp is UTC + ``monotonic`` suffix for sub-second ordering.
    """
    here = pathlib.Path(__file__).resolve().parent.parent  # .../agent/
    stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    monotonic = int(time.monotonic() * 1000) % 100000
    basename = pathlib.Path(kb_location).stem or "kb"
    return here / ".scan_traces" / basename / f"{stamp}-{monotonic:05d}"


def _json_default(obj: typing.Any) -> typing.Any:
    # Pydantic enums / BaseModels can occasionally slip through if a
    # caller forgets to ``model_dump()``; this keeps the trace writer
    # a last line of defense rather than a crash site.
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "value"):
        return obj.value
    return str(obj)
