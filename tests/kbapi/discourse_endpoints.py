"""Assert the Rails recognizer finds Discourse's endpoints.

Runs against the agent-mode KB of the full Discourse repo ( ``b81bee142d3`` ).
Stdlib only, so CI can pipe it into any container on the compose network::

    docker compose ... exec -T app python - <kb_location> < tests/kbapi/discourse_endpoints.py

``SelectHttpHandlers`` is the agent's seed query ( ``agent/loop/seeder.py`` ).
Rails finds controllers by convention, not imports : the handlers are the
methods of ``*Controller`` classes defined under a ``controllers/`` dir,
minus the ``def`` s after a bare ``private`` / ``protected`` ( queryengine
``predicates/endpoints/ruby/rails.pl``, runner #138 ). Before it the seed
query returned 0 handlers on Discourse, 2,031 with private helpers, 1,232
without them ( 310 / 333 controllers ; the source has ~1,400 public
actions, the rest sit in files that do not parse yet, eg
``posts_controller.rb`` ). The floor is a round number below that.
"""

from __future__ import annotations

import collections
import json
import sys
import typing
import urllib.request

KBAPI_URL = "http://queryengine:3000/api"
MIN_HANDLERS = 1_200


def handlers(kb_location: str) -> list[dict[str, typing.Any]]:
    request = urllib.request.Request(
        f"{KBAPI_URL}?kb_location={kb_location}",
        data=json.dumps({"tag": "SelectHttpHandlers", "contents": {
            "verbs": ["Get", "Post", "Put", "Delete", "Patch", "Unknown"],
            "authentications": ["Unauthenticated", "Authenticated"],
            "routeContainsUrlParts": None,
            "maxNumHttpHandlers": 10_000,
            "orderEndpointsLexicographically": True,
        }}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        reply: dict[str, typing.Any] = json.load(response)
    if reply.get("tag") != "FoundHttpHandlers":
        print(json.dumps(reply, indent=2))
        raise SystemExit(f"FAIL: SelectHttpHandlers replied {reply.get('tag')}")
    matches: list[dict[str, typing.Any]] = reply["contents"]["matches"]
    return matches


def main() -> int:
    found = handlers(sys.argv[1])
    verbs = collections.Counter(h["httpHandlerVerb"] for h in found)
    print(f"== {len(found)} handlers, by verb : {dict(sorted(verbs.items()))}")
    for h in found[:20]:
        print(f"   {h['httpHandlerVerb']:<8} {h['httpHandlerUrl']}  {h['httpHandlerLocation']['filename']}:{h['httpHandlerLocation']['lineStart']}")
    if len(found) < MIN_HANDLERS:
        print(f"FAIL: {len(found)} Discourse handlers, expected >= {MIN_HANDLERS}")
        return 1
    print(f"PASS: {len(found)} Discourse handlers ( >= {MIN_HANDLERS} )")
    return 0


if __name__ == "__main__":
    sys.exit(main())
