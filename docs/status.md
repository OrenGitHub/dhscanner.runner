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

One testing effort = 5 random endpoints, reviewed by a teacher ( a human or an external LLM ).

**No real vuln is needed to improve.** The unit of improvement is a kb fact: a sink ( even a safe one ), a sanitizer, an auth check, a call edge.
Those are everywhere, so every random endpoint tests the whole pipeline ( parsers -> kb -> kbapi -> agent ).

**Small on purpose.** 5 endpoints can be reviewed for real; following every path in a large codebase can't.
Progress comes from doing "fives" across many repos ( other languages, frameworks, sink idioms ), not from going exhaustive on one.

1. **Fresh kb, plain user flow** ( above ). Run the loop from PowerShell : Git Bash rewrites `/tmp/kb_...` into a Windows path, and a missing kb answers 0 matches silently.
2. **Randomize 5 endpoints:**
   ```powershell
   python -m agent.loop --use_kb /tmp/kb_XXXXXXXX1-0.pl --max-items 5 --use-random-endpoints-order
   ```
   Each run picks 5 new endpoints.
3. **Source first.** For each endpoint, read the source *before* the trace, and list what is reachable: sinks ( even safe ones ), the checks in front of them, and the auth.
   The trace can't show a sink the kb missed, so this step is the only way to catch one.
4. **Then diff against the trace** ( `agent/.scan_traces/<kb>/<timestamp>/trace.jsonl` ):
   - `item_popped` : what is on the desk ( verb, url, bucket, auth evidence, user inputs ).
   - `kbapi_call` / `kbapi_reply` : what the kb returned, vs the source list.
   - `llm_verdict` : is every claim backed by a reply, and is the verdict right *given the kb*?
5. **Blame the right layer.** The agent works on top of the kb, not the source:
   - kb missed it ( eg a safe open redirect ) -> a kb / parser issue, not an agent fault.
   - kb has it, the agent misjudged it ( eg missed the sanitizer ) -> an agent issue.
6. **Write down the ONE most important thing to improve**, with the endpoint and source lines, and whether it is a quick win.

## DSpace: random 5, source first ( 2026-10-27 )

Same kb as below ( `/tmp/kb_XXXXXXXX1-0.pl`, same images, same DSpace commit ). 5 sessions, 5 kbapi calls, 31-44 s each.
Trace: `agent/.scan_traces/kb_XXXXXXXX1-0/20261027T125230Z-35812`.

| endpoint | the source | kb | verdict |
|---|---|---|---|
| `OidcAuthentication.isUsed` ( `:79` ) | 2 null checks, no sink | 0 sinks | safe ✔ |
| GET `/viewevents/{uuid}` ( `StatisticsRestController.java:69` ) | only throws | 0 sinks | safe ✔ |
| `ExportEventProcessor` ctor ( `:70` ) | 2 field assignments | 0 sinks | safe ✔ |
| DELETE `/itemReadGroup` ( `CollectionGroupRestController.java:260` ) | DB read / delete / insert through Hibernate, all keyed by a typed `UUID`; `@PreAuthorize` WRITE, plus an in-body ADMIN check ( `AuthorizeUtil.java:553` ) | 0 sinks, `@PreAuthorize` only | safe ✔ |
| `RootRestRepository.getRoot` ( `:25` ) | one converter call, no sink | 0 sinks | safe ✔ |

All 5 verdicts are right, given the kb and given the source. 3 of 5 are again `UNKNOWN {?}` helpers, not routes.
The agent still cites base rates ( "unauth 424 vs PreAuthorize 143", "prior verdicts were safe" ) as context.

### the most important thing to improve

**The kb has no Java sinks except `sendRedirect`.** `predicates/sinks/` has Java only under `open_redirects/java/servlet.pl`.
There is no Java SQL, file or SSRF predicate, so on a Java repo `SelectControlFlowReachableSinks` can only ever return an open redirect.
"0 sinks" on DSpace says more about the catalog than about the endpoint.

