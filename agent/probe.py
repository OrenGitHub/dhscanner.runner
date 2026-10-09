"""One-shot probe: drive ONE fresh agent-loop session on ONE endpoint.

Dev tool. Does NOT touch `agent/loop/` production code. We re-use
every real piece of the loop (seeder, kbapi client, findings store,
digest, trace, session) but swap out the seed set for a single
hand-filtered endpoint so we can watch exactly what the LLM chooses
to do on its first encounter with ONE specific HTTP handler (e.g.
the OWASP-IL running example `PUT apps/web/modules/ee/contacts/
api/v2/management/contacts/bulk`).

Usage ( from the repo root, with the compose stack already up ):

    python -m agent.probe
    python -m agent.probe --kb kb_XXXXXXXX1-2 \
        --url-endswith v2/management/contacts/bulk \
        --method PUT
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import typing

# Make the repo root importable so `agent.loop.*` resolves without
# needing a `pip install -e .`.
_HERE = pathlib.Path(__file__).resolve().parent  # .../repo/agent
_REPO_ROOT = _HERE.parent                        # .../repo
sys.path.insert(0, str(_REPO_ROOT))

# .env (OPENAI_API_KEY, OPENAI_MODEL) must be loaded BEFORE agent.loop.session
# reads os.environ in run_item_session.
try:
    from dotenv import load_dotenv  # type: ignore
    # override=True: the repo .env is the canonical key source during
    # dev; a stale shell export must NOT win. The real CLI
    # (`python -m agent.loop`) keeps the production default
    # (override=False) so prod exports still win there.
    load_dotenv(dotenv_path=_REPO_ROOT / ".env", override=True)
except ImportError:
    pass

# pylint: disable=wrong-import-position
from agent.loop.digest import ScanDigest
from agent.loop.findings import FindingsStore
from agent.loop.kbapi import KbapiClient
from agent.loop.queue import TwoLaneDeque
from agent.loop.seeder import seed_initial_queue
from agent.loop.session import (
    DEFAULT_ENQUEUE_BUDGET,
    DEFAULT_KBAPI_QUERY_BUDGET,
    DEFAULT_OPENAI_TIMEOUT_SECONDS,
    DEFAULT_WALL_CLOCK_SECONDS,
    openai_api_key_present,
    run_item_session,
)
from agent.loop.trace import ScanTrace, default_trace_root
from agent.loop.types import EndpointRef


_DEFAULT_URL_SUFFIX = "modules/ee/contacts/api/v2/management/contacts/bulk"
_BAR = "=" * 72


def _parse_args(argv: typing.Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="agent.probe",
        description=(
            "Drive ONE fresh agent-loop session on ONE handpicked endpoint. "
            "Everything you'd see in a full `python -m agent.loop` run, "
            "except we filter the A\u222aB seed down to a single URL first."
        ),
    )
    p.add_argument("--kb", default="kb_XXXXXXXX1-2",
                   help="kb filename on the queryengine (default: kb_XXXXXXXX1-2)")
    p.add_argument("--kbapi-url", default="http://localhost:3000/api",
                   help="queryengine endpoint (default: http://localhost:3000/api)")
    p.add_argument("--method", default="PUT", choices=("GET", "POST", "PUT"),
                   help="HTTP method of the target endpoint (default: PUT)")
    p.add_argument("--url-endswith", default=_DEFAULT_URL_SUFFIX,
                   help=f"keep the one endpoint whose URL ends with this (default: {_DEFAULT_URL_SUFFIX!r})")
    p.add_argument("--model", default=None,
                   help="override OPENAI_MODEL / default gpt-5")
    p.add_argument("--kbapi-query-budget", type=int, default=DEFAULT_KBAPI_QUERY_BUDGET,
                   help=f"max kbapi calls per session (default: {DEFAULT_KBAPI_QUERY_BUDGET})")
    p.add_argument("--enqueue-budget", type=int, default=DEFAULT_ENQUEUE_BUDGET,
                   help=f"max pair-edge enqueues (default: {DEFAULT_ENQUEUE_BUDGET})")
    p.add_argument("--wall-clock-s", type=float, default=DEFAULT_WALL_CLOCK_SECONDS,
                   help=f"per-session wall-clock bound (default: {DEFAULT_WALL_CLOCK_SECONDS:.0f})")
    p.add_argument("--openai-timeout-s", type=float, default=DEFAULT_OPENAI_TIMEOUT_SECONDS,
                   help=f"per-openai-call timeout (default: {DEFAULT_OPENAI_TIMEOUT_SECONDS:.0f})")
    return p.parse_args(argv)


def _find_target(kbapi: KbapiClient, method: str, url_endswith: str) -> EndpointRef:
    print(f"[probe] firing seeder against kb={kbapi.kb_location} ...")
    seeded = seed_initial_queue(kbapi)
    print(f"[probe] seeder returned {len(seeded)} endpoints (A \u222a B)")
    # The queryengine wraps URL atoms in single quotes (Prolog-style);
    # strip them for user-friendly substring matching.
    def _strip(u: str) -> str:
        return u.strip("'")
    matches = [r for r in seeded if r.method == method and url_endswith in _strip(r.url)]
    if not matches:
        print(f"[probe] no match for method={method} url~={url_endswith!r}", file=sys.stderr)
        print(f"[probe] all {method} URLs discovered by the seeder:", file=sys.stderr)
        for r in seeded:
            if r.method == method:
                print(f"  * {r.method} {_strip(r.url)}  @  "
                      f"{r.handler_location.filename}:{r.handler_location.lineStart}",
                      file=sys.stderr)
        raise SystemExit(2)
    # Multiple matches = exported wrapper + inner HOC lambda both got
    # seeded. The exported wrapper (lower lineStart) is the canonical
    # HTTP entry point; let the LLM discover the inner lambda via
    # the HOC-unwrap edge on its own.
    matches.sort(key=lambda r: r.handler_location.lineStart)
    if len(matches) > 1:
        print(f"[probe] {len(matches)} candidates for this URL; picking lowest lineStart:",
              file=sys.stderr)
        for r in matches:
            marker = "<-" if r is matches[0] else "  "
            print(f"  {marker} {r.handler_location.filename}:{r.handler_location.lineStart} "
                  f"(bucket={r.bucket.value})", file=sys.stderr)
    return matches[0]


def _print_endpoint(ref: EndpointRef) -> None:
    print(_BAR)
    print("[probe] target endpoint on the desk:")
    print(_BAR)
    print(json.dumps(ref.model_dump(mode="json"), indent=2))
    print()


def _print_session_summary(session_result, trace_root: pathlib.Path) -> None:
    print(_BAR)
    print(f"[probe] session complete  (wall={session_result.wall_clock_seconds:.2f}s, "
          f"kbapi_budget_used={session_result.kb_query_budget_used}, "
          f"forced_inconclusive={session_result.forced_inconclusive})")
    print(_BAR)

    print(f"\n--- what the LLM queried ({len(session_result.kb_queries)} calls) ---")
    for i, (q, r) in enumerate(zip(session_result.kb_queries, session_result.kb_responses), 1):
        print(f"\n  call #{i}: tag={q.get('tag')!r}")
        print("    contents =", json.dumps(q.get("contents"), indent=2).replace("\n", "\n    "))
        reply_tag = r.get("tag")
        contents = r.get("contents")
        if isinstance(contents, dict):
            summary_keys = ", ".join(sorted(contents.keys()))
            print(f"    reply tag = {reply_tag!r}; fields = [{summary_keys}]")
        else:
            print(f"    reply tag = {reply_tag!r}; contents = {contents!r}")

    print("\n--- final verdict ---")
    print(f"  verdict   : {session_result.response.verdict.value}")
    print(f"  reason    : {session_result.response.reason_for_verdict}")
    print(f"  enqueue   : {len(session_result.response.enqueue)} proposals")
    for i, prop in enumerate(session_result.response.enqueue, 1):
        print(f"    [{i}] hint={prop.hint.value}  cause={prop.cause!r}")
        print(f"        target  : {prop.item.endpoint_id}")
        if prop.provenance is not None:
            print(f"        prov    : parent={prop.provenance.parent!r} "
                  f"mechanism={prop.provenance.mechanism!r}")

    print("\n--- trace on disk ---")
    print(f"  {trace_root}")
    print("  trace.jsonl, digest_snapshots/item_0001.json")


def main(argv: typing.Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    if not openai_api_key_present():
        print("error: OPENAI_API_KEY not set; export it or add it to .env", file=sys.stderr)
        return 2

    kbapi = KbapiClient(args.kb, url=args.kbapi_url)
    target = _find_target(kbapi, args.method, args.url_endswith)
    _print_endpoint(target)

    # Minimal replica of run_scan's wiring, but with:
    #   - a 1-element queue (not seed_initial_queue()),
    #   - a hard max_items=1 cap,
    #   - identical trace / digest / findings plumbing so the artefacts
    #     match what a real `python -m agent.loop` run would produce.
    queue = TwoLaneDeque()
    queue.push_back(target)
    findings = FindingsStore()
    digest = ScanDigest()
    digest.bootstrap_from_seed([target])

    trace_root = default_trace_root(args.kb)
    trace = ScanTrace(root=trace_root, kb_location=args.kb,
                      kb_pointer={"kb_location": args.kb})

    try:
        trace.scan_started()
        trace.queue_seeded(queue.snapshot_ids())
        print(f"[probe] trace root: {trace_root}")
        print(f"[probe] running fresh LLM session (model={args.model or 'env/default'}, "
              f"kbapi_budget={args.kbapi_query_budget}) ...\n")

        endpoint = queue.pop_front()
        assert endpoint is not None  # we just pushed one
        item_id = 1
        trace.item_popped(item_id, endpoint)
        snapshot = digest.snapshot()
        trace.digest_snapshot(item_id, snapshot)

        session_kwargs: dict[str, typing.Any] = {
            "endpoint": endpoint,
            "history": findings.get(endpoint),
            "digest_snapshot": snapshot,
            "kbapi_client": kbapi,
            "kbapi_query_budget": args.kbapi_query_budget,
            "enqueue_budget": args.enqueue_budget,
            "wall_clock_seconds": args.wall_clock_s,
            "openai_timeout_seconds": args.openai_timeout_s,
            "trace_hook": _LiveHook(trace, item_id),
        }
        if args.model is not None:
            session_kwargs["model"] = args.model

        session_result = run_item_session(**session_kwargs)
        trace.llm_verdict(item_id, session_result.response)
        trace.scan_completed(items_processed=1, queue_remaining=len(queue))

        _print_session_summary(session_result, trace_root)
        return 0
    finally:
        trace.close()


class _LiveHook:
    """Trace hook that ALSO echoes to stdout so the user sees the LLM's
    tool calls as they happen (instead of only post-mortem)."""

    def __init__(self, trace: ScanTrace, item_id: int) -> None:
        self._trace = trace
        self._item_id = item_id

    def kbapi_call(self, call_index: int, query: dict[str, typing.Any]) -> None:
        self._trace.kbapi_call(self._item_id, call_index, query)
        print(f"  [kbapi #{call_index}] -> tag={query.get('tag')!r}")

    def kbapi_reply(self, call_index: int, reply: dict[str, typing.Any]) -> None:
        self._trace.kbapi_reply(self._item_id, call_index, reply)
        print(f"  [kbapi #{call_index}] <- tag={reply.get('tag')!r}")


if __name__ == "__main__":
    raise SystemExit(main())
