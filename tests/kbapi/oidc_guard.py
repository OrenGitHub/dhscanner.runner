"""Assert the kbapi replies the agent needs to clear DSpace's guarded OIDC open redirect.

Runs against the one-file agent-mode KB of ``OidcRestController.java``
( dspace-10.1 ). Stdlib only, so CI can pipe it into any container on the
compose network::

    docker compose ... exec -T app python - <kb_location> < tests/kbapi/oidc_guard.py

The four queries walk the same path the agent takes on
``GET /api/authn/oidc`` ( runner issue #105 ): handler -> reachable
open-redirect sink -> user input -> dataflow into the sink -> the ``if``
guarding the sink, with the error response on its other branch.
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


def check_sink(kb_location: str) -> list[str]:
    reply = query(kb_location, "ControlFlowReachableOpenRedirectSink", {
        "controlFlowReachableOpenRedirectSinkFrom": HANDLER,
        "controlFlowReachableOpenRedirectSinkLimitNumHops": 10,
        "controlFlowReachableOpenRedirectSinkLimit": 50,
    })
    expected = {
        "foundControlFlowReachableOpenRedirectSinkMatchLocation": SINK,
        "foundControlFlowReachableOpenRedirectSinkMatchQualifiedName":
            "jakarta.servlet.http.HttpServletResponse.sendRedirect",
    }
    if expected not in reply["foundControlFlowReachableOpenRedirectSinkMatches"]:
        return ["ControlFlowReachableOpenRedirectSink: no sendRedirect match at :71:13-:71:47"]
    return []


def check_user_inputs(kb_location: str) -> list[str]:
    reply = query(kb_location, "HandlerUserInputs", {
        "handlerUserInputsHandler": HANDLER,
        "handlerUserInputsLimit": 50,
    })
    expected = {"foundHandlerUserInputLocation": USER_INPUT, "foundHandlerUserInputName": "redirectUrl"}
    if expected not in reply["foundHandlerUserInputsMatches"]:
        return ["HandlerUserInputs: no redirectUrl at :54:13-:54:85"]
    return []


def check_dataflow(kb_location: str) -> list[str]:
    reply = query(kb_location, "DataFlowPath", {
        "dataFlowPathFrom": USER_INPUT,
        "dataFlowPathTo": SINK,
        "dataFlowPathLimitLength": 10,
    })
    path = reply["foundDataFlowPathPath"]
    if not path or path[0] != USER_INPUT or path[-1] != SINK:
        return ["DataFlowPath: no path from :54 to :71"]
    return []


def check_guard(kb_location: str) -> list[str]:
    reply = query(kb_location, "BranchGuardedCall", {
        "branchGuardedCallCall": SINK,
        "branchGuardedCallLimit": 10,
    })
    for guard in reply["foundBranchGuardedCallGuards"]:
        if guard["branchGuardConditionLocation"] != CONDITION:
            continue
        if guard["branchGuardConditionQualifiedName"] != "org.apache.commons.lang3.Strings.CI.equalsAny":
            return ["BranchGuardedCall: :69 condition does not resolve to Strings.CI.equalsAny"]
        expected = {
            "branchCallLocation": ERROR_RESPONSE,
            "branchCallQualifiedName": "jakarta.servlet.http.HttpServletResponse.sendError",
            "branchCallConstStringArgs": [ERROR_MESSAGE],
        }
        if expected not in guard["branchGuardOtherBranchCalls"]:
            return ["BranchGuardedCall: no sendError + error message on the other branch"]
        return []
    return ["BranchGuardedCall: no guard at :69"]


def main() -> int:
    kb_location = sys.argv[1]
    failures = (
        check_sink(kb_location)
        + check_user_inputs(kb_location)
        + check_dataflow(kb_location)
        + check_guard(kb_location)
    )
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: sink, user input, dataflow and branch guard replies all match")
    return 0


if __name__ == "__main__":
    sys.exit(main())
