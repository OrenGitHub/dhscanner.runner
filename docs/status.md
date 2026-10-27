# status

Last updated: 2026-10-27

## the user flow under test

What a user runs, nothing else:

```powershell
docker compose --env-file .env -f compose/compose.base.yaml -f compose/compose.app.yaml -f compose/compose.fronts.yaml -f compose/compose.prebuilt.yaml -f compose/compose.workers.yaml -f compose/compose.agent.yaml up -d
python -m cli run --create_knowledge_base_from ../DSpace --ignore_testing_code true
python -m agent.loop --use_kb /tmp/kb_XXXXXXXX1-0.pl --max-items 5 -v
```

The images are parsers 1.1.41, codegen 1.0.40, kbgen 1.0.47 and queryengine 1.0.73.
The `.env` at the repo root is the only source of config.

## a testing effort

One testing effort = one sample of the agent's judgment, read by a human:

1. **Fresh kb, plain user flow** ( above ). Run the loop from PowerShell : Git Bash rewrites `/tmp/kb_...` into a Windows path, and a missing kb answers 0 matches silently.
2. **Randomize 5 endpoints:**
   ```powershell
   python -m agent.loop --use_kb /tmp/kb_XXXXXXXX1-0.pl --max-items 5 --use-random-endpoints-order
   ```
   Each run picks 5 new endpoints. Run it twice ( 10 endpoints ), plus once without the flag as the lexicographic baseline.
3. **Inspect the reasoning** in `agent/.scan_traces/<kb>/<timestamp>/trace.jsonl`, per endpoint:
   - `item_popped` : what is on the desk ( verb, url, bucket, auth evidence, user inputs ).
   - `kbapi_call` / `kbapi_reply` : which queries, and what came back.
   - `llm_verdict` : is every claim in `reason_for_verdict` backed by a reply? Check the doubtful ones against the source.
4. **Write down the ONE most important thing to improve**, with the endpoint and the source lines that show it.

## DSpace: random 5 + 5 + lexicographic 5 ( 2026-10-27 )

queryengine 1.0.73, 567 seeded handlers, 15 sessions, 22 kbapi calls.

| run | endpoints | verdicts |
|---|---|---|
| random #1 | `AutoAssignAction`, `CollectionMappedItemLinkRepository`, `ItemTypeProcessor`, `DSpaceSamlAuthRequest`, `OidcAuthentication` | 5 safe |
| random #2 | `JWTTokenRestAuthenticationServiceImpl`, `ItemAddBundleController` ( POST ), `Util`, `IPAuthentication`, `RestResourceController` ( GET ) | 5 safe |
| lexicographic | `RestResourceController` DELETE x3, `CommunityAdminGroupRestController`, `ItemTemplateRestController` | 5 safe |

Every verdict rests on one fact: `SelectControlFlowReachableSinks` from the handler returned 0.

### the most important thing to improve

**"The kb sees nothing" becomes "safe".** The agent can't tell *no sink* from *the kb's call graph stops here*.

`DELETE /api/{apiCategory}/{model}/{uuid}` ( `RestResourceController.java:1120` ) shows it:

- the handler calls `deleteInternal`, which picks the repository by name at runtime : `utils.getResourceRepository(apiCategory, model).deleteById(id)`.
- the real work, and the real auth ( eg `@PreAuthorize("hasPermission(#id, 'ITEM', 'DELETE')")` in `ItemRestRepository.java:151` ), sit behind that call.
- the kb sees neither, so the handler is `pre_auth` with 0 sinks, and the agent wrote "pre_auth alone is not anomalous ... safe" three times.

What to do: `safe` needs evidence that the call graph from the handler is *closed*.
Give the agent a kbapi query for the unresolved calls reachable from a handler ( call sites with no `kb_call_resolved` target ), and make "0 sinks + unresolved calls" an `inconclusive` that names the call site, not a `safe`.

Smaller, and already listed below : the prompt still cites earlier verdicts and base rates as evidence, and 7 of the 10 random picks are `UNKNOWN {?}` helper methods, not routes.

## DSpace: first 5 agent loop iterations ( 2026-10-26 )

The KB is 277MB. The seed query returns 567 handlers: 454 UNKNOWN, 56 GET, 28 POST, 13 DELETE, 11 PUT and 5 PATCH.
All 567 are `pre_auth`.

