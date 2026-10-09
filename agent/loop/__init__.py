"""Deterministic LLM<->KB outer loop for dhscanner.

This package is the Python driver referenced in
``docs/OWASP_NOTES_FINALIZED.md`` \u00a711 (SHIPPED matrix) as
*"\U0001f40d talk-only Python driver script"*. It implements the
three-actor runtime (KB / outer loop / LLM) with fresh-session-per-item
discipline, a two-lane BFS work queue, per-endpoint append-only
findings history, a counts-layer ScanDigest, and a JSONL ScanTrace.

Each submodule maps 1:1 to a doc section so grep-ability survives:

* :mod:`agent.loop.types`     \u2014 Pydantic I/O schema (\u00a72.4 LLM-output + queue/findings/digest records)
* :mod:`agent.loop.queue`     \u2014 TwoLaneDeque (\u00a72.1)
* :mod:`agent.loop.findings`  \u2014 FindingsStore (\u00a74.6)
* :mod:`agent.loop.digest`    \u2014 ScanDigestCounts (\u00a73.2 + \u00a73.3 update discipline)
* :mod:`agent.loop.trace`     \u2014 ScanTrace JSONL writer (\u00a74)
* :mod:`agent.loop.kbapi`     \u2014 thin HTTP client against the queryengine
* :mod:`agent.loop.seeder`    \u2014 initial queue = A \u222a B (\u00a72.2)
* :mod:`agent.loop.session`   \u2014 fresh LLM session (\u00a72.3 + \u00a72.4 budgets)
* :mod:`agent.loop.loop`      \u2014 the deterministic outer loop (\u00a74.6 ritual)
"""

from __future__ import annotations

from agent.loop.loop import run_scan

__all__ = ["run_scan"]
