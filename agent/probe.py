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

Handlers the seeder cannot find ( eg a spring `@RequestMapping` whose
verb or url the KB does not resolve yet ) go straight on the desk by
location instead. The handler's exact span is looked up in a local copy
of the KB ( `--kb-file`, or `docker cp` out of the queryengine container ):

    python -m agent.probe --kb kb_XXXXXXXX1-4 \
        --handler-file OidcRestController.java --handler-line 52 \
        --method GET --url /api/authn/oidc
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import tempfile
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
from agent.loop.types import EndpointBucket, EndpointRef, Location


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
    p.add_argument("--method", default=None, choices=("GET", "POST", "PUT"),
                   help="HTTP method of the target endpoint (default: PUT, or GET with --handler-file)")
    p.add_argument("--url-endswith", default=_DEFAULT_URL_SUFFIX,
                   help=f"keep the one endpoint whose URL ends with this (default: {_DEFAULT_URL_SUFFIX!r})")
    p.add_argument("--handler-file", default=None,
                   help="bypass the seeder: put the handler defined in the file ending with this on the desk")
    p.add_argument("--handler-line", type=int, default=None,
                   help="line where the --handler-file handler starts (its first annotation, if any)")
    p.add_argument("--url", default="{?}",
                   help="url label for a --handler-file endpoint (default: '{?}')")
    p.add_argument("--bucket", default=EndpointBucket.PRE_AUTH.value,
                   choices=[b.value for b in EndpointBucket],
                   help="bucket label for a --handler-file endpoint (default: pre_auth)")
    p.add_argument("--kb-file", default=None,
                   help="local copy of the KB used to resolve --handler-file "
                        "(default: docker cp it out of --queryengine-container)")
    p.add_argument("--queryengine-container", default="compose-queryengine-1",
                   help="container holding /tmp/<kb>.pl (default: compose-queryengine-1)")
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
    args = p.parse_args(argv)
    if (args.handler_file is None) != (args.handler_line is None):
        p.error("--handler-file and --handler-line go together")
    if args.method is None:
        args.method = "PUT" if args.handler_file is None else "GET"
    return args


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


# Callable locations as they appear in KB facts. A kbgen location atom is
# `startloc_<line>_<col>_endloc_<line>_<col>_<normalized filename>`.
_CALLABLE_ATOM_PATTERNS: typing.Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"^kb_called_from\( \S+, (startloc_\S+) \)\."),
    re.compile(r"^kb_param_i_of_callable\( \S+, \d+, (startloc_\S+) \)\."),
    re.compile(r"^kb_method_of_class\( (startloc_\S+), "),
    re.compile(r"^kb_func_def\( (startloc_\S+), "),
    re.compile(r"^kb_callable_has_annotation\( (startloc_\S+), "),
)
_LOCATION_ATOM = re.compile(r"^startloc_(\d+)_(\d+)_endloc_(\d+)_(\d+)_(.+)$")
# Inverse of kbgen's filename normalization ( `Kbgen.restoreloc` ).
_FILENAME_RULES: typing.Final[tuple[tuple[str, str], ...]] = (
    ("_slash_", "/"), ("_dot_", "."), ("_dash_", "-"),
    ("_lbrack_", "["), ("_rbrack_", "]"), ("_lparen_", "("), ("_rparen_", ")"),
)


def _restore_location(atom: str) -> typing.Optional[Location]:
    m = _LOCATION_ATOM.match(atom)
    if m is None:
        return None
    filename = m.group(5)
    for normalized, original in _FILENAME_RULES:
        filename = filename.replace(normalized, original)
    return Location(
        filename=filename,
        lineStart=int(m.group(1)), colStart=int(m.group(2)),
        lineEnd=int(m.group(3)), colEnd=int(m.group(4)),
    )


def _read_kb(kb: str, kb_file: typing.Optional[str], container: str) -> str:
    if kb_file is not None:
        return pathlib.Path(kb_file).read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        local = pathlib.Path(tmp) / f"{kb}.pl"
        print(f"[probe] copying {container}:/tmp/{kb}.pl to resolve the handler ...")
        subprocess.run(["docker", "cp", f"{container}:/tmp/{kb}.pl", str(local)], check=True)
        return local.read_text(encoding="utf-8")


def _resolve_handler(kb_text: str, file_suffix: str, line: int) -> Location:
    """The callable starting at ``line`` of the file ending with ``file_suffix``.

    Nested callables can share a start line ( eg a lambda on the
    method's first line ), so the widest span wins.
    """
    callables: set[tuple[str, int, int, int, int]] = set()
    for kb_line in kb_text.splitlines():
        for pattern in _CALLABLE_ATOM_PATTERNS:
            m = pattern.match(kb_line)
            if m is not None:
                loc = _restore_location(m.group(1))
                if loc is not None and loc.filename.endswith(file_suffix):
                    callables.add((loc.filename, loc.lineStart, loc.colStart, loc.lineEnd, loc.colEnd))
                break
    matches = [c for c in callables if c[1] == line]
    if not matches:
        print(f"[probe] no callable starts at {file_suffix}:{line}; callables in matching files:",
              file=sys.stderr)
        for filename, l1, c1, l2, c2 in sorted(callables):
            print(f"  * {filename}:{l1}:{c1}-{l2}:{c2}", file=sys.stderr)
        raise SystemExit(2)
    filename, l1, c1, l2, c2 = max(matches, key=lambda c: (c[3] - c[1], c[4] - c[2]))
    return Location(filename=filename, lineStart=l1, colStart=c1, lineEnd=l2, colEnd=c2)


def _target_from_handler(args: argparse.Namespace) -> EndpointRef:
    kb_text = _read_kb(args.kb, args.kb_file, args.queryengine_container)
    handler = _resolve_handler(kb_text, args.handler_file, args.handler_line)
    print(f"[probe] handler resolved: {handler.filename}:{handler.lineStart}:{handler.colStart}"
          f"-{handler.lineEnd}:{handler.colEnd}")
    return EndpointRef(
        method=args.method,
        url=args.url,
        handler_location=handler,
        bucket=EndpointBucket(args.bucket),
    )


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
    if args.handler_file is not None:
        target = _target_from_handler(args)
    else:
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

    def llm_round(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        round_index: int,
        *,
        content: str,
        finish_reason: typing.Optional[str],
        tool_calls: list[dict[str, typing.Any]],
        reasoning_tokens: typing.Optional[int],
    ) -> None:
        self._trace.llm_round(
            self._item_id,
            round_index,
            content=content,
            finish_reason=finish_reason,
            tool_calls=tool_calls,
            reasoning_tokens=reasoning_tokens,
        )
        tc_names = ",".join(tc.get("name", "?") for tc in tool_calls) or "<none>"
        snippet = (content[:70] + "\u2026") if len(content) > 70 else content
        rt = f" reasoning_tokens={reasoning_tokens}" if reasoning_tokens is not None else ""
        print(f"  [llm #{round_index}] finish={finish_reason!r} tools=[{tc_names}]{rt} content={snippet!r}")

    def kbapi_call(self, call_index: int, query: dict[str, typing.Any]) -> None:
        self._trace.kbapi_call(self._item_id, call_index, query)
        print(f"  [kbapi #{call_index}] -> tag={query.get('tag')!r}")

    def kbapi_reply(self, call_index: int, reply: dict[str, typing.Any]) -> None:
        self._trace.kbapi_reply(self._item_id, call_index, reply)
        print(f"  [kbapi #{call_index}] <- tag={reply.get('tag')!r}")


if __name__ == "__main__":
    raise SystemExit(main())
