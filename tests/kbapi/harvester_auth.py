"""Assert spring's ``@PreAuthorize`` puts DSpace's harvester endpoints in the authenticated bucket.

Runs against the one-file agent-mode KB of
``CollectionHarvestSettingsController.java`` ( dspace-10.1 ). Stdlib only,
so CI can pipe it into any container on the compose network::

    docker compose ... exec -T app python - <kb_location> < tests/kbapi/harvester_auth.py

Both handlers carry ``@PreAuthorize("hasPermission(#collectionUuid,
'COLLECTION', 'WRITE')")`` ( runner issue #113 ), so ``SelectHttpHandlers``
returns them for ``Authenticated`` only, with the annotation as evidence.
"""

from __future__ import annotations

import json
import sys
import typing
import urllib.request

KBAPI_URL = "http://queryengine:3000/api"
FILENAME = "dspace-server-webapp/src/main/java/org/dspace/app/rest/CollectionHarvestSettingsController.java"
PRE_AUTHORIZE = "org.springframework.security.access.prepost.PreAuthorize"
EXPRESSION = "hasPermission(#collectionUuid, 'COLLECTION', 'WRITE')"


def location(line_start: int, col_start: int, line_end: int, col_end: int) -> dict[str, typing.Any]:
    return {
        "filename": FILENAME,
        "lineStart": line_start,
        "colStart": col_start,
        "lineEnd": line_end,
        "colEnd": col_end,
    }


class Handler(typing.NamedTuple):
    name: str
    verb: str
    location: dict[str, typing.Any]
    annotation: dict[str, typing.Any]


HANDLERS = [
    Handler("get", "Get", location(73, 5, 90, 6), location(73, 5, 73, 75)),
    Handler("updateHarvestSettingsEndpoint", "Put", location(100, 5, 125, 6), location(100, 5, 100, 75)),
]


def handlers(kb_location: str, authentication: str) -> list[dict[str, typing.Any]]:
    request = urllib.request.Request(
        f"{KBAPI_URL}?kb_location={kb_location}",
        data=json.dumps({"tag": "SelectHttpHandlers", "contents": {
            "verbs": ["Get", "Post", "Put", "Delete", "Patch", "Unknown"],
            "authentications": [authentication],
            "routeContainsUrlParts": None,
            "maxNumHttpHandlers": 50,
        }}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        reply: dict[str, typing.Any] = json.load(response)
    print(f"== SelectHttpHandlers [{authentication}]")
    print(json.dumps(reply, indent=2))
    matches: list[dict[str, typing.Any]] = reply["contents"]["matches"]
    return matches


def check_authenticated(kb_location: str) -> list[str]:
    found = handlers(kb_location, "Authenticated")
    failures = []
    for expected in HANDLERS:
        handler = next((h for h in found if h["httpHandlerLocation"] == expected.location), None)
        if handler is None:
            failures.append(f"Authenticated: no handler {expected.name} at :{expected.location['lineStart']}")
            continue
        if handler["httpHandlerVerb"] != expected.verb:
            failures.append(f"Authenticated: {expected.name} is not a {expected.verb}")
        annotation = {
            "securityAnnotationFqn": PRE_AUTHORIZE,
            "securityAnnotationLocation": expected.annotation,
            "securityAnnotationConstStrArgs": [EXPRESSION],
        }
        auth = {
            "authenticationFunctionName": "PreAuthorize",
            "authenticationEvidence": {"tag": "ByAnnotations", "contents": [annotation]},
        }
        if handler["httpHandlerAuth"] != auth:
            failures.append(f"Authenticated: {expected.name} auth is not the :{expected.annotation['lineStart']} @PreAuthorize")
    return failures


def check_not_unauthenticated(kb_location: str) -> list[str]:
    if handlers(kb_location, "Unauthenticated"):
        return ["Unauthenticated: a @PreAuthorize handler came back as pre auth"]
    return []


def main() -> int:
    kb_location = sys.argv[1]
    failures = check_authenticated(kb_location) + check_not_unauthenticated(kb_location)
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: both harvester handlers are authenticated by their @PreAuthorize")
    return 0


if __name__ == "__main__":
    sys.exit(main())
