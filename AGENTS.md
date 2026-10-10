# AGENTS

This is the top-level `dhscanner.vps` repo (the optimized backend / orchestration
layer for dhscanner). Most of the actual language-handling code lives in the
`dhscanner` git submodule and, transitively, in its own submodules.

## Grammar / parser-coverage work

For anything related to **improving parser coverage** (adjusting `.y` grammar
files, smart constructors in `TsParserActions.hs`, the per-iteration
regression / strict-progress gate, the agent-driven `agent_loop.py` workflow,
etc.) the canonical guide is **not** this file — it is the `AGENTS.md` shipped
inside the parsers submodule:

- [`dhscanner/dhscanner.1.parsers/AGENTS.md`](dhscanner/dhscanner.1.parsers/AGENTS.md)

That document owns:

1. The coverage goal and the regression-repo methodology.
2. The "one rule adjustment at a time" iteration contract and the strict
   progress gate (every previously-passing file still passes; every previously
   failing file now passes or fails at a strictly greater column; at least
   one file strictly progresses).
3. Guardrails (`cabal build` succeeds, Happy reports no new shift/reduce or
   reduce/reduce conflicts vs the previous baseline).
4. The active cleanup conventions inside `TsParser.y` /
   `TsParserActions.hs` (camelCase = handled, snake_case = TODO; one-line
   mapping comment; reusable list/option helpers; etc.).
5. The mapping from native TS nodes to the normalized **dhscanner.ast**
   (direct vs instrumented rules, and the `<dhscanner-instrumentation>[<tag>]`
   callee-name convention routed through `Actions.instrumentationCall`).

The companion **stand-alone dev stack** for this work also lives in that
submodule (`dhscanner/dhscanner.1.parsers/compose.yaml`). It is intentionally
separate from the prebuilt stack used by this repo's `compose/compose.*.yaml`
files: it builds parsers from source and binds host ports `4000` / `4001` so
it can coexist with the prebuilt vps stack on the same machine. The
agent-driven loop (`dhscanner/dhscanner.1.parsers/agent_loop.py`) drives that
stack — it performs `docker compose stop parsers` / `build parsers` /
`up -d parsers` / `/healthcheck` per iteration on its own; you only do the
one-time bring-up by hand:

```powershell
cd dhscanner/dhscanner.1.parsers
$env:OPENAI_API_KEY = 'sk-...'
docker compose up -d --build
python agent_loop.py
```

**Do not** duplicate the parser-coverage rules here — edit them in the
submodule's `AGENTS.md` so they stay co-located with the grammar they govern.

## Push / release discipline across submodules

The repos under this umbrella publish on different cadences and the chat
workflow has to respect each one — picking the wrong one will either break
downstream CI or leave the diff impossible to review cleanly.

- **Services** (`dhscanner.service.*`, e.g. `queryengine`, `parsers`,
  `fronts`, `codegen`, `kbgen`) — **push straight to `main`, no PRs.**
  Each repo's `.github/workflows/build.yaml` auto-bumps the `VERSION`
  patch, builds + strips the binary, and pushes
  `orenishdocker/dhscanner-<service>:<new-version>-x64` to Dockerhub.
  The Dockerhub secrets are wired only to the main-branch job, so a PR
  wouldn't publish anything useful anyway.

- **Packages** (Hackage libraries: `dhscanner.kbapi`, `dhscanner.ast`,
  `dhscanner.bitcode`, `dhscanner.kbgen`) — also no PRs, but the push to
  `main` has to be **ordered carefully**. The correct sequence per
  version bump is:
  1. Commit the change locally (bump the `.cabal` `version:` field in
     the same commit, _not_ the top-level `VERSION` file — that one is
     owned by CI).
  2. **Review the change before uploading.** The right diff to look at
     is "everything since the last Hackage-published commit", scoped to
     the files a library consumer actually sees (`src/` + the `.cabal`
     file). Hackage-release commits by convention have a subject
     starting with `bump X.Y.Z -> X.Y.W` (the manual cabal `version:`
     bump), vs. CI's `:arrow_up: Bump version: ...` which only touches
     the `VERSION` file + regenerated schemas. So the general command is:
     ```powershell
     git fetch origin main
     $prev = git log --grep='^bump ' --format=%H -1
     git diff $prev..origin/main -- src dhscanner-kbapi.cabal
     ```
     Avoid `git show HEAD` as a review command — once the schema CI
     (`.github/workflows/schema.yml`) tacks on its own `VERSION` bump
     and regenerated `query.schema.json` / `query_result.schema.json`
     commit, `HEAD` is CI's commit, not yours.
  3. `cabal sdist` and then `cabal upload --publish
     dist-newstyle/sdist/dhscanner-<pkg>-<ver>.tar.gz` to Hackage.
     This step is **manual on purpose** — Hackage credentials aren't in
     CI — and it must happen _before_ the next step.
  4. _Only now_ push the local commit to `origin main`.
  5. `git pull` once the schema CI finishes so the local tree reflects
     the regenerated schema + the CI's `VERSION` bump.

  Pushing before the Hackage upload is a repeat mistake worth guarding
  against: downstream services pin `dhscanner-<pkg> >= <new-ver>` in
  their `.cabal`, and their next CI build (triggered by any push on
  their own repo) will fail at `cabal update` because the new version
  isn't on Hackage yet.

- **`dhscanner.core`** — umbrella repo of service submodules. Also
  **push straight to `main`**. It only ever carries submodule-pointer
  bumps and has no CI publication step.

- **`dhscanner.runner`** (this repo) — **normal PR workflow.** This is
  the only repo in the umbrella that goes through code review.

## Everything else

For changes that are genuinely top-level (the FastAPI app under
`dhscanner.infra/app/`, the
CLI in `cli/`, the workers, the coordinator, the compose files under
`compose/`, etc.) there is currently no extra agent contract beyond the
project's normal lint / type-check / test CI:

- `pylint` (see `.github/workflows/pylint.yaml`)
- `mypy` (see `.github/workflows/mypy.yaml`)
- `tests` (see `.github/workflows/tests.yaml`)

If a sub-area grows its own per-iteration discipline (the way the parsers
submodule has), prefer adding an `AGENTS.md` next to that code and linking
it from here, rather than expanding this file.
