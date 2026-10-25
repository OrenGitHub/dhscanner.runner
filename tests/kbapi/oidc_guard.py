"""Assert the kbapi replies the agent needs to clear DSpace's guarded OIDC open redirect.

Runs against the one-file agent-mode KB of ``OidcRestController.java``
( dspace-10.1 ). Stdlib only, so CI can pipe it into any container on the
compose network::

    docker compose ... exec -T app python - <kb_location> < tests/kbapi/oidc_guard.py

The queries walk the same path the agent takes on ``GET /api/authn/oidc``
( runner issue #105 ): the seeder's handler query ( #107 ) -> reachable
open-redirect sink -> dataflow from the user input into the sink -> the
top level if-then-else guarding the sink, with the error response in its
else part.
"""

from __future__ import annotations

import json
import sys
import typing
import urllib.request

KBAPI_URL = "http://queryengine:3000/api"
FILENAME = "dspace-server-webapp/src/main/java/org/dspace/app/rest/OidcRestController.java"


def location(line_start: int, col_start: int, line_end: int, col_end: int) -> dict[str, typing.Any]:
    return {
        "filename": FILENAME,
        "lineStart": line_start,
        "colStart": col_start,
        "lineEnd": line_end,
        "colEnd": col_end,
    }


HANDLER = location(52, 5, 80, 6)
USER_INPUT = location(54, 13, 54, 85)
SINK = location(71, 13, 71, 47)
CONDITION = location(69, 13, 69, 92)
HOST_NAME = location(60, 35, 60, 65)
HOST_NAME_VAR = location(60, 9, 60, 66)
LOG_DEBUG = location(70, 13, 70, 61)
LOG_ERROR = location(73, 13, 75, 33)
ERROR_RESPONSE = location(76, 13, 77, 89)
ERROR_MESSAGE = "Invalid redirectURL! Must match server or ui hostname."


