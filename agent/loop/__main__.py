"""``python -m agent.loop`` CLI entry point.

Minimal argparse surface. We intentionally keep this *not* wired into
``cli/argparse_wrapper.py`` for the first pass \u2014 mirrors how
``agent/explore.py`` and ``agent/test.py`` are driven today, keeps
the first PR small, and preserves the top-of-``agent/explore.py`` TODO
about eventually promoting the whole trio into one ``python -m cli``
subcommand surface.
"""

from __future__ import annotations

import argparse
import logging
import os
import pathlib
import sys

from agent.loop.loop import ScanConfig, run_scan
from agent.loop.session import (
    DEFAULT_ENQUEUE_BUDGET,
    DEFAULT_KBAPI_QUERY_BUDGET,
    DEFAULT_OPENAI_TIMEOUT_SECONDS,
    DEFAULT_WALL_CLOCK_SECONDS,
)

_DEFAULT_KBAPI_URL = "http://localhost:3000/api"
_DEFAULT_MODEL_FALLBACK = "gpt-5"


def _load_dotenv_if_available() -> None:
    """Best-effort: load the repo-root ``.env`` into ``os.environ``.

    ``python-dotenv`` is already in ``requirements.txt`` (the CLI
    sibling `launcher.py` just doesn't currently use it); importing
    is wrapped so a missing extra never breaks a run that has the
    key already exported.
    """
    try:
        from dotenv import load_dotenv  # pylint: disable=import-outside-toplevel
    except ImportError:
        return
    # Walk up from this file's dir until we hit a ``.env`` or run
    # out of parents. Avoids ``cwd``-sensitivity.
    here = pathlib.Path(__file__).resolve()
    for ancestor in [here, *here.parents]:
        candidate = ancestor.parent / ".env" if ancestor.is_file() else ancestor / ".env"
        if candidate.is_file():
            load_dotenv(dotenv_path=candidate, override=False)
            return


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agent.loop",
        description=(
            "Deterministic LLM<->KB outer loop (OWASP-IL 2026 driver script). "
            "Seeds the work queue from the kb's A-union-B endpoint surface, "
            "spawns one fresh LLM session per popped item, persists a "
            "ScanTrace + ScanDigest counts snapshots on disk."
        ),
    )
    parser.add_argument(
        "--use_kb",
        required=True,
        metavar="kb_filename",
        help=(
            "kb filename as returned by `python -m cli run --with_agent` "
            "(forwarded verbatim to the queryengine as ?kb_location=...)"
        ),
    )
    parser.add_argument(
        "--kbapi-url",
        default=_DEFAULT_KBAPI_URL,
        metavar="URL",
        help=f"queryengine kbapi endpoint (default: {_DEFAULT_KBAPI_URL})",
    )
    parser.add_argument(
        "--model",
        default=None,
        metavar="MODEL",
        help=(
            "OpenAI chat model (default: $OPENAI_MODEL or "
            f"{_DEFAULT_MODEL_FALLBACK!r}); passed to every fresh session."
        ),
    )
    parser.add_argument(
        "--kbapi-query-budget",
        type=_positive_int,
        default=DEFAULT_KBAPI_QUERY_BUDGET,
        metavar="N",
        help=(
            f"max kbapi calls per fresh session (default: "
            f"{DEFAULT_KBAPI_QUERY_BUDGET}; see docs OWASP_NOTES_FINALIZED.md section 2.4)"
        ),
    )
    parser.add_argument(
        "--enqueue-budget",
        type=_positive_int,
        default=DEFAULT_ENQUEUE_BUDGET,
        metavar="M",
        help=(
            f"max pair-edge enqueues the LLM may propose per session "
            f"(default: {DEFAULT_ENQUEUE_BUDGET})"
        ),
    )
    parser.add_argument(
        "--wall-clock-per-session-s",
        type=_positive_float,
        default=DEFAULT_WALL_CLOCK_SECONDS,
        metavar="SECONDS",
        help=(
            f"per-session wall-clock bound (default: "
            f"{DEFAULT_WALL_CLOCK_SECONDS:.0f}; see docs OWASP_NOTES_FINALIZED.md section 2.4)"
        ),
    )
    parser.add_argument(
        "--openai-timeout-s",
        type=_positive_float,
        default=DEFAULT_OPENAI_TIMEOUT_SECONDS,
        metavar="SECONDS",
        help="per-openai-call timeout, within the per-session wall clock",
    )
    parser.add_argument(
        "--max-items",
        type=_positive_int,
        default=None,
        metavar="N",
        help="hard cap on items processed (default: run until queue drains)",
    )
    parser.add_argument(
        "--max-wall-clock-s",
        type=_positive_float,
        default=None,
        metavar="SECONDS",
        help="hard cap on total scan wall clock (default: unbounded)",
    )
    parser.add_argument(
        "--trace-root",
        type=pathlib.Path,
        default=None,
        metavar="DIR",
        help=(
            "where to write the ScanTrace (default: "
            "agent/.scan_traces/<kb-basename>/<timestamp>/)"
        ),
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="increase log verbosity (-v = INFO, -vv = DEBUG)",
    )
    return parser


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an int: {raw}") from exc
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {value}")
    return value


def _positive_float(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not a number: {raw}") from exc
    if value <= 0.0:
        raise argparse.ArgumentTypeError(f"must be > 0, got {value}")
    return value


def _configure_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%d/%m/%Y ( %H:%M:%S )",
        stream=sys.stdout,
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _configure_logging(args.verbose)
    _load_dotenv_if_available()

    model = args.model or os.environ.get("OPENAI_MODEL") or _DEFAULT_MODEL_FALLBACK

    config = ScanConfig(
        kb_location=args.use_kb,
        kbapi_url=args.kbapi_url,
        model=model,
        kbapi_query_budget=args.kbapi_query_budget,
        enqueue_budget=args.enqueue_budget,
        wall_clock_per_session_s=args.wall_clock_per_session_s,
        openai_timeout_s=args.openai_timeout_s,
        max_items=args.max_items,
        max_wall_clock_s=args.max_wall_clock_s,
        trace_root=args.trace_root,
    )

    try:
        result = run_scan(config)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print("scan complete")
    print(f"  items processed    : {result.items_processed}")
    print(f"  queue remaining    : {result.queue_remaining}")
    print(f"  trace root         : {result.trace_root}")
    for verdict, count in sorted(result.verdict_counts.items(), key=lambda kv: kv[0].value):
        print(f"  verdict[{verdict.value:<13}]: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
