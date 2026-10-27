"""Assert the kbapi replies the agent needs on DSpace's login filters.

Runs against the agent-mode KB of ``OidcLoginFilter.java``,
``OrcidLoginFilter.java`` and ``ShibbolethLoginFilter.java``
( dspace-10.1 ). Stdlib only, so CI can pipe it into any container on the
compose network::

    docker compose ... exec -T app python - <kb_location> < tests/kbapi/login_filters_guard.py

Each filter's ``redirectAfterSuccess`` copies the OIDC controller's guard
( ``tests/kbapi/oidc_guard.py`` ) : ``request.getParameter("redirectUrl")``
is user input ( queryengine ``endpoints_user_input_servlet/1`` ), its
host goes through ``Utils.getHostName`` into ``Strings.CI.equalsAny``,
``sendRedirect`` sits in the then part and ``sendError`` in the else part.

``redirectAfterSuccess`` itself is a handler with verb ``Unknown``
( queryengine ``endpoints_http_servlet/2`` ) : it takes the
``HttpServletRequest request``, while the filter's verb and url are
registered elsewhere.
"""

from __future__ import annotations

import json
import sys
import typing
import urllib.request

KBAPI_URL = "http://queryengine:3000/api"
DIRNAME = "dspace-server-webapp/src/main/java/org/dspace/app/rest/security"
ERROR_MESSAGE = "Invalid redirectURL! Must match server or ui hostname."


def location(filename: str, line_start: int, col_start: int, line_end: int, col_end: int) -> dict[str, typing.Any]:
    return {
        "filename": f"{DIRNAME}/{filename}",
        "lineStart": line_start,
        "colStart": col_start,
        "lineEnd": line_end,
        "colEnd": col_end,
    }


# filename -> ( user input, condition, sink ) start lines
FILTERS = {
    "OidcLoginFilter.java": (74, 92, 94),
    "OrcidLoginFilter.java": (131, 149, 151),
    "ShibbolethLoginFilter.java": (113, 130, 132),
}

# filename -> `redirectAfterSuccess( HttpServletRequest request, ... )` span
HANDLERS = {
    "OidcLoginFilter.java": (72, 100),
    "OrcidLoginFilter.java": (129, 158),
    "ShibbolethLoginFilter.java": (111, 139),
}


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


def check_handlers(kb_location: str) -> list[str]:
    # A method taking `HttpServletRequest request` is a handler with verb
    # `Unknown` and url '{?}' : the filters' verb and url are registered
    # in another file ( WebSecurityConfiguration.java ). Its user inputs
    # are the request's getParameter calls.
    reply = query(kb_location, "SelectHttpHandlers", {
        "verbs": ["Unknown"],
        "authentications": ["Unauthenticated", "Authenticated"],
        "routeContainsUrlParts": None,
        "maxNumHttpHandlers": 100,
        "orderEndpointsLexicographically": True,
    })
    failures = []
    for filename, (line_start, line_end) in HANDLERS.items():
        handler = location(filename, line_start, 5, line_end, 6)
        user_input = {
            "tag": "RequestParamCtor",
            "contents": {
                "requestParamName": "redirectUrl",
                "requestParamLocation": location(filename, FILTERS[filename][0], 30, FILTERS[filename][0], 65),
            },
        }
        matches = [m for m in reply["matches"] if m["httpHandlerLocation"] == handler]
        if len(matches) != 1:
            failures.append(f"SelectHttpHandlers: no single Unknown handler at {filename}:{line_start}")
            continue
        match = matches[0]
        class_name = filename.removesuffix(".java")
        if match["httpHandlerDef"] != {"tag": "MethodOfClass", "contents": ["redirectAfterSuccess", class_name]}:
            failures.append(f"SelectHttpHandlers: {filename}:{line_start} is not {class_name}.redirectAfterSuccess")
        if match["httpHandlerVerb"] != "Unknown" or match["httpHandlerUrl"] != "{?}":
            failures.append(f"SelectHttpHandlers: {filename}:{line_start} is not Unknown '{{?}}'")
        if match["httpHandlerUserInputs"] != [user_input]:
            failures.append(f"SelectHttpHandlers: user inputs of {filename}:{line_start} are not exactly redirectUrl")
    return failures


def check_filter(kb_location: str, filename: str, lines: tuple[int, int, int]) -> list[str]:
    user_input_line, cond_line, sink_line = lines
    user_input = location(filename, user_input_line, 30, user_input_line, 65)
    cond = location(filename, cond_line, 13, cond_line, 92)
    sink = location(filename, sink_line, 13, sink_line, 47)
    found = query(kb_location, "SelectSanitizers", {
        "userInput": user_input,
        "sink": sink,
        "maxNumSanitizers": 10,
    })["matches"]
    if len(found) != 1 or found[0]["tag"] != "TopLevelIfThenElse":
        return [f"{filename}: expected exactly one TopLevelIfThenElse"]
    gadget = found[0]["contents"]
    failures = []
    expected_cond = {"location": cond, "qualifiedName": "org.apache.commons.lang3.Strings.CI.equalsAny", "constStringArgs": []}
    if gadget["cond"] != expected_cond:
        failures.append(f"{filename}: cond is not the :{cond_line} Strings.CI.equalsAny call")
    if gadget["userInputArgIndex"] != 0:
        failures.append(f"{filename}: redirectUrl does not reach arg 0 of the :{cond_line} condition")
    flow = gadget["userInputFlow"]
    if not flow or flow[0]["flowStepLocation"] != user_input:
        failures.append(f"{filename}: user input flow does not start at the :{user_input_line} getParameter")
    if "org.dspace.core.Utils.getHostName" not in [step["flowStepQualifiedName"] for step in flow]:
        failures.append(f"{filename}: user input flow does not go through Utils.getHostName")
    if sink not in [call["location"] for call in gadget["thenPart"]]:
        failures.append(f"{filename}: then part does not hold the :{sink_line} sendRedirect")
    errors = [
        call for call in gadget["elsePart"]
        if call["qualifiedName"] == "jakarta.servlet.http.HttpServletResponse.sendError"
        and call["constStringArgs"] == [ERROR_MESSAGE]
    ]
    if len(errors) != 1:
        failures.append(f"{filename}: else part does not hold exactly one sendError + message")
    return failures


def main() -> int:
    kb_location = sys.argv[1]
    failures = check_handlers(kb_location)
    for filename, lines in FILTERS.items():
        failures += check_filter(kb_location, filename, lines)
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print(f"PASS: SelectHttpHandlers + SelectSanitizers on all {len(FILTERS)} login filters")
    return 0


if __name__ == "__main__":
    sys.exit(main())
