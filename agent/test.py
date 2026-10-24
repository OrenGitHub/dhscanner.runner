from __future__ import annotations

import sys
import json
import http
import typing
import logging

import requests

try:
    from cli.argparse_wrapper import ExploreWithAgentArgparse as Argparse
except ModuleNotFoundError as exc:
    if exc.name in ('cli', 'cli.argparse_wrapper'):
        raise SystemExit(
            'cli.argparse_wrapper is not importable. Run from repo root with '
            '`python -m agent.test --use_kb ... --save_sarif_to ...`'
        ) from exc
    raise

QUERYENGINE_API_URL: typing.Final[str] = 'http://localhost:3000/api'

CONST_STRINGS_QUERY: typing.Final[dict[str, typing.Any]] = {
    'tag': 'SelectConstStrings',
    'contents': {
        'matchingRegex': '.*',
        'maxNumConstStrings': 7,
    },
}

HTTP_HANDLERS_QUERY: typing.Final[dict[str, typing.Any]] = {
    'tag': 'SelectHttpHandlers',
    'contents': {
        'verbs': ['Get', 'Post'],
        'authentications': ['Unauthenticated', 'Authenticated'],
        'routeContainsUrlParts': None,
        'maxNumHttpHandlers': 5,
    },
}

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s]: %(message)s',
    datefmt='%d/%m/%Y ( %H:%M:%S )',
    stream=sys.stdout,
)


def valid_response(response_json: dict[str, typing.Any], expected_tag: str, location_field: str) -> bool:
    if response_json.get('tag') != expected_tag:
        logging.error('unexpected tag in response: %s', response_json.get('tag'))
        return False

    contents = response_json.get('contents')
    if not isinstance(contents, dict):
        logging.error('response contents is missing or invalid')
        return False

    total = contents.get('total')
    matches = contents.get('matches')

    if not isinstance(total, int):
        logging.error('invalid total: %s', total)
        return False
    if not isinstance(matches, list):
        logging.error('invalid matches: %s', matches)
        return False

    for i, match in enumerate(matches, start=1):
        if not isinstance(match, dict) or not is_valid_location(match.get(location_field)):
            logging.error('match #%s has an invalid %s', i, location_field)
            return False

    return True


def log_const_strings_preview(response_json: dict[str, typing.Any], preview_limit: int = 10) -> None:
    contents = response_json['contents']
    total = contents['total']
    matches = contents['matches']

    logging.info('[ test ] regex used: %s', CONST_STRINGS_QUERY['contents']['matchingRegex'])
    logging.info('[ test ] total matched strings: %s', total)

    if not matches:
        logging.info('[ test ] no constant strings matched')
        return

    logging.info('[ test ] showing first %s matches:', min(preview_limit, len(matches)))
    for i, match in enumerate(matches[:preview_limit], start=1):
        logging.info('  #%s value=%s file=%s', i, match['value'], match['location']['filename'])


def log_http_handlers_preview(response_json: dict[str, typing.Any], preview_limit: int = 10) -> None:
    contents = response_json['contents']
    total = contents['total']
    matches = contents['matches']

    logging.info('[ test ] total http handlers: %s', total)

    if not matches:
        logging.info('[ test ] no http handlers matched')
        return

    logging.info('[ test ] showing first %s matches:', min(preview_limit, len(matches)))
    for i, match in enumerate(matches[:preview_limit], start=1):
        logging.info('  #%s %s %s', i, match.get('httpHandlerVerb'), match.get('httpHandlerUrl'))
        logging.info('%s', format_location(match['httpHandlerLocation'], indent='      '))


def is_valid_location(location: typing.Any) -> bool:
    if not isinstance(location, dict):
        return False

    required_keys = ['filename', 'lineStart', 'lineEnd', 'colStart', 'colEnd']
    for key in required_keys:
        if key not in location:
            return False

    if not isinstance(location['filename'], str):
        return False

    if not all(isinstance(location[key], int) for key in required_keys[1:]):
        return False

    return True


def format_location(location: typing.Any, indent: str = '') -> str:
    if not is_valid_location(location):
        return f'{indent}<invalid location>'

    lines = [
        f"lineStart={location['lineStart']}",
        f"colStart={location['colStart']}",
        f"lineEnd={location['lineEnd']}",
        f"colEnd={location['colEnd']}",
        f"filename={location['filename']}",
    ]
    return '\n'.join(f'{indent}{line}' for line in lines)


def run_query(kb_filename: str, query: dict[str, typing.Any]) -> typing.Optional[dict[str, typing.Any]]:
    params = {'kb_location': kb_filename}

    try:
        with requests.post(
            QUERYENGINE_API_URL,
            params=params,
            json=query,
            timeout=30,
        ) as response:
            if response.status_code != http.HTTPStatus.OK:
                logging.error('query api failed with status %s', response.status_code)
                return None
            return response.json()
    except requests.exceptions.RequestException as exc:
        logging.error('query api call failed: %s', exc)
        logging.error(
            'make sure queryengine is running and host port 3000 is exposed '
            '(e.g. compose queryengine service has ports: ["3000:3000"])'
        )
    except json.JSONDecodeError:
        logging.error('query api returned invalid json')

    return None


def main(parsed_args: Argparse) -> int:
    logging.info('[ test ] sending SelectConstStrings query')
    if not (const_strings_response := run_query(parsed_args.use_kb, CONST_STRINGS_QUERY)):
        return 1

    if not valid_response(const_strings_response, 'FoundConstStringsMatching', 'location'):
        return 1

    log_const_strings_preview(const_strings_response)

    logging.info('[ test ] sending SelectHttpHandlers query')
    if not (http_handlers_response := run_query(parsed_args.use_kb, HTTP_HANDLERS_QUERY)):
        return 1

    if not valid_response(http_handlers_response, 'FoundHttpHandlers', 'httpHandlerLocation'):
        return 1

    log_http_handlers_preview(http_handlers_response)

    with parsed_args.save_sarif_to.open('w', encoding='utf-8') as fl:
        json.dump(
            {
                'constStrings': const_strings_response,
                'httpHandlers': http_handlers_response,
            },
            fl,
        )

    logging.info('[ test ] responses are valid and saved to %s', parsed_args.save_sarif_to)
    return 0


if __name__ == '__main__':
    if args := Argparse.run():
        raise SystemExit(main(args))