The calls are already in the kb, resolved, and nothing classifies them:

| family | resolved call sites in the DSpace kb ( examples ) |
|---|---|
| file | `java.io.File` 198, `FileInputStream` 41, `FileOutputStream` 28, `FileReader` 21, `FileWriter` 19, `File.delete` 13 |
| SSRF | `HttpGet` 18, `CloseableHttpClient.execute` 11, `java.net.URL` 17, `java.net.http.HttpClient.send` 6 |
| SQL | `Unknown.createQuery` 27, `Unknown.getHibernateSession.createQuery` 8, `*.executeUpdate` 22, `*.createNativeQuery` 12 ( receivers often `Unknown.`, so match on the method suffix ) |

The endpoint that shows it is not in this sample, but sits one private call from a route:
unauth GET `/sitemaps/{name}` ( `SitemapRestController.java:70` ) opens `new FileInputStream(foundSitemapFile)` ( `:119` ).
It is safe: `name` only picks a file by `equalsIgnoreCase` against `sitemapOutputDir.listFiles()` ( `:80` ), an allow-list.
That is exactly the kb fact we want: a file read sink, plus the check in front of it. Today the kb sees neither.

**Quick win:** yes. Add `files/java`, `ssrf/java`, `db/java` next to `open_redirects/java/servlet.pl`, one fqn list each.
It needs no call-graph work: the sitemap read is a direct private call.
It comes before the base class -> subclass dispatch fix below: dispatch only pays off once there are Java sinks to reach.
( Related: the DSpace kb has 0 `kb_class_has_1st_party_super` facts, which that fix will need. )

## DSpace: random 5 + 5 + lexicographic 5 ( 2026-10-27 )

queryengine 1.0.73, 567 seeded handlers, 15 sessions, 22 kbapi calls.

| run | endpoints | verdicts |
|---|---|---|
| random #1 | `AutoAssignAction`, `CollectionMappedItemLinkRepository`, `ItemTypeProcessor`, `DSpaceSamlAuthRequest`, `OidcAuthentication` | 5 safe |
| random #2 | `JWTTokenRestAuthenticationServiceImpl`, `ItemAddBundleController` ( POST ), `Util`, `IPAuthentication`, `RestResourceController` ( GET ) | 5 safe |
| lexicographic | `RestResourceController` DELETE x3, `CommunityAdminGroupRestController`, `ItemTemplateRestController` | 5 safe |

Every verdict rests on one fact: `SelectControlFlowReachableSinks` from the handler returned 0.

### the most important thing to improve

**Nothing in the agent: it reasons correctly on top of the kb.** The agent works on the kb, not on the source, so 0 sinks in the kb rightly means `safe`.

The one thing worth fixing is in the kb: virtual dispatch through the generic REST controller.
`DELETE /api/{apiCategory}/{model}/{uuid}` ( `RestResourceController.java:1120` ) shows it:

1. `deleteInternal` picks the repository by name at runtime : `utils.getResourceRepository(apiCategory, model)`, ie `getBean(apiCategory + "." + modelPlural)` ( `Utils.java:283` ).
2. `DSpaceRestRepository.deleteById` ( line 194 ) calls `getThisRepository().delete(context, id)`, effectively `this.delete` through the spring proxy. The static target is the base `delete` ( line 217 ), which only throws.
3. The real work and the real auth are in the overrides, eg `@PreAuthorize("hasPermission(#id, 'ITEM', 'DELETE')")` in `ItemRestRepository.java:151`.

The kb stops at step 2, so these handlers look `pre_auth` with 0 sinks.
Expanding step 2 to every override ( base class -> subclass, the sibling of G3 in `docs/DSpace.md` ) is the fix. It is not a quick win.

Smaller, already listed below: the prompt still cites earlier verdicts and base rates as evidence, and 7 of the 10 random picks are `UNKNOWN {?}` helper methods, not routes.

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