def query(kb_location: str, tag: str, contents: dict[str, typing.Any]) -> dict[str, typing.Any]:
    request = urllib.request.Request(
        f"{KBAPI_URL}?kb_location={kb_location}",
        data=json.dumps({"tag": tag, "contents": contents}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        reply: dict[str, typing.Any] = json.load(response)
    print(f"== {tag}")
    print(json.dumps(reply, indent=2))
    return reply["contents"]


def check_endpoint(kb_location: str) -> list[str]:
    # The handler declares its verb as `@RequestMapping(method =
    # RequestMethod.GET)` ( :52 ). The url is not checked : its class level
    # prefix concatenates `AuthnRest.CATEGORY`, a constant from another
    # file, so it comes back as '{?}'.
    reply = query(kb_location, "SelectHttpHandlers", {
        "verbs": ["Get"],
        "authentications": ["Unauthenticated", "Authenticated"],
        "routeContainsUrlParts": None,
        "maxNumHttpHandlers": 50,
    })
    user_input = {
        "tag": "RequestParamCtor",
        "contents": {"requestParamName": "redirectUrl", "requestParamLocation": USER_INPUT},
    }
    for handler in reply["matches"]:
        if handler["httpHandlerLocation"] != HANDLER:
            continue
        failures = []
        if handler["httpHandlerVerb"] != "Get":
            failures.append("SelectHttpHandlers: oidc handler at :52 is not a GET")
        if handler["httpHandlerDef"] != {"tag": "MethodOfClass", "contents": ["oidc", "OidcRestController"]}:
            failures.append("SelectHttpHandlers: handler at :52 is not OidcRestController.oidc")
        if handler["httpHandlerUserInputs"] != [user_input]:
            failures.append("SelectHttpHandlers: user inputs of :52 are not exactly redirectUrl at :54")
        return failures
    return ["SelectHttpHandlers: no GET handler at :52 ( RequestMethod.GET unresolved? )"]


def check_sink(kb_location: str) -> list[str]:
    reply = query(kb_location, "SelectControlFlowReachableSinks", {
        "from": HANDLER,
        "sinks": ["OpenRedirect"],
        "maxNumHops": 10,
        "maxNumSinks": 50,
    })
    expected = {
        "location": SINK,
        "qualifiedName": "jakarta.servlet.http.HttpServletResponse.sendRedirect",
        "kind": "OpenRedirect",
    }
    if expected not in reply["matches"]:
        return ["SelectControlFlowReachableSinks: no sendRedirect match at :71:13-:71:47"]
    return []


def check_dataflow(kb_location: str) -> list[str]:
    reply = query(kb_location, "SelectDataFlowPath", {
        "from": USER_INPUT,
        "to": SINK,
        "maxNumIntraProceduralEdges": 10,
        "maxNumInterProceduralEdges": 1,
    })
    path = reply["path"]
    if not path or path[0] != USER_INPUT or path[-1] != SINK:
        return ["SelectDataFlowPath: no path from :54 to :71"]
    return []


def sanitizers(kb_location: str, user_input: dict[str, typing.Any]) -> list[dict[str, typing.Any]]:
    reply = query(kb_location, "SelectSanitizers", {
        "userInput": user_input,
        "sink": SINK,
        "maxNumSanitizers": 10,
    })
    found: list[dict[str, typing.Any]] = reply["matches"]
    return found


def check_sanitizer(kb_location: str) -> list[str]:
    found = sanitizers(kb_location, USER_INPUT)
    if len(found) != 1 or found[0]["tag"] != "TopLevelIfThenElse":
        return ["SelectSanitizers: expected exactly one TopLevelIfThenElse"]
    gadget = found[0]["contents"]
    failures = []
    cond = {"location": CONDITION, "qualifiedName": "org.apache.commons.lang3.Strings.CI.equalsAny", "constStringArgs": []}
    if gadget["cond"] != cond:
        failures.append("SelectSanitizers: cond is not the :69 Strings.CI.equalsAny call")
    if gadget["userInputArgIndex"] != 0:
        failures.append("SelectSanitizers: redirectUrl does not reach arg 0 of the :69 condition")
    flow = [
        {"flowStepLocation": USER_INPUT, "flowStepQualifiedName": None},
        {"flowStepLocation": HOST_NAME, "flowStepQualifiedName": "org.dspace.core.Utils.getHostName"},
        {"flowStepLocation": HOST_NAME_VAR, "flowStepQualifiedName": None},
    ]
    if gadget["userInputFlow"] != flow:
        failures.append("SelectSanitizers: user input flow is not :54 -> :60 getHostName -> redirectHostName")
    if [call["location"] for call in gadget["thenPart"]] != [LOG_DEBUG, SINK]:
        failures.append("SelectSanitizers: then part is not exactly the :70 log.debug + :71 sendRedirect")
    error = {
        "location": ERROR_RESPONSE,
        "qualifiedName": "jakarta.servlet.http.HttpServletResponse.sendError",
        "constStringArgs": [ERROR_MESSAGE],
    }
    if [call["location"] for call in gadget["elsePart"]] != [LOG_ERROR, ERROR_RESPONSE] or error not in gadget["elsePart"]:
        failures.append("SelectSanitizers: else part is not exactly the :73-75 log.error + :76-77 sendError + message")
    return failures


def check_no_sanitizer_without_flow(kb_location: str) -> list[str]:
    # The sink itself does not flow into the :69 condition, so no gadget
    # matches it as the "user input".
    if sanitizers(kb_location, SINK):
        return ["SelectSanitizers: gadget reported for an input that does not reach the condition"]
    return []


def main() -> int:
    kb_location = sys.argv[1]
    failures = (
        check_endpoint(kb_location)
        + check_sink(kb_location)
        + check_dataflow(kb_location)
        + check_sanitizer(kb_location)
        + check_no_sanitizer_without_flow(kb_location)
    )
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: endpoint, sink, dataflow and sanitizer replies all match")
    return 0


if __name__ == "__main__":
    sys.exit(main())
