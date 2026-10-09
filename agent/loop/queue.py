"""Two-lane BFS work queue (\u00a72.1).

Priority-hinted deque: ``push_front`` (urgent) / ``push_back`` (default) /
``pop_front``. O(1) each. No fine-grained priority, no re-scoring, no
shuffling \u2014 the LLM emits a lane hint per enqueue and the outer loop
reifies it deterministically here.

The LLM never sees this structure (\u00a72.3). Only the outer loop reads
and writes it.
"""

from __future__ import annotations

import collections
import typing

from agent.loop.types import EndpointRef, Hint


class TwoLaneDeque:
    """collections.deque-backed, with a tiny vocabulary.

    Not thread-safe; the outer loop is single-worker by design. If we
    ever enable the \"parallel workers pulling from one queue\" story
    from \u00a71 point 6, wrap this in a mutex at that point.
    """

    def __init__(self, initial: typing.Iterable[EndpointRef] = ()) -> None:
        self._deque: collections.deque[EndpointRef] = collections.deque(initial)
        # Monotonically growing. Snapshotted into the trace at seed
        # time so \"% explored\" is a defined concept per \u00a72.2.
        self._initial_size: int = len(self._deque)
        # Total pops ever \u2014 handy for the \"items processed\" counter
        # on the ScanDigest.
        self._pops: int = 0
        # Idempotency guard. Pair-edge discoveries can fire multiple
        # times across sessions; we don't want the same H2 enqueued
        # five times just because five H1s each named it. Keyed on
        # ``EndpointRef.endpoint_id``.
        self._ever_enqueued: set[str] = set()
        for ref in self._deque:
            self._ever_enqueued.add(ref.endpoint_id)

    # ---- read-only inspection -------------------------------------------

    def __len__(self) -> int:
        return len(self._deque)

    @property
    def initial_size(self) -> int:
        return self._initial_size

    @property
    def pops(self) -> int:
        return self._pops

    def snapshot_ids(self) -> list[str]:
        """Non-destructive id-only view, cheap to persist into the trace."""
        return [ref.endpoint_id for ref in self._deque]

    def already_known(self, ref: EndpointRef) -> bool:
        return ref.endpoint_id in self._ever_enqueued

    # ---- the three ops --------------------------------------------------

    def push_front(self, ref: EndpointRef) -> bool:
        """Urgent lane. Returns True if actually enqueued (new id)."""
        if ref.endpoint_id in self._ever_enqueued:
            return False
        self._deque.appendleft(ref)
        self._ever_enqueued.add(ref.endpoint_id)
        return True

    def push_back(self, ref: EndpointRef) -> bool:
        """Default lane. Returns True if actually enqueued (new id)."""
        if ref.endpoint_id in self._ever_enqueued:
            return False
        self._deque.append(ref)
        self._ever_enqueued.add(ref.endpoint_id)
        return True

    def push(self, ref: EndpointRef, hint: Hint) -> bool:
        """Dispatch on an LLM-emitted hint (\u00a72.4 schema)."""
        if hint is Hint.FRONT:
            return self.push_front(ref)
        return self.push_back(ref)

    def requeue_back(self, ref: EndpointRef) -> None:
        """Re-enqueue an item that was already popped (\u00a72.4
        inconclusive-retry path).

        Distinct from :meth:`push_back` because dedup against
        ``_ever_enqueued`` is a correctness invariant for pair-edge
        discovery (don't let five H1s each announce the same H2
        five times) \u2014 pop-and-retry is a different operation on
        the *same* item and must be allowed to re-add it.
        """
        self._deque.append(ref)

    def pop_front(self) -> typing.Optional[EndpointRef]:
        if not self._deque:
            return None
        self._pops += 1
        return self._deque.popleft()
