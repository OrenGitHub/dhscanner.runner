"""Assert Rails user input and its dataflow on three Discourse actions ( runner #152 ).

Runs against the agent-mode KB of the full Discourse repo ( ``b81bee142d3`` ).
Stdlib only, so CI can pipe it into any container on the compose network::

    docker compose ... exec -T app python - <kb_location> < tests/kbapi/discourse_user_input.py

Rails user input is a ``params`` call in a method of a class whose super
chain reaches ``ActionController::Base`` ( queryengine
``predicates/endpoints/ruby/rails.pl`` ``endpoints_user_input_of_method_rails/2`` ).
``SelectHttpHandlers`` lists those calls as the handler's ``RequestParamCtor``
inputs ; before, a Rails handler's only input was the handler itself, with no
dataflow out of it. The three actions are the #152 definition of done, each
queried the way the agent loop does : the handler, its control flow
reachable SQL sinks, a ``SelectDataFlowPath`` from every input to every sink.

A : ``CategoriesController#set_notifications`` ( categories_controller.rb:356 ).
    ``params[:category_id]`` / ``params[:notification_level]`` go to
    ``CategoryUser.set_notification_level_for_category``, which reaches two
    ``DB.build`` sql sinks ( category_user.rb:88, :125 ) through a class
    method and an implicit self call. Neither input flows into the sql :
    control flow yes, user input yes, dataflow no.
B : ``TagsController#update_notifications`` ( tags_controller.rb:438 ), the
    same shape : two ``DB.build`` sinks ( tag_user.rb:134, :174 ), no dataflow.
C : ``Admin::UsersController#penalty_history`` ( admin/users_controller.rb:107 ),
    in ``Admin::StaffController`` < ``ApplicationController`` ( the namespaced
    super chain, a def-less class ) :
    ``DB.exec(sql, ....merge(user_id: params[:user_id].to_i))`` : the input
    flows into the sink, through the subscript, ``.to_i``, the hash and
    ``.merge``. The ``.to_i`` cast makes it safe ; telling so is the agent's
    job, not the KB's ( no sanitizer here yet ).
"""

from __future__ import annotations

import json
import sys
import typing
import urllib.request

KBAPI_URL = "http://queryengine:3000/api"
SINKS = ["FileOperationRead", "FileOperationWrite", "FileOperationDelete", "OpenRedirect", "SSRF", "SQL"]

Location = dict[str, typing.Any]


class Expected(typing.NamedTuple):
    name: str
    filename: str
    line: int
    # ( line, colStart ) of each `params` call
    inputs: list[tuple[int, int]]
    # ( filename, lineStart, colStart ) of each control flow reachable sql sink
    sinks: list[tuple[str, int, int]]
    # the sinks some input flows into ; the rest get a null path
    flows_into: list[tuple[str, int, int]]


EXPECTED = [
    Expected(
        "A CategoriesController#set_notifications",
        "app/controllers/categories_controller.rb", 356,
        inputs=[(357, 11716), (358, 11768)],
        sinks=[("app/models/category_user.rb", 88, 2434), ("app/models/category_user.rb", 125, 3635)],
        flows_into=[],
    ),
    Expected(
        "B TagsController#update_notifications",
        "app/controllers/tags_controller.rb", 438,
        inputs=[(439, 14332)],
        sinks=[("app/models/tag_user.rb", 134, 3767), ("app/models/tag_user.rb", 174, 5683)],
        flows_into=[],
    ),
    Expected(
        "C Admin::UsersController#penalty_history",
        "app/controllers/admin/users_controller.rb", 107,
        inputs=[(142, 4383)],
        sinks=[("app/controllers/admin/users_controller.rb", 128, 4024)],
        flows_into=[("app/controllers/admin/users_controller.rb", 128, 4024)],
    ),
]


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


def sink_key(sink: Location) -> tuple[str, int, int]:
    return (str(sink["filename"]), int(sink["lineStart"]), int(sink["colStart"]))


def check(kb_location: str, found: list[dict[str, typing.Any]], expected: Expected) -> list[str]:
    hits = [h for h in found if h["httpHandlerLocation"]["filename"] == expected.filename and h["httpHandlerLocation"]["lineStart"] == expected.line]
    if len(hits) != 1:
        return [f"{expected.name} : {len(hits)} handlers at {expected.filename}:{expected.line}, expected 1"]
    handler = hits[0]
    print(f"== {expected.name} : {handler['httpHandlerDef']}")
    errors: list[str] = []

    inputs: list[Location] = [i["contents"]["requestParamLocation"] for i in handler["httpHandlerUserInputs"] if i["tag"] == "RequestParamCtor"]
    got_inputs = sorted((i["lineStart"], i["colStart"]) for i in inputs)
    print(f"   user inputs ( params calls ) : {got_inputs}")
    if got_inputs != sorted(expected.inputs):
        errors.append(f"{expected.name} : user inputs {got_inputs}, expected {sorted(expected.inputs)}")

    reply = query(kb_location, "SelectControlFlowReachableSinks", {"from": handler["httpHandlerLocation"], "sinks": SINKS, "maxNumHops": 10, "maxNumSinks": 50})
    sinks: list[Location] = [m["location"] for m in reply["contents"]["matches"] if m.get("kind") == "SQL"]
    got_sinks = sorted(sink_key(s) for s in sinks)
    print(f"   control flow reachable sql sinks : {got_sinks}")
    errors += [f"{expected.name} : sql sink {sink} not reachable" for sink in expected.sinks if sink not in got_sinks]

    for sink in sinks:
        if sink_key(sink) in expected.sinks:
            errors += check_dataflow(kb_location, expected, inputs, sink)
    return errors


def check_dataflow(kb_location: str, expected: Expected, inputs: list[Location], sink: Location) -> list[str]:
    key = sink_key(sink)
    flows = False
    for user_input in inputs:
        path = query(kb_location, "SelectDataFlowPath", {"from": user_input, "to": sink, "maxNumIntraProceduralEdges": 50, "maxNumInterProceduralEdges": 10})["contents"]["path"]
        steps = "null" if path is None else f"{len(path)} steps : " + " -> ".join(f"{p['lineStart']}:{p['colStart']}" for p in path)
        print(f"   dataflow {user_input['lineStart']}:{user_input['colStart']} -> {key} : {steps}")
        flows = flows or path is not None
    if flows and key not in expected.flows_into:
        return [f"{expected.name} : unexpected dataflow into {key}"]
    if not flows and key in expected.flows_into:
        return [f"{expected.name} : no dataflow into {key}"]
    return []


def main() -> int:
    kb_location = sys.argv[1]
    found = handlers(kb_location)
    errors = [e for expected in EXPECTED for e in check(kb_location, found, expected)]
    for error in errors:
        print(f"FAIL: {error}")
    if errors:
        return 1
    print("OK : A, B ( control flow + user input, no dataflow ) and C ( dataflow into DB.exec )")
    return 0


if __name__ == "__main__":
    sys.exit(main())