| # | endpoint | kbapi calls | time | verdict |
|---|---|---|---|---|
| 1 | GET `/api/{apiCategory}/{model}/search` | 2 | 54 s | safe + 1 enqueue |
| 2 | GET `.../search/{searchMethodName}` | 3 | 76 s | safe |
| 3 | GET `{?}/search/facets` | 3 | 65 s | safe |
| 4 | GET `/iiif/{id}/canvas/{cid}` | 3 | 66 s | safe |
| 5 | GET `{?}/status` | 1 | 23 s | safe |

The verdicts match the source: none of the 5 reaches a tracked sink.
The `SelectControlFlowReachableSinks` replies are trustworthy. From `OidcLoginFilter.java:72` it does return the `sendRedirect` OpenRedirect sink.

### what is good

- Every session opens with `SelectControlFlowReachableSinks` from the exact `handler_location`, over all 6 sink kinds.
- It runs no dataflow / sanitizer queries when there is no sink.

### what to fix

1. **Prompt ( a must )**
   - Don't re-run an empty sink query with more hops: 7 of the 12 queries were 10 → 20 / 25 → 50 retries.
   - Don't re-query your own handler with `SelectHttpHandlers`.
   - Never cite earlier verdicts or base rates as evidence ( "recent verdicts all safe" ).
   - Say "no tracked sink reachable", not "no dataflow", when no dataflow query was run.
   - Enqueue only capability-passing pair-edges ( signed urls, oauth state, email tokens ), not hyperlinks ( item 1 used `hateoas_link` ).
2. **Loop:** set the provenance `parent` from the parent's real endpoint id, never from the LLM. Item 1 wrote `...:1013-1030`, which matches no endpoint id.
3. **Running time:** ~57 s per item means ~9 hours for 567 items. That is unacceptable.
4. **Seed order ( important ):** only 2 of the first 40 seeded handlers reach any sink at all ( #20 `IdentifierRestRepository /find`, #30 `OidcRestController` ).
   - Put sink-reaching handlers first, and record zero-sink handlers without an LLM session.
   - Also see [#112](https://github.com/OrenGitHub/dhscanner.runner/issues/112).
5. **Missing kb is silent:** a nonexistent `kb_location` answers every query with 0 matches, so the loop "drains" with 0 items and exits 0.

## KB creation timing ( full DSpace, 3171 files )

| stage | time |
|---|---|
| upload + native parsing | ~2.5 min |
| parsers | ~45 s |
| codegen ( 3024 ASTs ) | 75 s |
| kbgen ( ~21.6k requests ) | ~5 m 50 s |
| queryengine ( write the 344MB of facts as the KB ) | ~2 m 15 s |
| **total** | **~12.7 min** |

`-rtsopts -with-rtsopts=-N` on codegen / kbgen made **no difference**: 84 s vs 75 s and 5 m 50 s vs 5 m 49 s.
The Python workers are the bottleneck:

- `codegen_worker` sits at ~100% ( one core ).
- In kbgen, neither the service nor `kbgen_worker` fills a single core.

## fixed in this round

- `python -m cli` and `python -m agent.loop` load the repo-root `.env`, and its values win over stale shell exports. A missing `APPROVED_URL_0` / `APPROVED_BEARER_TOKEN_0` is now an error, not a silent exit 0.
- `--create_knowledge_base_from <dir>` is the default flow ( kb only ). `--scan_dirname` ( sarif ) is soon deprecated, and `--with_agent` is removed.
- The cli retries a dropped status poll instead of crashing the scan.
- queryengine 1.0.71 raises the `/uploadkb` limit to 512MB, because DSpace's facts are ~344MB and 1.0.70 answered 413.
- The README is shorter.

## open issues

- [#111](https://github.com/OrenGitHub/dhscanner.runner/issues/111) invalid status response during kbgen
- [#112](https://github.com/OrenGitHub/dhscanner.runner/issues/112) deterministic + random seeds ( fixed by [#117](https://github.com/OrenGitHub/dhscanner.runner/pull/117) )
- [#113](https://github.com/OrenGitHub/dhscanner.runner/issues/113) authenticated spring endpoints
- [#114](https://github.com/OrenGitHub/dhscanner.runner/issues/114) research: cut kb creation time

## known rough edges ( no issue yet )

- On a cp1252 Windows console, logging prints `UnicodeEncodeError` tracebacks for 😊 / `∪`. They are harmless.
- The queryengine agent mode job reports `Finished` even when `/uploadkb` failed. The cli then only warns at step 6.
- A worker that hits a missing job file exits, and nothing restarts it.
- The cli stops polling silently after 200 × 5 s ( ~17 min ).
