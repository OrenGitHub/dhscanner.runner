"""Assert the Huginn EventsController#show open redirect dataflow ( runner #165 ).

Runs against the agent-mode KB of the full Huginn repo ( ``639c050b2b`` ).
Stdlib only, so CI can pipe it into any container on the compose network::

    docker compose ... exec -T app python - <kb_location> < tests/kbapi/huginn_events_redirect.py

``app/controllers/events_controller.rb``::

    18  def show
    19    respond_to do |format|
    20      format.html do
    21        load_event
    22      rescue ActiveRecord::RecordNotFound
    23        return_to = params[:return] or raise
    24        redirect_to return_to, allow_other_host: false
    25      end

``params[:return]`` :23 -> ``return_to`` :23 -> ``redirect_to`` :24. Three
parser gaps hid it ( parsers 1.1.61 ) : the ``:return`` symbol ( a ruby
keyword ) failed the whole file, every ``rescue`` body was dropped, and the
``x = a or raise`` assignment expression dropped its target ``return_to``.

The redirect is safe : ``allow_other_host: false`` makes Rails raise on any
other host. Telling so is the sanitizer's job ( #165 ), not the KB's.
"""

from __future__ import annotations

import json
import sys
import typing
import urllib.request

KBAPI_URL = "http://queryengine:3000/api"
SINKS = ["FileOperationRead", "FileOperationWrite", "FileOperationDelete", "OpenRedirect", "SSRF", "SQL"]
EVENTS_CONTROLLER = "app/controllers/events_controller.rb"
# def show
HANDLER_LINE = 18
# params[:return]
USER_INPUT_LINE = 23
# return_to = .. ( the assignment target the path must go through )
RETURN_TO = (EVENTS_CONTROLLER, 23)
# redirect_to return_to, allow_other_host: false
SINK = (EVENTS_CONTROLLER, 24)

Location = dict[str, typing.Any]


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


def check(kb_location: str) -> list[str]:
    found = [
        h for h in handlers(kb_location)
        if h["httpHandlerLocation"]["filename"] == EVENTS_CONTROLLER
        and h["httpHandlerLocation"]["lineStart"] == HANDLER_LINE
    ]
    if len(found) != 1:
        return [f"{len(found)} handlers at {EVENTS_CONTROLLER}:{HANDLER_LINE}, expected 1 ( events#show )"]
    handler = found[0]
    print(f"== {handler['httpHandlerDef']} {handler['httpHandlerVerb']}")

    inputs: list[Location] = [
        i["contents"]["requestParamLocation"] for i in handler["httpHandlerUserInputs"]
        if i["tag"] == "RequestParamCtor" and int(i["contents"]["requestParamLocation"]["lineStart"]) == USER_INPUT_LINE
    ]
    print(f"   user inputs at :{USER_INPUT_LINE} : {len(inputs)}")
    if len(inputs) != 1:
        return [f"{len(inputs)} user inputs at :{USER_INPUT_LINE}, expected 1 ( params in the rescue clause )"]

    reply = query(kb_location, "SelectControlFlowReachableSinks", {"from": handler["httpHandlerLocation"], "sinks": SINKS, "maxNumHops": 10, "maxNumSinks": 50})
    sinks: list[Location] = [m["location"] for m in reply["contents"]["matches"] if m.get("kind") == "OpenRedirect" and key(m["location"]) == SINK]
    print(f"   control flow reachable open redirect sinks at {SINK} : {len(sinks)}")
    if len(sinks) != 1:
        return [f"open redirect sink {SINK} not reachable"]

    path = query(kb_location, "SelectDataFlowPath", {"from": inputs[0], "to": sinks[0], "maxNumIntraProceduralEdges": 50, "maxNumInterProceduralEdges": 10})["contents"]["path"]
    if path is None:
        return [f"no dataflow :{USER_INPUT_LINE} -> {SINK}"]
    print("   dataflow : " + " -> ".join(f"{p['filename'].rsplit('/', 1)[-1]}:{p['lineStart']}:{p['colStart']}-{p['colEnd']}" for p in path))
    # the target of `return_to = params[:return] or raise` : on line 23,
    # strictly left of the params call
    targets = [p for p in path if key(p) == RETURN_TO and int(p["colEnd"]) <= int(inputs[0]["colStart"])]
    if not targets:
        return ["dataflow skips the return_to assignment target :23"]
    return []


def main() -> int:
    errors = check(sys.argv[1])
    for error in errors:
        print(f"FAIL: {error}")
    if errors:
        return 1
    print("OK : params[:return] :23 -> return_to -> redirect_to :24 ( events#show rescue clause )")
    return 0


if __name__ == "__main__":
    sys.exit(main())
