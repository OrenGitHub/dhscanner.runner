"""Fresh LLM session for one popped queue item (\u00a72.3 + \u00a72.4).

Discipline:

* **One session per item.** Spawned by the outer loop every time a
  new item is popped. No context carries across sessions \u2014 that
  invariant is enforced here by never caching an :class:`openai.OpenAI`
  conversation across calls to :func:`run_item_session`.
* **LLM has no queue visibility** (\u00a72.3). The system+user prompts
  bundle exactly four slots: static system prompt, KB pointer,
  the popped item + its findings history, the frozen digest snapshot.
* **Hard budgets:** at most ``kbapi_query_budget`` kbapi queries per
  session + a wall-clock bound (\u00a72.4). Hitting either returns a
  synthetic ``inconclusive`` so the outer loop can re-enqueue the
  item at the back.
* **Guardrailed output.** The model's reply is parsed through the
  :class:`LlmResponse` Pydantic model with ``extra='forbid'``;
  anything else collapses to ``inconclusive``.

The ping-pong exchange with the KB (one of the SHIPPED artefacts per
\u00a74 point 3) is captured by invoking an optional :class:`Trace`
hook per kbapi call/reply, so the outer loop can keep the trace writer
as the single source of persistence truth.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import logging
import os
import time
import typing

import pydantic

from agent.loop.kbapi import KbapiClient, KbapiError
from agent.loop.types import (
    EndpointRef,
    HistoryEntry,
    LlmResponse,
    ScanDigestSnapshot,
    Verdict,
)


_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Defaults (configurable through the CLI). Values picked to match the doc
# literally: \u00a72.4 names \"\u2264 5 kbapi queries\" + \"wall-clock bound\"
# + \"0..M enqueues per session, M ~5-10\".
# ---------------------------------------------------------------------------


DEFAULT_MODEL: typing.Final[str] = "gpt-5"
DEFAULT_KBAPI_QUERY_BUDGET: typing.Final[int] = 5
DEFAULT_WALL_CLOCK_SECONDS: typing.Final[float] = 180.0
DEFAULT_OPENAI_TIMEOUT_SECONDS: typing.Final[float] = 60.0
DEFAULT_ENQUEUE_BUDGET: typing.Final[int] = 10
# How many history records to show the LLM in the user prompt. Older
# records are summarised to keep the prompt bounded; the full
# transcript always lives in the ScanTrace on disk.
_MAX_HISTORY_SHOWN: typing.Final[int] = 10


# ---------------------------------------------------------------------------
# Static system prompt. Owns the \"one job per session\" contract.
# ---------------------------------------------------------------------------


SYSTEM_PROMPT: typing.Final[str] = """\
You are a security analyst session inside the dhscanner outer loop. One
endpoint is on your desk right now. Your single job is to decide, with
evidence, whether this endpoint is `safe`, `suspicious`, `defer`, or
`inconclusive`, and (if relevant) to propose cross-endpoint pair-edges
to enqueue for later sessions.

Division of labor:

* The knowledge base knows the code. You query it through the
  `kbapi_query` tool. Each call reports *structural evidence*
  (locations, FQNs, sink kinds, constness, dataflow paths) \u2014 you
  interpret that evidence into verdicts.
* The outer loop knows the plan. It owns the queue, the per-endpoint
  findings history (shown in your user prompt), and the ScanDigest
  counts snapshot (also shown). You never see the queue itself.
* You do the judgment. One item, this session.

Hard constraints:

* You may invoke `kbapi_query` at most {kbapi_budget} times this
  session. Spend them on evidence that bears on this specific
  endpoint's verdict.
* You have a wall-clock bound. Prioritise cheap structural queries
  before expensive dataflow queries.
* Your final reply MUST be a JSON object matching the required schema
  exactly (`verdict`, `reason_for_verdict`, `enqueue`). Do not add
  prose outside that schema.
