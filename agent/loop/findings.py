"""Per-endpoint append-only findings history (\u00a74.6).

The findings store is the *in-memory* data structure the outer loop
consults when bundling a popped item's context for the fresh LLM
session. The ScanTrace is the on-disk persistence of everything the
findings store ever held, plus the KB queries + responses that
produced each entry \u2014 the two are coupled but distinct.

Discipline (\u00a74.6, locked):

* Outer loop reads + writes. LLM never touches this directly.
* Appends per session. Never overwrites. If an endpoint is explored
  three times, that's three records \u2014 not one mutated record.
* Keyed by :pyattr:`EndpointRef.endpoint_id` so re-exploration of
  the same endpoint under a different bucket label still hits the
  same history.
"""

from __future__ import annotations

import collections
import typing

from agent.loop.types import (
    EndpointRef,
    HistoryEntry,
    ProvenanceArrival,
    SessionRecord,
)


class FindingsStore:
    def __init__(self) -> None:
        self._store: dict[str, list[HistoryEntry]] = collections.defaultdict(list)

    def append_session(self, endpoint: EndpointRef, record: SessionRecord) -> None:
        """Append a new session record. Never overwrites."""
        self._store[endpoint.endpoint_id].append(record)

    def append_provenance(
        self, endpoint: EndpointRef, arrival: ProvenanceArrival,
    ) -> None:
        """Append a pair-edge arrival stub (\u00a74.7).

        Called when some other endpoint's session enqueued THIS
        endpoint as an H2 pair-edge target. The next fresh session
        on this endpoint will see the arrival in its history
        bundle and can reason about the pair.
        """
        self._store[endpoint.endpoint_id].append(arrival)

    def get(self, endpoint: EndpointRef) -> list[HistoryEntry]:
        """Return the (possibly empty) history for one endpoint.

        The returned list is the live internal buffer \u2014 by convention,
        callers must not mutate it. We don't deep-copy for cost
        reasons (histories can be large on re-explored bucket-C H2s);
        the append-only discipline keeps the aliasing safe in practice.
        """
        return self._store.get(endpoint.endpoint_id, [])

    def __contains__(self, endpoint: EndpointRef) -> bool:
        return endpoint.endpoint_id in self._store

    def all_items(self) -> typing.Iterator[tuple[str, list[HistoryEntry]]]:
        """For post-mortem dumps (e.g. end-of-scan trace tail)."""
        yield from self._store.items()
