[![pylint](https://github.com/OrenGitHub/dhscanner.vps/actions/workflows/pylint.yaml/badge.svg)](https://github.com/OrenGitHub/dhscanner.vps/actions/workflows/pylint.yaml)
[![mypy](https://github.com/OrenGitHub/dhscanner.vps/actions/workflows/mypy.yaml/badge.svg)](https://github.com/OrenGitHub/dhscanner.vps/actions/workflows/mypy.yaml)
[![tests](https://github.com/OrenGitHub/dhscanner.vps/actions/workflows/tests.yaml/badge.svg)](https://github.com/OrenGitHub/dhscanner.vps/actions/workflows/tests.yaml)

## dhscanner.vps

optimized backend for dhscanner

## install

```bash
$ git clone --recurse-submodules https://github.com/OrenGitHub/dhscanner.vps.git
$ cd dhscanner.vps
$ cp .env.example .env    # fill in the values
$ pip install -r requirements.txt

# about 3 min. on a modern laptop
$ docker compose --env-file .env \
    -f compose/compose.base.yaml -f compose/compose.app.yaml \
    -f compose/compose.fronts.yaml -f compose/compose.prebuilt.yaml \
    -f compose/compose.workers.yaml -f compose/compose.agent.yaml \
    up -d
```

`.env` at the repo root is the single source of config: every command
below loads it, and its values win over variables already exported in
your shell.

## create a knowledge base + run the agent loop

```bash
$ python -m cli run --create_knowledge_base_from repo/to/scan --ignore_testing_code true
# ... [ step 6 ] kb filename: kb_XXXXXXXX1-0.pl

$ python -m agent.loop --use_kb kb_XXXXXXXX1-0.pl --max-items 5 -v
```

One fresh LLM session per http handler of the scanned repo, each querying
the kb and returning a verdict ( `safe` / `suspicious` / `defer` /
`inconclusive` ). The full trace lands under
`agent/.scan_traces/<kb>/<timestamp>/trace.jsonl`. See
`python -m agent.loop --help` for the budgets.

## scan with the built-in queries ( soon deprecated )

```bash
$ python -m cli run --scan_dirname repo/to/scan --ignore_testing_code true --save_sarif_to out.json
```

## manage jobs

```bash
$ python -m cli manage --get-all-job-ids
$ python -m cli manage --clear-job-id <job_id>
$ python -m cli manage --clear-all
```

## launch-local-app

Asks an OpenAI model to inspect a target repo, build it from source with
docker, launch it on localhost and probe a healthcheck, feeding failures
back for up to `--max-iterations` attempts:

```bash
$ python -m cli launch-local-app ../phpbb             # --dry-run, --teardown-on-exit, --model
```

Per-iteration plans, logs and probe results land under
`agent/.launch_logs/<target>/<timestamp>/iter-NN/`.
