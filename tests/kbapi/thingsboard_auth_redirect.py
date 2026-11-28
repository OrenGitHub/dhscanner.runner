"""Assert the ThingsBoard AuthController open redirect dataflows ( runner #161 ).

Runs against the agent-mode KB of a two file ThingsBoard sample
( ``91acf8567f`` ) : ``AuthController.java`` + ``BaseController.java``, both of
package ``org.thingsboard.server.controller``. Stdlib only, so CI can pipe it
into any container on the compose network::

    docker compose ... exec -T app python - <kb_location> < tests/kbapi/thingsboard_auth_redirect.py

``AuthController extends BaseController`` with no import : a class of the
same package needs none. The cli maps the same package classes a file names
and the parsers turn each into an implicit 1st party import, so the inherited
``redirectTo(..)`` resolves to ``BaseController#redirectTo``. Its
``ResponseEntity.status(..).location(uri)`` is a spring open redirect sink
( predicates v1.8.0 ``sinks/open_redirects/java/spring.pl`` ).

A : ``AuthController#checkActivateToken`` ( GET /api/noauth/activate, :126 ) :
    ``@RequestParam activateToken`` :133 -> ``"/login/createPassword?activateToken=" + ..``
    :141 -> ``redirectTo(location)`` :1690 -> ``URI.create`` -> ``.location(uri)`` :1698.
B : ``AuthController#checkResetToken`` ( GET /api/noauth/resetPassword, :173 ) :
    ``@RequestParam resetToken`` :180 -> :191 -> the same ``redirectTo`` sink.

Both are false positives : the input lands after a fixed ``/login/..`` path
( it cannot choose the host ) and the token must already exist in the db.
Telling so is the agent's job, not the KB's.
"""

from __future__ import annotations

import json
import sys
import typing
import urllib.request

KBAPI_URL = "http://queryengine:3000/api"
SINKS = ["FileOperationRead", "FileOperationWrite", "FileOperationDelete", "OpenRedirect", "SSRF", "SQL"]
AUTH_CONTROLLER = "application/src/main/java/org/thingsboard/server/controller/AuthController.java"
BASE_CONTROLLER = "application/src/main/java/org/thingsboard/server/controller/BaseController.java"
# ResponseEntity.status( HttpStatus.SEE_OTHER ).location( uri ) in BaseController#redirectTo
SINK = (BASE_CONTROLLER, 1698)
# the redirectTo( String location ) param : the path crosses into BaseController
REDIRECT_TO_PARAM = (BASE_CONTROLLER, 1690)

Location = dict[str, typing.Any]


class Expected(typing.NamedTuple):
    name: str
    # a line inside the handler ( its location starts at the annotations )
    line: int
    # the line of the @RequestParam
    user_input: int


EXPECTED = [
    Expected("A AuthController#checkActivateToken", 131, 133),
    Expected("B AuthController#checkResetToken", 177, 180),
]



def dataflow_path(content: typing.Any) -> typing.Optional[list[typing.Any]]:
    """The path of a SelectDataFlowPath reply's contents ( kbapi >= 2.0.0 ), None when there is none."""
    fields = {"PlainDataFlowPath": "plainDataFlowPath", "DBWriteDataFlowPath": "dbWriteDataFlowPath"}
    field = fields.get(str(content.get("tag"))) if isinstance(content, dict) else None
    path = content["contents"].get(field) if field is not None else None
    return path if isinstance(path, list) else None

def query(kb_location: str, tag: str, contents: dict[str, typing.Any]) -> dict[str, typing.Any]:
    request = urllib.request.Request(
        f"{KBAPI_URL}?kb_location={kb_location}",
        data=json.dumps({"tag": tag, "contents": contents}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=900) as response:
        reply: dict[str, typing.Any] = json.load(response)
    return reply


def handlers(kb_location: str) -> list[dict[str, typing.Any]]:
    reply = query(kb_location, "SelectHttpHandlers", {
        "verbs": ["Get", "Post", "Put", "Delete", "Patch", "Unknown"],
        "authentications": ["Unauthenticated", "Authenticated"],
        "routeContainsUrlParts": None,
        "maxNumHttpHandlers": 10_000,
        "orderEndpointsLexicographically": True,
    })
    if reply.get("tag") != "FoundHttpHandlers":
        print(json.dumps(reply, indent=2))
        raise SystemExit(f"FAIL: SelectHttpHandlers replied {reply.get('tag')}")
    matches: list[dict[str, typing.Any]] = reply["contents"]["matches"]
    return matches


def key(location: Location) -> tuple[str, int]:
    # lines, not columns : a column is an offset from the start of the file,
    # so it depends on the checkout's line endings ( crlf vs lf )
    return (str(location["filename"]), int(location["lineStart"]))


def check(kb_location: str, found: list[dict[str, typing.Any]], expected: Expected) -> list[str]:
    hits = [
        h for h in found
        if h["httpHandlerLocation"]["filename"] == AUTH_CONTROLLER
        and h["httpHandlerLocation"]["lineStart"] <= expected.line <= h["httpHandlerLocation"]["lineEnd"]
    ]
    if len(hits) != 1:
        return [f"{expected.name} : {len(hits)} handlers around {AUTH_CONTROLLER}:{expected.line}, expected 1"]
    handler = hits[0]
    print(f"== {expected.name} : {handler['httpHandlerDef']}")

    inputs: list[Location] = [
        i["contents"]["requestParamLocation"] for i in handler["httpHandlerUserInputs"]
        if i["tag"] == "RequestParamCtor" and int(i["contents"]["requestParamLocation"]["lineStart"]) == expected.user_input
    ]
    print(f"   user inputs at :{expected.user_input} : {len(inputs)}")
    if len(inputs) != 1:
        return [f"{expected.name} : {len(inputs)} user inputs at :{expected.user_input}, expected 1"]

    reply = query(kb_location, "SelectControlFlowReachableSinks", {"from": handler["httpHandlerLocation"], "sinks": SINKS, "maxNumHops": 10, "maxNumSinks": 50})
    sinks: list[Location] = [m["location"] for m in reply["contents"]["matches"] if m.get("kind") == "OpenRedirect" and key(m["location"]) == SINK]
    print(f"   control flow reachable open redirect sinks at {SINK} : {len(sinks)}")
    if len(sinks) != 1:
        return [f"{expected.name} : open redirect sink {SINK} not reachable"]

    path = dataflow_path(query(kb_location, "SelectDataFlowPath", {"from": inputs[0], "to": sinks[0], "maxNumIntraProceduralEdges": 50, "maxNumInterProceduralEdges": 10})["contents"])
    if path is None:
        return [f"{expected.name} : no dataflow :{expected.user_input} -> {SINK}"]
    print("   dataflow : " + " -> ".join(f"{p['filename'].rsplit('/', 1)[-1]}:{p['lineStart']}" for p in path))
    if REDIRECT_TO_PARAM not in [key(p) for p in path]:
        return [f"{expected.name} : dataflow skips the redirectTo param {REDIRECT_TO_PARAM}"]
    return []


def main() -> int:
    kb_location = sys.argv[1]
    found = handlers(kb_location)
    errors = [e for expected in EXPECTED for e in check(kb_location, found, expected)]
    for error in errors:
        print(f"FAIL: {error}")
    if errors:
        return 1
    print("OK : A + B, @RequestParam token -> inherited BaseController#redirectTo -> ResponseEntity.status.location")
    return 0


if __name__ == "__main__":
    sys.exit(main())
