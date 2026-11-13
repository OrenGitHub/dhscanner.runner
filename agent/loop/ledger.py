"""Per-endpoint dataflow ledger, kept by the outer loop across sessions.

The goal is a real dataflow, from a user input to a sink ( docs/GOAL.md ).
A handler with I user inputs and S reachable sinks has I x S candidate
pairs, and one session only affords a few ``SelectDataFlowPath`` queries :
Chatwoot ``instagram/callbacks#show`` has 7 inputs x 4 sinks = 28 pairs
for a budget of 6. So the loop, not the model, remembers :

* the endpoint's user inputs ( from the seed ) and its sinks ( from every
  ``SelectControlFlowReachableSinks`` reply ),
* every ``( from, to )`` pair a ``SelectDataFlowPath`` already asked, and
  whether the kb found a path,
* every query's reply, so asking it again costs no budget.

The next session on the endpoint sees the tried and the untried pairs,
and an ``inconclusive`` endpoint goes back on the queue while untried
pairs remain ( ``agent/loop/loop.py`` ).

A location is keyed by ``( filename, colStart, colEnd )`` : a kb column
is an offset from the start of the file, so the key pins a location by
itself ( and a retyped line does not split it in two ).
"""

from __future__ import annotations

import json
import typing


LocationKey = tuple[str, int, int]

_LOCATION_KEYS: typing.Final[frozenset[str]] = frozenset(
    {"filename", "lineStart", "lineEnd", "colStart", "colEnd"}
)

_DATAFLOW_TAG: typing.Final[str] = "SelectDataFlowPath"
_SINKS_TAG: typing.Final[str] = "SelectControlFlowReachableSinks"


def location_key(node: typing.Any) -> typing.Optional[LocationKey]:
    """The key of a kb location dict, or ``None`` when ``node`` is not one."""
    if not isinstance(node, dict) or not _LOCATION_KEYS <= node.keys():
        return None
    filename, col_start, col_end = node["filename"], node["colStart"], node["colEnd"]
    if not isinstance(filename, str) or not isinstance(col_start, int) or not isinstance(col_end, int):
        return None
    return (filename, col_start, col_end)


def first_location(node: typing.Any) -> typing.Optional[dict[str, typing.Any]]:
    """The first kb location found in ``node``, depth first."""
    if location_key(node) is not None:
        return {k: node[k] for k in _LOCATION_KEYS}
    children: typing.Iterable[typing.Any] = ()
    if isinstance(node, dict):
        children = node.values()
    elif isinstance(node, list):
        children = node
    for child in children:
        found = first_location(child)
        if found is not None:
            return found
    return None


def _short(loc: dict[str, typing.Any]) -> str:
    return f"{loc['filename']}:{loc['lineStart']}-{loc['lineEnd']} cols {loc['colStart']}-{loc['colEnd']}"


def _query_key(tag: str, contents: dict[str, typing.Any]) -> str:
    return json.dumps({"tag": tag, "contents": contents}, sort_keys=True)


class DataflowLedger:
    """Cross-session memory of one endpoint's input x sink search."""

    def __init__(self, user_inputs: typing.Iterable[dict[str, typing.Any]]) -> None:
        self._inputs: dict[LocationKey, dict[str, typing.Any]] = {}
        self._sinks: dict[LocationKey, dict[str, typing.Any]] = {}
        # ( from, to ) -> the path, or None when the kb found none
        self._tried: dict[tuple[LocationKey, LocationKey], typing.Optional[list[typing.Any]]] = {}
        self._replies: dict[str, dict[str, typing.Any]] = {}
        for user_input in user_inputs:
            loc = first_location(user_input.get("contents"))
            key = location_key(loc)
            if loc is not None and key is not None:
                self._inputs.setdefault(key, {"kind": user_input.get("tag"), "location": loc})

    # -- recording ----------------------------------------------------------

    def observe(self, tag: str, contents: dict[str, typing.Any], reply: dict[str, typing.Any]) -> None:
        """Record one kbapi query and its reply ( a failed query is not cached )."""
        if reply.get("tag") == "KbapiError":
            return
        self._replies[_query_key(tag, contents)] = reply
        found = reply.get("contents")
        if not isinstance(found, dict):
            return
        if tag == _SINKS_TAG:
            for match in found.get("matches") or []:
                key = location_key(match.get("location")) if isinstance(match, dict) else None
                if key is not None:
                    self._sinks.setdefault(key, match)
        elif tag == _DATAFLOW_TAG:
            src, dst = location_key(contents.get("from")), location_key(contents.get("to"))
            if src is not None and dst is not None:
                path = found.get("path")
                self._tried[(src, dst)] = path if isinstance(path, list) else None

    def cached_reply(self, tag: str, contents: dict[str, typing.Any]) -> typing.Optional[dict[str, typing.Any]]:
        """The reply to the very same query, when one was already asked."""
        return self._replies.get(_query_key(tag, contents))

    # -- reading --------------------------------------------------------------

    def untried_pairs(self) -> list[tuple[dict[str, typing.Any], dict[str, typing.Any]]]:
        """( input location, sink location ) pairs no session asked yet."""
        return [
            (user_input["location"], sink["location"])
            for src, user_input in self._inputs.items()
            for dst, sink in self._sinks.items()
            if (src, dst) not in self._tried
        ]

    def has_sinks(self) -> bool:
        return bool(self._sinks)

    def found_paths(self) -> int:
        return sum(1 for path in self._tried.values() if path is not None)

    def prompt_section(self, max_untried_shown: int = 40) -> typing.Optional[str]:
        """The user prompt section, or ``None`` before any sink is known."""
        if not self._sinks:
            return None
        lines = [
            "## Dataflow pairs for THIS endpoint (kept by the outer loop across sessions)",
            f"{len(self._inputs)} user inputs x {len(self._sinks)} sinks = "
            f"{len(self._inputs) * len(self._sinks)} pairs. Already asked pairs are "
            "answered from the ledger at no budget cost, so spend your "
            "`SelectDataFlowPath` calls on UNTRIED pairs, copying `from` / `to` "
            "from the locations below.",
            "",
            "user inputs:",
        ]
        lines += [f"* {u['kind']} {_short(u['location'])}" for u in self._inputs.values()]
        lines += ["", "sinks:"]
        lines += [
            f"* {s.get('kind')} {s.get('qualifiedName')} {_short(s['location'])}"
            for s in self._sinks.values()
        ]
        tried = [
            f"* {self._describe(src, self._inputs)} -> {self._describe(dst, self._sinks)} : "
            + ("PATH FOUND" if path is not None else "no path")
            for (src, dst), path in self._tried.items()
        ]
        lines += ["", f"tried ( {len(tried)} ):"] + (tried or ["* none yet"])
        untried = self.untried_pairs()
        lines += ["", f"untried ( {len(untried)} ):"]
        lines += [
            f"* from {json.dumps(src)} to {json.dumps(dst)}"
            for src, dst in untried[:max_untried_shown]
        ] or ["* none : every pair was asked"]
        if len(untried) > max_untried_shown:
            lines.append(f"* ... and {len(untried) - max_untried_shown} more")
        return "\n".join(lines)

    @staticmethod
    def _describe(key: LocationKey, known: dict[LocationKey, dict[str, typing.Any]]) -> str:
        entry = known.get(key)
        if entry is not None:
            return _short(entry["location"])
        return f"{key[0]} cols {key[1]}-{key[2]}"