* You may propose up to {enqueue_budget} pair-edge enqueues. Each
  must point at an in-codebase handler you have reason to believe is
  reachable from THIS endpoint (e.g. its response URL resolves to
  another handler). Attach the parent's endpoint id and the
  mechanism (e.g. `url_signing`, `oauth_state`, `jwt_capability`,
  `email_token`). Pair-edges go to the front of the queue by default.
* Narrating the counts snapshot in `reason_for_verdict` is encouraged
  (base rates, anomalies) \u2014 but you cannot mutate it.
"""


# ---------------------------------------------------------------------------
# kbapi tool exposed to the model. One function, one dispatcher.
# ---------------------------------------------------------------------------


KBAPI_TOOL_NAME: typing.Final[str] = "kbapi_query"

# These are the tags the LLM is allowed to invoke directly. Mirrors
# `Kbapi.Query` constructors in dhscanner.packages/dhscanner.kbapi/src/Kbapi.hs.
# Adding a tag here is a leaf-add: no caller churn.
_ALLOWED_TAGS: tuple[str, ...] = (
    "ConstStringsMatching",
    "CommentsInFunction",
    "WriteContentToLocalFile",
    "ControlFlowPath",
    "DataFlowPath",
    "ControlFlowReachableSqlSink",
    "ControlFlowReachableFileActionSink",
)


# Per-tag `contents` schemas. Haskell-side field names (`Content.hs`) are
# record selectors, so the JSON keys are the selectors verbatim \u2014 e.g.
# `constStringsMatchingThisRegex`, not `pattern` or `regex`. The LLM
# previously guessed shorter names and got HTTP 400 on every call, so we
# bake the real schemas straight into the tool description.
#
# `Location` is a nested object with exactly these fields:
#   {filename: string, lineStart: int, lineEnd: int, colStart: int, colEnd: int}
_TAG_CONTENTS_DOC: typing.Final[str] = (
    "contents MUST use the exact field names from Content.hs (Haskell "
    "record selectors). A `Location` object is "
    "{filename, lineStart, lineEnd, colStart, colEnd}. Per-tag schema:\n"
    "\n"
    "  ConstStringsMatching:\n"
    "    { constStringsMatchingThisRegex: string,\n"
    "      constStringsMatchingLimit: int }\n"
    "\n"
    "  CommentsInFunction:\n"
    "    { commentsInFunctionLocation: Location,\n"
    "      commentsInFunctionLimit: int }\n"
    "\n"
    "  WriteContentToLocalFile:\n"
    "    { writeContentToLocalFileLimit: int }\n"
    "\n"
    "  ControlFlowPath:\n"
    "    { controlFlowPathCaller: Location,\n"
    "      controlFlowPathCallee: Location,\n"
    "      controlFlowPathLimitNumHops: int }\n"
    "\n"
    "  DataFlowPath:\n"
    "    { dataFlowPathFrom: Location,\n"
    "      dataFlowPathTo: Location,\n"
    "      dataFlowPathLimitLength: int }\n"
    "\n"
    "  ControlFlowReachableSqlSink:\n"
    "    { controlFlowReachableSqlSinkFrom: Location,\n"
    "      controlFlowReachableSqlSinkLimitNumHops: int,\n"
    "      controlFlowReachableSqlSinkLimit: int }\n"
    "\n"
    "  ControlFlowReachableFileActionSink:\n"
    "    { controlFlowReachableFileActionSinkFrom: Location,\n"
    "      controlFlowReachableFileActionSinkLimitNumHops: int,\n"
    "      controlFlowReachableFileActionSinkLimit: int }\n"
    "\n"
    "The endpoint on your desk carries its `handler_location`: that is "
    "the Location you want for the *From/Caller/Location field of "
    "sink-enumeration / reachability / comment queries. Typical "
    "`...Limit` values: 10 for num-hops, 50-100 for match limits."
)


def _kbapi_tool_schema(allowed_tags: tuple[str, ...]) -> dict[str, typing.Any]:
    return {
        "type": "function",
        "function": {
            "name": KBAPI_TOOL_NAME,
            "description": (
                "Fire one query against the dhscanner knowledge base. Returns "
                "the queryengine's JSON reply verbatim. Use evidence-level "
                "queries (ControlFlowReachableSqlSink, DataFlowPath, ...) \u2014 "
                "the KB does not pre-bake verdicts.\n\n"
                + _TAG_CONTENTS_DOC
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "tag": {
                        "type": "string",
                        "enum": list(allowed_tags),
                        "description": "The kbapi Query tag.",
                    },
                    "contents": {
                        "type": "object",
                        "description": (
                            "Tag-specific payload. Field names are Haskell "
                            "record selectors verbatim \u2014 see the main "
                            "tool description for the per-tag schema."
                        ),
                    },
                },
                "required": ["tag", "contents"],
            },
        },
    }


# ---------------------------------------------------------------------------
# Session result.
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class SessionResult:
    """Everything the outer loop needs to persist from one session."""

    response: LlmResponse
    kb_queries: list[dict[str, typing.Any]]
    kb_responses: list[dict[str, typing.Any]]
    kb_query_budget_used: int
    wall_clock_seconds: float
    # True iff the session returned a *synthetic* inconclusive because
    # one of the hard budgets fired. The outer loop uses this to decide
    # whether to re-enqueue at the back (\u00a72.4).
    forced_inconclusive: bool = False


# ---------------------------------------------------------------------------
# Trace hook interface. Kept tiny so session.py doesn't depend on
# the full trace module directly.
# ---------------------------------------------------------------------------


class SessionTraceHook(typing.Protocol):
    def kbapi_call(self, call_index: int, query: dict[str, typing.Any]) -> None: ...
    def kbapi_reply(self, call_index: int, reply: dict[str, typing.Any]) -> None: ...


class _NullHook:
    # pylint: disable=unused-argument
    def kbapi_call(self, call_index: int, query: dict[str, typing.Any]) -> None:
        return

    def kbapi_reply(self, call_index: int, reply: dict[str, typing.Any]) -> None:
        return


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------


def run_item_session(  # pylint: disable=too-many-arguments,too-many-locals,too-many-branches,too-many-statements,too-many-positional-arguments
    *,
    endpoint: EndpointRef,
    history: list[HistoryEntry],
    digest_snapshot: ScanDigestSnapshot,
    kbapi_client: KbapiClient,
    model: str = DEFAULT_MODEL,
    kbapi_query_budget: int = DEFAULT_KBAPI_QUERY_BUDGET,
    enqueue_budget: int = DEFAULT_ENQUEUE_BUDGET,
    wall_clock_seconds: float = DEFAULT_WALL_CLOCK_SECONDS,
    openai_timeout_seconds: float = DEFAULT_OPENAI_TIMEOUT_SECONDS,
    trace_hook: typing.Optional[SessionTraceHook] = None,
) -> SessionResult:
    """Run exactly one fresh LLM session on exactly one endpoint.

    See the module docstring for the contract. Return value is
    always a :class:`SessionResult` \u2014 we never raise out of this
    function. A broken OpenAI reply, a kbapi failure mid-session, a
    budget overrun: all collapse to a synthetic ``inconclusive``.
    """
    # Lazy import so `import agent.loop` stays cheap and so the
    # package is tolerant of a missing `openai` extra (same style
    # launcher.py uses).
    # pylint: disable=import-outside-toplevel
    try:
        from openai import OpenAI
    except ImportError:
        return _synthetic_inconclusive(
            reason=(
                "openai SDK not installed; cannot run a fresh LLM session. "
                "Run: pip install -r requirements.txt"
            ),
        )

    hook: SessionTraceHook = trace_hook or _NullHook()
    client = OpenAI(timeout=openai_timeout_seconds)

    system = SYSTEM_PROMPT.format(
        kbapi_budget=kbapi_query_budget,
        enqueue_budget=enqueue_budget,
    )
    user = _build_user_prompt(endpoint, history, digest_snapshot)
    messages: list[dict[str, typing.Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    kb_queries: list[dict[str, typing.Any]] = []
    kb_responses: list[dict[str, typing.Any]] = []
    budget_used = 0

    response_format = _llm_response_format()
    tool_schema = _kbapi_tool_schema(_ALLOWED_TAGS)
    started = time.monotonic()

    # Hard cap on OpenAI rounds. Each tool-emitting round advances by
    # one; add +2 for the eventual budget-exhausted no-tools round
    # plus a safety margin. If OpenAI starts spinning on tool calls
    # forever (shouldn't happen under structured output + budget),
    # we land here instead of looping.
    max_rounds = kbapi_query_budget + 3

    for round_index in range(max_rounds):
        elapsed = time.monotonic() - started
        if elapsed >= wall_clock_seconds:
            return _finalize_forced(
                kb_queries, kb_responses, budget_used, started,
                reason=(
                    f"wall-clock bound of {wall_clock_seconds:.1f}s exceeded "
                    f"after {round_index} rounds; re-enqueue at back."
                ),
            )

        budget_exhausted = budget_used >= kbapi_query_budget
        kwargs: dict[str, typing.Any] = {
            "model": model,
            "messages": messages,
            "response_format": response_format,
        }
        if not budget_exhausted:
            kwargs["tools"] = [tool_schema]

        try:
            resp = client.chat.completions.create(  # type: ignore[call-overload]
                **kwargs,
            )
        except Exception as exc:  # pylint: disable=broad-except
            _log.warning("openai call failed round=%d: %s", round_index, exc)
            return _finalize_forced(
                kb_queries, kb_responses, budget_used, started,
                reason=f"openai call failed: {exc}",
            )

        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        if not tool_calls:
            parsed = _parse_llm_response(msg.content or "{}")
            if parsed is None:
                return _finalize_forced(
                    kb_queries, kb_responses, budget_used, started,
                    reason=(
                        "LLM reply did not validate against the LlmResponse "
                        "schema; re-enqueue at back."
                    ),
                )
            return SessionResult(
                response=parsed,
                kb_queries=kb_queries,
                kb_responses=kb_responses,
                kb_query_budget_used=budget_used,
                wall_clock_seconds=time.monotonic() - started,
            )

        # Replay the assistant turn before issuing tool replies \u2014 OpenAI
        # requires each `role=tool` message to point back at a prior
        # assistant tool_call id.
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ],
        })

        for tc in tool_calls:
            if budget_used >= kbapi_query_budget:
                # Model tried to overrun its budget. Report the
                # rejection as a tool-side error and keep going so
                # the model can commit a verdict with what it has.
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps({
                        "error": "kbapi query budget exhausted; commit a verdict now",
                    }),
                })
                continue

            name = tc.function.name
            raw_args = tc.function.arguments or "{}"
            if name != KBAPI_TOOL_NAME:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps({
                        "error": f"unknown tool: {name!r}",
                    }),
                })
                continue
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError as exc:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps({
                        "error": f"malformed JSON arguments: {exc}",
                    }),
                })
                continue
            tag = args.get("tag")
            contents = args.get("contents") or {}
            if tag not in _ALLOWED_TAGS or not isinstance(contents, dict):
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps({
                        "error": "tag must be in the allowed set + contents must be a JSON object",
                    }),
                })
                continue

            query_payload = {"tag": tag, "contents": contents}
            call_index = budget_used + 1
            hook.kbapi_call(call_index, query_payload)
            kb_queries.append(query_payload)
            try:
                reply = kbapi_client.query(tag, contents)
            except KbapiError as exc:
                reply = {"tag": "KbapiError", "contents": {"error": str(exc)}}
            budget_used += 1
            hook.kbapi_reply(call_index, reply)
            kb_responses.append(reply)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(reply),
            })

    # Fell out of the loop without a final reply \u2014 force inconclusive.
    return _finalize_forced(
        kb_queries, kb_responses, budget_used, started,
        reason=(
            f"OpenAI session exceeded {max_rounds} rounds without a verdict; "
            "re-enqueue at back."
        ),
    )


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _llm_response_format() -> dict[str, typing.Any]:
    """Pin down the response_format schema from the Pydantic model.

    OpenAI's structured-output mode requires a JSON schema object
    with a top-level ``name`` + ``schema``. We derive both from
    :class:`LlmResponse` so the schema and the Pydantic validator
    never drift apart.

    Pydantic emits a schema full of ``$defs`` references and
    ``allOf`` wrappers (so an enum field with a default looks like
    ``{"allOf": [{"$ref": "#/$defs/Hint"}], "default": "back"}``).
    OpenAI's strict mode disallows ``allOf`` entirely and disallows
    sibling keys next to ``$ref``, so we fully inline the defs,
    unwrap single-element ``allOf`` wrappers, then enforce
    ``additionalProperties: false`` + a complete ``required`` list
    on every object subschema.
    """
    schema = LlmResponse.model_json_schema()
    defs = schema.pop("$defs", {})
    if isinstance(defs, dict) and defs:
        _inline_defs(schema, defs)
    _tighten_schema(schema)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "LlmResponse",
            "schema": schema,
            "strict": True,
        },
    }


def _inline_defs(schema: dict[str, typing.Any], defs: dict[str, typing.Any]) -> None:
    """Fully inline every ``$ref`` and unwrap single-element ``allOf``.

    ``defs`` may reference other entries in ``defs`` (e.g.
    ``EnqueueProposal`` -> ``EndpointRef`` -> ``Location``), so we
    iterate to a fixed point. Pydantic never produces reference
    cycles for our model graph, so a modest iteration cap is safe
    and keeps a buggy input from spinning forever.
    """
    for _ in range(32):
        before = json.dumps(schema, sort_keys=True)
        _resolve_node(schema, defs)
        for d in defs.values():
            _resolve_node(d, defs)
        if json.dumps(schema, sort_keys=True) == before:
            return


def _resolve_node(node: typing.Any, defs: dict[str, typing.Any]) -> None:
    if isinstance(node, dict):
        # Unwrap `allOf: [X]` -> X merged into the parent. Pydantic
        # uses this shape to attach `default`/`description`/etc. to a
        # bare `$ref`; strict mode rejects it, so we flatten.
        all_of = node.get("allOf")
        if isinstance(all_of, list) and len(all_of) == 1 and isinstance(all_of[0], dict):
            inner = node.pop("allOf")[0]
            for k, v in inner.items():
                if k not in node:
                    node[k] = v
        # Inline `$ref`. Strict mode rejects sibling keys next to
        # `$ref`, so we drop the ref and merge the referent's keys
        # into the parent node (parent-level overrides win).
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            def_name = ref[len("#/$defs/"):]
            target = defs.get(def_name)
            if isinstance(target, dict):
                del node["$ref"]
                for k, v in copy.deepcopy(target).items():
                    if k not in node:
                        node[k] = v
        for v in list(node.values()):
            _resolve_node(v, defs)
    elif isinstance(node, list):
        for v in node:
            _resolve_node(v, defs)


def _tighten_schema(node: typing.Any) -> None:
    """Recursively enforce OpenAI structured-output "strict" rules.

    Strict mode requires every object subschema to:

    1. Set ``additionalProperties: false``.
    2. List EVERY key of ``properties`` in ``required`` \u2014 strict mode
       has no concept of an optional property. Fields that Pydantic
       marked ``Optional[...]`` already carry ``"null"`` in their type
       union, so the LLM can satisfy them by emitting ``null``.

    We walk the full schema (including ``$defs``, ``items``, nested
    ``anyOf``/``oneOf`` branches) so every object subschema is tightened,
    not just the top-level one.
    """
    if isinstance(node, dict):
        if node.get("type") == "object":
            if "additionalProperties" not in node:
                node["additionalProperties"] = False
            props = node.get("properties")
            if isinstance(props, dict) and props:
                # Overwrite rather than union with existing `required`:
                # strict mode wants exactly the full property set.
                node["required"] = list(props.keys())
        for v in node.values():
            _tighten_schema(v)
    elif isinstance(node, list):
        for v in node:
            _tighten_schema(v)


def _parse_llm_response(raw: str) -> typing.Optional[LlmResponse]:
    try:
        return LlmResponse.model_validate_json(raw)
    except pydantic.ValidationError as exc:
        _log.warning("LlmResponse validation failed: %s\nraw=%s", exc, raw[:400])
        return None
    except ValueError as exc:
        _log.warning("LlmResponse json parse failed: %s", exc)
        return None


def _build_user_prompt(
    endpoint: EndpointRef,
    history: list[HistoryEntry],
    digest_snapshot: ScanDigestSnapshot,
) -> str:
    history_shown = history[-_MAX_HISTORY_SHOWN:]
    older_count = max(0, len(history) - _MAX_HISTORY_SHOWN)
    sections: list[str] = []

    sections.append(
        "## Endpoint on your desk\n"
        f"```json\n{json.dumps(endpoint.model_dump(), indent=2)}\n```"
    )

    if history:
        prev = "\n".join(
            json.dumps(rec.model_dump(mode='json'), indent=2) for rec in history_shown
        )
        preamble = (
            f"## History for THIS endpoint ({len(history)} entries"
            + (f"; showing last {_MAX_HISTORY_SHOWN}" if older_count else "")
            + ")\n"
            + "Discriminated by `kind`:\n"
            + "* `session` \u2014 a prior fresh-session verdict + reasoning +\n"
            + "  kbapi queries/responses + enqueues.\n"
            + "* `provenance_arrival` \u2014 another endpoint's session named\n"
            + "  this one as a pair-edge target (so you are a bucket-C H2;\n"
            + "  reconcile the parent's capability-scope with your handler).\n"
            + f"```json\n{prev}\n```"
        )
        sections.append(preamble)
    else:
        sections.append(
            "## History for THIS endpoint\n"
            "None. This is the first time anyone looked at this endpoint."
        )

    sections.append(
        "## ScanDigest counts snapshot (frozen; you cannot mutate)\n"
        f"```json\n{json.dumps(digest_snapshot.model_dump(), indent=2)}\n```"
    )

    sections.append(
        "## Your output\n"
        "Return ONE JSON object matching the LlmResponse schema. If you "
        "need evidence, call `kbapi_query` first (within budget); then "
        "return the JSON object."
    )

    return "\n\n".join(sections)


def _synthetic_inconclusive(reason: str) -> SessionResult:
    return SessionResult(
        response=LlmResponse(
            verdict=Verdict.INCONCLUSIVE,
            reason_for_verdict=reason,
            enqueue=[],
        ),
        kb_queries=[],
        kb_responses=[],
        kb_query_budget_used=0,
        wall_clock_seconds=0.0,
        forced_inconclusive=True,
    )


def _finalize_forced(
    kb_queries: list[dict[str, typing.Any]],
    kb_responses: list[dict[str, typing.Any]],
    budget_used: int,
    started: float,
    *,
    reason: str,
) -> SessionResult:
    return SessionResult(
        response=LlmResponse(
            verdict=Verdict.INCONCLUSIVE,
            reason_for_verdict=reason,
            enqueue=[],
        ),
        kb_queries=kb_queries,
        kb_responses=kb_responses,
        kb_query_budget_used=budget_used,
        wall_clock_seconds=time.monotonic() - started,
        forced_inconclusive=True,
    )


# ---------------------------------------------------------------------------
# A tiny convenience for CLI callers that forgot to export the API key.
# ---------------------------------------------------------------------------


def openai_api_key_present() -> bool:
    """Cheap pre-flight: refuse to start the loop if there's no key."""
    key = os.environ.get("OPENAI_API_KEY")
    return bool(key and key.strip())
