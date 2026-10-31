# status

Last updated: 2026-10-31

## the user flow under test

What a user runs, nothing else:

```powershell
docker compose --env-file .env -f compose/compose.base.yaml -f compose/compose.app.yaml -f compose/compose.fronts.yaml -f compose/compose.prebuilt.yaml -f compose/compose.workers.yaml -f compose/compose.agent.yaml up -d
python -m cli run --create_knowledge_base_from ../DSpace --ignore_testing_code true
python -m agent.loop --use_kb /tmp/kb_XXXXXXXX1-0.pl --max-items 5 -v
```

The images are parsers 1.1.49, codegen 1.0.44, kbgen 1.0.50 and queryengine 1.0.77.
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

## Weblate: random 5, source first, after the `try` fix ( 2026-10-31 ) : 1 `suspicious`, wrong

Fresh kb ( `/tmp/kb_XXXXXXXX1-51.pl` ), plain user flow, parsers + codegen from source ( same file calls + `try` fix ), kbgen 1.0.50, queryengine 1.0.77. 214 handlers.
Trace: `agent/.scan_traces/kb_XXXXXXXX1-51/20261031T141625Z-95750`.
3 of 5 ran an LLM session, 2 short circuited on 0 sinks. 4 `safe`, 1 `suspicious`.

| # | endpoint | kb sinks | agent | source |
|---|---|---|---|---|
| 1 | UNKNOWN `healthz/` `trans/views/basic.py:1166` | 0 | safe ( no LLM ) | right : `HttpResponse("ok")`. `@login_not_required` |
| 2 | UNKNOWN `remove-duplicate-units/<path>/` `trans/views/git.py:230` | `HttpResponseRedirect` `trans/util.py:259` | safe : no dataflow | right : `execute_locked` -> `redirect_param(obj, "#repository")`, internal url. `@login_required`, `has_perm("vcs.reset")` |
| 3 | UNKNOWN `access/<project>/unblock/` `trans/views/acl.py:338` | `redirect` `:349` | **suspicious** : dataflow request -> redirect, no sanitizer, pre_auth | **wrong** : `redirect("manage-access", project=obj.slug)`, the target is a route name ( reversed, same host ). The dataflow ends in the `project=` kwarg, not the target. `@login_required` |
| 4 | UNKNOWN `manage/alerts/` `wladmin/views.py:809` | 0 | safe ( no LLM ) | right : ORM + `render`. `@management_access` |
| 5 | POST `fonts/<project>/group/<pk>/` `fonts/views.py:187` | `redirect` `:208` `:226` `:237` `:241` | safe : no dataflow ( checked `:208`, `:241` ) | right : 3 x `redirect(self.object)` ( a model ) + `redirect("fonts", ...)`. `:208`, `:226` and `:237` are in `try` / `else` bodies, found thanks to the `try` fix. `has_perm("project.edit")` |

Agent : items 2, 4 ( no LLM ), 5 are sound ; item 5 checked dataflow for 2 of the 4 redirects only, harmless here.
Item 3 : the claim "user input flowing to that redirect argument" is wrong, it flows to a keyword arg ; but the agent only sees the path's locations, so given the kb it couldn't tell.

### the most important thing to improve

**A Django `redirect` whose target ( arg 0 ) is a constant string can't be an open redirect, but the sink still reports it.** The kb already says so for item 3 : `kb_arg_i_for_call( <"manage-access">, 0, Call )` + `kb_const_string( <"manage-access">, 'manage-access' )`, and the tainted `obj.slug` is `kb_keyword_arg_for_call( 'project', ... )`.
Weblate has 82 `redirect("<literal>", ...)` calls, most with `project=` / `path=` kwargs from a `parse_path` object, so each is one dataflow hit away from a `suspicious` like item 3.
Quick win, queryengine `sinks/open_redirects/python/django.pl` : drop calls whose arg 0 is a `kb_const_string` ( a route name, or a fixed url : either way not attacker controlled ). Covers this FP class only ; `redirect(obj)` ( the earlier 2 FPs ) still needs the db lookup work.

## Weblate: random 5, source first, after the same file call fix ( 2026-10-31 ) : 5 safe, `except` bodies missing

Fresh kb ( `/tmp/kb_XXXXXXXX1-21.pl` ), plain user flow, prebuilt parsers 1.1.48, kbgen 1.0.50, queryengine 1.0.77, codegen from source ( same file call fix, below ). 214 handlers.
Trace: `agent/.scan_traces/kb_XXXXXXXX1-21/20261031T134959Z-09593`.
3 of 5 ran an LLM session, 2 short circuited on 0 sinks. All 5 `safe`.

| # | endpoint | kb sinks | agent | source |
|---|---|---|---|---|
| 1 | UNKNOWN `labels/<project>/edit/<pk>/` `trans/views/labels.py:55` | `redirect` `:67` | safe : no dataflow from the request | right : `redirect("labels", project=project)`, a route name. `@login_required`, `has_perm("project.edit")` |
| 2 | UNKNOWN `cleanup/<path>/` `trans/views/git.py:203` | `redirect` `:142`, `HttpResponseRedirect` `trans/util.py:259` ( via `queue_operation`, a same file call : new edge ) | safe : no dataflow | right : `redirect(f"{reverse('show_progress', ...)}?info=1")` and `redirect_param(obj, "#repository")`, internal urls. kb wrong : `redirect` `:129` and `redirect_param` `:132` are in the `except` body, missing. `@login_required` |
| 3 | UNKNOWN `js/unit/<unit_id>/screenshots/` `screenshots/views.py:863` | 0 | safe ( no LLM ) | right : ORM + `JsonResponse` / `render`. `@login_required`, `has_perm("screenshot.edit")` |
| 4 | UNKNOWN `js/screenshot/<pk>/ocr/` `screenshots/views.py:792` | `os.replace` `:223` + `os.path.dirname` `:217` + `os.path.basename` `:218` as `FileOperationWrite` | safe : no dataflow to any of the 3 | right : `get_tesseract` -> `download_tesseract_data` writes the tessdata file to a server side path. Nit ( queryengine ) : the `os.replace` write sink is reported at its path arg `full_name`, and the template lists every call taking that arg, so `dirname` / `basename` show up as file writes ( the agent spent 2 queries on them ) |
| 5 | UNKNOWN `user/<user>/link/<link>/` `accounts/views.py:1116` | 0 | safe ( no LLM ) | verdict right, kb wrong : `redirect(page_profile.get_absolute_url())` `:1131` is in an `except ValidationError` body, missing. `@login_not_required` ( public ) |

Agent : all 3 sessions are sound, every claim is backed by a reply ( sinks + null `SelectDataFlowPath` ).
Same nits : each session re-ran `SelectControlFlowReachableSinks` ( = call 0 ), and reasons cite the `unauth: 214` base rate.

### the most important thing to improve

**`try` statements keep only the `try` body.** Two layers drop the rest :
- parsers `PyParser.y` `stmt_try` lowers to `StmtBlock $5` ( the body ) : `except` handlers, `else` and `finally` are gone ( `exception_handler` returns `Nothing` ).
- codegen `codeGenStmtTry = codeGenStmts . Ast.stmtTryPart` ( `CodeGen.hs:207` ) drops `stmtCatchPart` for every language ( Java and TS fill it ).

On Weblate ( non test, 1,011 `try` ) : 1,442 calls in `except`, 140 in `else`, 64 in `finally`, vs 1,378 in the `try` bodies, so more than half the calls under a `try` are missing. 31 of them are sinks ( `redirect` 23, `redirect_param` 5, `HttpResponseRedirect` 2, `open` 1 ), 2 in this five ( items 2 and 5 ).
Quick win : parsers, keep the handler bodies + `orelse` + `finalbody` in the block ; codegen, generate `stmtCatchPart` too ( a sequence is enough for reachability ).

Fix : codegen 1.0.44 generates the catch part after the try part ( all languages ). Parsers 1.1.49 : `stmtTry` -> `Ast.StmtTry`, `try` body as the try part, `except` bodies ++ `else` ++ `finally` as the catch part ( `Actions.stmtTry` ), so Python needs both. Happy : 0 conflicts before and after ( only actions + rule names changed, same accepted language ).
Fresh Weblate kb ( `/tmp/kb_XXXXXXXX1-51.pl` ) : `kb_called_from` 46,864 -> 48,168, 1st party file call edges 5,417 -> 5,689, 214 handlers. Of this five : `cleanup` now also reaches `redirect` `git.py:129`, `user/<user>/link/` reaches `redirect` `accounts/views.py:1131` ( was 0 sinks ), `ocr` gains `os.unlink` `:229` ( a `finally` ).

## Weblate: random 5, source first, after #131 ( 2026-10-31 ) : first `suspicious` verdicts, both wrong

Fresh kb ( `/tmp/kb_XXXXXXXX1-0.pl` ), plain user flow, prebuilt parsers 1.1.48, codegen 1.0.43, kbgen 1.0.50, queryengine 1.0.77. 214 handlers.
Trace: `agent/.scan_traces/kb_XXXXXXXX1-0/20261031T131738Z-68265`.
3 of 5 ran an LLM session ( 1st party call edges from #131 now reach sinks ), 2 short circuited on 0 sinks. 3 `safe`, 2 `suspicious`.

| # | endpoint | kb sinks | agent | source |
|---|---|---|---|---|
| 1 | POST `auth/tokens/webauthn/<pk>/` `accounts/views.py:2332` | 0 | safe ( no LLM ) | verdict right, kb wrong : `redirect_profile("#account")` `:2354` -> `HttpResponseRedirect(reverse("profile") + anchor)` `:381`, constant. The call resolves to `'Unknown'` ( see below ) |
| 2 | UNKNOWN `move/<path>/` `trans/views/settings.py:418` | `redirect` `:447`, `HttpResponseRedirect` `trans/util.py:259` | **suspicious** : dataflow request -> `redirect`, no sanitizer, pre_auth | **wrong** : `redirect(moved)` = `moved.get_absolute_url()`, a model ( `moved = form.save()` ) ; `redirect_param(obj, "#organize")` = `resolve_url(model) + constant`. `@login_required` + `has_perm("project.edit")` |
| 3 | UNKNOWN `manage/memory/upload/` `auth/decorators.py:48` | 0 | safe ( no LLM ) | kb wrong : the handler is `management_permission_required("memory.manage")( UploadView.as_view() )` ( `urls.py:640` ), the kb picked the decorator factory, not `UploadView`, and still calls it `pre_auth` |
| 4 | UNKNOWN `download/<path>/` `trans/views/files.py:163` | `redirect` `:200`, `open` + `FileResponse` `utils/views.py:910-912` | **suspicious** : open redirect + path traversal, request flows to both | **wrong** : `redirect(obj)` `:200` is a model ( `obj = parse_path(request, path, ...)` ) ; `open(filename)` reads `translation.filenames`, the component's files on disk, chosen by the db object, not by the request. `has_perm("translation.download", obj)` `:190` |
| 5 | UNKNOWN `manage/tools/` `wladmin/views.py:279` | `redirect` `:301` `:307` | safe : no dataflow from the request | right : 2 x `redirect("manage-tools")`, a route name. `@management_access` |

Agent : item 5 is sound. Items 2 and 4 reason "a dataflow path from the request object reaches the redirect, no sanitizer -> user controlled target".
Every kb reply is quoted correctly, but the conclusion doesn't follow : the path is request -> `parse_path` / `form.save()` -> **a model** -> `redirect(model)`.
The request picks *which* object, the url is the object's own `get_absolute_url()`, same host. Same for `open`. Both also lean on `pre_auth` ( kb has no Django auth, `move` is `@login_required` ).
Same nit as before : each session re-ran `SelectControlFlowReachableSinks` ( = call 0 ).

### the most important thing to improve

**False positives : taint through a db lookup.** Now that 1st party calls are linked ( #131 ), `request -> parse_path(request, path) -> obj -> redirect(obj)` is a dataflow path, and the agent ( which only sees locations, not code ) reads it as "the user controls the url".
Weblate has 70 `redirect(<name>)` calls ( vs 82 with a route name string ), most of them `redirect(obj)` after a `parse_path`, so on a full scan this pattern is the main source of `suspicious`.
Layer : kb ( the agent's claim is backed by the reply ; it can't tell a model from a string ). Direction, not decided : stop python taint at a model returned by a lookup ( `parse_path`, `get_object_or_404`, `.objects.get`, `form.save()` ), or let `redirect` / `open` sinks say what their argument is ( a model / a route name / a string ). Not a quick win.

Also found, kb, likely a quick win : **a call to a same file function placed after its `def` resolves to `'Unknown'`.** On this kb : 1,821 of 2,176 such call sites are `'Unknown'`, vs 2 of 206 when the call is placed before ( or inside ) the `def`.
Example : `redirect_profile` ( `accounts/views.py:377` ) is `'Unknown'` at `:504`, `:1275` and `:2354`. In `auth/permissions.py`, `check_permission` ( `:292` ) resolves at `:274` and `:344` but not at its 21 later call sites. Cause ( codegen ) : `codeGenStmtFunc` binds the name as `ActualType.Function`, and `toFqn` has no case for it, so every later call got `Fqn.Unknown` ; a call above the `def` missed the symbol table and kept a bare name, with no edge either.
Fix ( codegen 1.0.44 ) : a call on a `Function` emits `CallFuncFromImportedFile` with the def's file ( -> `kb_call_1st_party_func_defined_in_file`, like an imported 1st party function ), and top level `def`s are bound before any body ( hoisting ).
Fresh Weblate kb ( `/tmp/kb_XXXXXXXX1-21.pl` ) : 1st party file call edges 3,239 -> 5,417, `'Unknown'` calls 4,707 -> 2,724, same file calls after the `def` 1,821 `'Unknown'` -> 1, 214 handlers ( unchanged ). webauthn ( item 1 ) now reaches `HttpResponseRedirect` `accounts/views.py:381`. Left : 10 calls to nested `def`s.

## Weblate: random 5, source first, after `Invert` ( #128, 2026-10-30 ) : 213 endpoints

Fresh kb ( `/tmp/kb_XXXXXXXX11-15.pl` ), plain user flow, parsers built from source with `Invert` ( `~x` -> `<dhscanner-instrumentation>[invert](x)`, uncommitted, #128 ), queryengine 1.0.76.
`SelectHttpHandlers` : **213** handlers ( 29 Get, 28 Post, 156 Unknown ), was 205 : `trans/views/basic.py` now parses ( Weblate 610 -> 617 / 630 files, 0 regressions ).
Trace: `agent/.scan_traces/kb_XXXXXXXX11-15/20261030T130335Z-01609`.
1 of 5 ran an LLM session, 4 short circuited on 0 sinks. All 5 `safe`.

| # | endpoint | kb sinks | agent | source |
|---|---|---|---|---|
| 1 | UNKNOWN `download-list/<name>/` `trans/views/files.py:147` | 0 | safe ( no LLM ) | right : `download_multi` -> `zip_download` ( `utils/views.py:829` ) zips files from the db ( component paths, `allowed_roots` ), `format` only picks an exporter. ACL : `filter_access` + `has_perm("translation.download")` |
| 2 | UNKNOWN `watch/<path>/` `accounts/views.py:1643` | 0 | safe ( no LLM ) | verdict right, kb wrong : `redirect_next(request.GET.get("next"), ...)` `:1671` -> `HttpResponseRedirect(next_url)` `trans/util.py:364`, **tainted**, behind `url_has_allowed_host_and_scheme` + `startswith("/")` `:358-362`. `@login_required` `@require_POST` |
| 3 | UNKNOWN `languages/` `lang/views.py:34` | 0 | safe ( no LLM ) | right : ORM + `render`. Public |
| 4 | UNKNOWN `manage/discovery/register/` `wladmin/views.py:351` | `redirect` `:361` `:366` `:376` | safe : no dataflow from the request to any of the 3 | right : 2 x `redirect("manage")`, and `:376` = the weblate.org support url from settings + a `get_token` state. `@management_permission_required("management.configure")` |
| 5 | UNKNOWN `js/screenshot/<pk>/add/` `screenshots/views.py:844` | 0 | safe ( no LLM ) | right : ORM ( `ain_bulk`, `filter` ) + `JsonResponse`, POST ids cast to `int`. `@login_required`, `has_perm("screenshot.edit")` |

Agent ( item 4 ) : the verdict is right and every claim is backed by a reply ( 3 sinks, 3 null `SelectDataFlowPath` ).
Same 2 nits as before : call 1 re-ran `SelectControlFlowReachableSinks` ( = call 0 ), and the reason cites the digest base rate ( "unauth endpoints are common ( unauth: 213 )" ) as context for an admin-only endpoint the seed calls `pre_auth`.

### the most important thing to improve

**Still the python 1st-party module-function call edge ( same as the previous effort ), and now it hides a tainted sink.**
On item 2 the kb has `kb_call_resolved( <accounts/views.py:1671>, 'weblate.trans.util.redirect_next' )` and `kb_func_def( ..., 'redirect_next', 'weblate/trans/util.py', ... )`, but no `kb_call_1st_party_func_defined_in_file` between them ( 144 such facts in the whole kb ).
So the one endpoint in this five with request data flowing into a redirect ( the textbook open redirect, sanitized here ) settles as `safe` with no LLM, for the wrong reason, and the agent never gets to judge the sanitizer.
`redirect_next` is called from 13 sites with `request.GET.get("next")` ( `trans/views/edit.py`, `screenshots/views.py`, `legal/views.py`, `auth/views.py`, ... ). Quick win, queryengine : the `utils_control_flow_callable_calls_callable` clause from the previous effort.

### done: absolute 1st party imports resolve to the exact file ( [#131](https://github.com/OrenGitHub/dhscanner.runner/issues/131) )

Weblate imports its own modules with absolute paths ( ~3,900 `from weblate...` / `import weblate...` vs ~180 relative ), and those were all labeled 3rd party.
The python front ( `py/rewrite.py`, an `ast.NodeTransformer` ) now rewrites them into `from` imports of the exact file, using the scanned `.py` files and the top level class / function names per file ( sent by the native parser worker ) :

| source | rewritten | kb |
|---|---|---|
| `from weblate.trans.util import redirect_next` | ( parsers : level 0 `from` import of a scanned file is 1st party ) | `kb_call_1st_party_func_defined_in_file( <accounts/views.py:1671>, 'redirect_next', 'weblate/trans/util.py' )` |
| `path("hosting/", weblate.accounts.views.hosting)` | `path("hosting/", dhscanner_instrumented_hosting())` | the same fact, for `hosting` in `accounts/views.py` |
| `path("stats/", weblate.trans.views.about.StatsView.as_view())` | `class dhscanner_instrumented_StatsView_Subclass(dhscanner_instrumented_StatsView): pass` + `dhscanner_instrumented_StatsView_Subclass.as_view()` | `kb_call_method_of_class( Call, 'as_view', Sub )` + `kb_class_has_1st_party_super( Sub, 'StatsView', 'weblate/trans/views/about.py' )` -> `AboutView` -> django `TemplateView` |

Plus codegen ( a dotted call on a class name is a method of that class ), kbgen ( a 1st party super gets its imported name, not the alias ) and `django.pl` ( reads the two shapes above ).
On a fresh Weblate kb : 1st party file call edges 144 -> 3,085, `watch` reaches `redirect` / `HttpResponseRedirect` at `trans/util.py:363-364` ( was 0 sinks ), 214 handlers ( was 213 ; CI floor 200 ), 617 / 630 files parse ( 0 regressions ).
Open : 7 class based handlers found before are not found now ( 57 -> 50 ), not located yet.

## Weblate: random 5, source first, after the python sinks ( #129, 2026-10-30 ) : first LLM sessions

Fresh kb ( `/tmp/kb_XXXXXXXX11-0.pl` ), plain user flow, parsers with `Match` ( #128 ) and queryengine with the python sink catalogs ( #129 ), both from source.
Trace: `agent/.scan_traces/kb_XXXXXXXX11-0/20261030T113013Z-99484`.
2 of 5 ran an LLM session ( the first on Weblate ), 3 short circuited on 0 sinks. All 5 `safe`.

| # | endpoint | kb sinks | agent | source |
|---|---|---|---|---|
| 1 | POST `backups/<project>/` `trans/views/settings.py:711` | `redirect` `:716` | safe : no dataflow from the request | right : `redirect("backups", project=self.obj.slug)`, a named route. `@method_decorator(login_required)` |
| 2 | UNKNOWN `billing/<pk>/` `billing/views.py:349` | `redirect` `:359` | safe : no dataflow | right : `redirect(billing)`, the model's url. `@login_required` |
| 3 | POST `auth/tokens/webauthn/<pk>/` `accounts/views.py:2332` | 0 | safe ( no LLM ) | verdict right, kb wrong : `redirect_profile(...)` -> `HttpResponseRedirect` `:381`, not reached |
| 4 | UNKNOWN `matrix/<path>/` `trans/views/source.py:73` | 0 | safe ( no LLM ) | right : ORM + `render` only. `@login_required` |
| 5 | UNKNOWN `access/<project>/set/` `trans/views/acl.py:130` | 0 | safe ( no LLM ) | verdict right, kb wrong : `redirect_param(...)` -> `HttpResponseRedirect` `trans/util.py:259`, not reached |

Agent : both verdicts are correct, and grounded in kb evidence ( `SelectDataFlowPath` null ). The stronger reason ( the target is a route name / a model ) isn't in its vocabulary.
Each session spent 1 of its 5 queries re-running `SelectControlFlowReachableSinks`, which the loop had just run ( call 0 ).

### the most important thing to improve

**Python calls to 1st-party module functions have no call graph edge.** `acl.py` calls `weblate.trans.util.redirect_param` ( absolute import ), the kb has its `kb_func_def` in `weblate/trans/util.py`, but no `kb_call_1st_party_func_defined_in_file`, so `utils_control_flow_callable_calls_callable` never hops into it.
On this kb : 2,061 call sites resolve to `weblate.<module>.<func>` with a matching `kb_func_def` in that module file, vs 144 linked calls in the whole kb. Every helper ( `parse_path`, `redirect_param`, `messages.*` ) is a dead end, so reachability is mostly intra-file.
Quick win, queryengine : one more `utils_control_flow_callable_calls_callable` clause, a call resolved to `a.b.c.f` -> the `kb_func_def` of `f` in `a/b/c.py` ( or `a/b/c/__init__.py` ), the same 1st-party-by-module-file rule as `endpoints/python/django.pl`.

## Weblate: random 5, source first, after `Match` ( #128, 2026-10-30 ) : 205 endpoints, 0 sinks

Fresh kb ( `/tmp/kb_XXXXXXXX1-2.pl` ), plain user flow, parsers built from source with `Match` ( uncommitted, #128 ), codegen 1.0.42, kbgen 1.0.49, queryengine 1.0.75.
`SelectHttpHandlers` : **205** handlers ( 29 Get, 28 Post, 148 Unknown ), was 156 : `accounts/views.py` +38, `trans/views/edit.py` +11.
Trace: `agent/.scan_traces/kb_XXXXXXXX1-2/20261030T110628Z-74578`.
All 5 settled by the 0-sink short circuit ( `zero_sinks_verdict` ), no LLM session ran.

| # | endpoint | kb | source | auth ( source ) |
|---|---|---|---|---|
| 1 | GET `manage/integrations/` `vcs/views.py:468` | 0 sinks | ORM + `render` only | `@method_decorator(management_access)` |
| 2 | UNKNOWN `auto-translate/<path>/` `trans/views/edit.py:1517` ( new, `Match` ) | 0 sinks | `redirect(obj)` ( model url ) x4, ORM | `@login_required`, `@require_POST` |
| 3 | UNKNOWN `confirm/` `accounts/views.py:604` ( new ) | 0 sinks | `redirect("home")`, `redirect("social:complete", backend=session[...])` | `@login_not_required` ( really unauth ) |
| 4 | GET `changes/browse/<path>/` `trans/views/changes.py:137` | 0 sinks | `redirect("changes", path=<GET params>)` ( named url, reversed ) | none ( public, ACL via `filter_access` ) |
| 5 | UNKNOWN `costs/<path>/` `trans/views/reports.py:552` | 0 sinks | `redirect_param(...)`, ORM `Report.objects.create` | `@login_required`, `@require_POST` |

The verdicts match the source : none of the 5 reaches a tracked sink, every redirect target is a model url or a named route.
But the kb is right for the wrong reason : queryengine has no Django sinks at all ( Python = `requests.*` SSRF + tornado redirect ), so 4 of 5 endpoints have safe Django `redirect(...)` sinks the kb can't see, and every Weblate endpoint will short circuit to `safe` with no LLM.
Auth : the seed puts all 205 handlers in `pre_auth` ( `auth_pattern_distribution: unauth 205` ). 4 of the 5 are wrong : only `confirm/` is unauth. There are no Python auth predicates ( `predicates/auth` has `nodejs/` only ).

### the most important thing to improve

**A Django sink catalog in queryengine, starting with `django.shortcuts.redirect` / `HttpResponseRedirect` ( open redirect ).** It is the only sink in 4 of the 5 endpoints, and with 0 Python sinks the agent never runs on Weblate.
Then file reads / writes ( `open`, `FileResponse`, storage ) and raw SQL ( `cursor.execute`, `.raw`, `.extra` ).
Next after it : Django auth predicates ( `login_required`, `method_decorator(...)`, `login_not_required`, `management_access` ), so the seed stops calling every endpoint unauth.

## Weblate: random 5, after #124 ( 2026-10-29, evening ) : still 0 endpoints

Fresh kb through the plain user flow ( `/tmp/kb_XXXXXXXX1-0.pl`, 80MB vs 51MB before, 6 m 12 s ), parsers 1.1.44, same Weblate `0195e965e6`.
Trace: `agent/.scan_traces/kb_XXXXXXXX1-0/20261029T193558Z-43453`.

```
seeded 0 endpoints (A ∪ B surface)
items processed    : 0
```

The parser fix landed: `api/views.py` ( 549 kb lines ) and `trans/views/hooks.py` ( 60 ) are now in the kb, and 67 files fail to parse across the whole scan, down from 111.
`accounts/views.py` and `vcs/git.py` are still missing ( they fail on `Match` ).
The loop still seeds nothing, because the parser was never the blocker for seeding.

### the most important thing to improve

**queryengine has no Django / DRF handler recognizer.** `predicates/endpoints/api.pl:3-8` loads only tornado ( user input only, no handlers ), nextjs, express, echo, spring and servlet.
Weblate's views are in the kb now, but no rule turns them into endpoints, so the agent has nothing to sample.
Not a quick win: it needs a new `predicates/endpoints/python/django.pl` ( `path(...)` / DRF `router.register` -> view function / `ViewSet` methods ). Tracked in [#126](https://github.com/OrenGitHub/dhscanner.runner/issues/126).

**Found on the way, a quick win:** the `urls.py` facts gap ( next section ) is kbgen, not the parser. The module-level callable of `weblate/urls.py` is 5.3 MB of bitcode, and kbgen answers **413** : its Yesod instance ( `dhscanner.service.kbgen/src/Main.hs:39` ) keeps the default 2 MB `maximumContentLength`, while codegen raised its limit to 256 MB ( `dhscanner.service.codegen/src/Main.hs:48` ).
The kbgen worker logs it as `KBGEN_FAILED ... exception(s): no exceptions`, with no status. `weblate/settings_docker.py` is dropped the same way.

### done: Django endpoint recognizer, Weblate 0 -> 156 handlers ( [#126](https://github.com/OrenGitHub/dhscanner.runner/issues/126) )

queryengine `predicates/endpoints/python/django.pl` : `django.urls.path` / `re_path( Url, View )` -> the verb methods of a class-based view ( `X.as_view()`, the nearest definition up its 1st party supers ), or a function view ( verb `Unknown` ).
An absolute import reaches the kb by name, so a dotted module `a.b.c` is 1st party when the kb has a definition in `a/b/c.py` or `a/b/c/__init__.py`.
It needed one fix per layer :

| # | layer | fix |
|---|---|---|
| G0 | kbgen 1.0.49 | `maximumContentLength` 64 MB ( was the Yesod default 2 MB ) : the 5.3 MB module-level callable of `weblate/urls.py` got a 413, so the kb had 0 routes. The kbgen worker now logs the http status |
| G1 | parsers 1.1.45 | `import a.b.c` binds the root name `a`, like python ( it bound the whole dotted string, so `a.b.c.X` resolved to `Unknown.b.c.X` ) |
| G2 | parsers 1.1.45 | every class gets a `<dhscanner-instrumentation>[default-method]` method, so a class with no methods ( `class TermsView(LegalView): page = "terms"` ) still has a `kb_class_def` and its supers |
| G2b | codegen 1.0.42 + kbgen 1.0.49 | a class name binds in the enclosing scope, so a super class from the same file resolves ( 309 -> 2,470 `kb_class_has_1st_party_super` on Weblate ) |

Measured through the plain user flow : `SelectHttpHandlers` returns **156** handlers ( 24 Get, 21 Post, 111 Unknown ), now a CI floor ( `tests/kbapi/weblate_endpoints.py` ).
Left : `Match` statements ( `accounts/views.py`, `trans/views/edit.py`, `trans/views/basic.py` : ~61 routes ), `include(...)` url prefixes, DRF routers, views wrapped in `urls.py` ( `management_permission_required(view)` ), and class-based views that inherit every verb from django's generic views ( 30 classes ).
`compose/compose.services-dev.yaml` runs codegen / kbgen / queryengine from source, like `compose.parsers-dev.yaml` does for parsers.

## Weblate: random 5 ( 2026-10-29 ) : 0 endpoints

Fresh kb ( `/tmp/kb_XXXXXXXX1-1.pl`, 51MB, 4 m 17 s ), parsers 1.1.43, codegen 1.0.41, kbgen 1.0.48, queryengine 1.0.74, Weblate `0195e965e6` ( Django + DRF, ~450-500 routes ).
Trace: `agent/.scan_traces/kb_XXXXXXXX1-1/20261029T045055Z-40890`.

```
items processed    : 0
queue remaining    : 0
```

The loop drained with 0 items and exited 0, silently. There was nothing to sample, so this effort is about the layers under the agent.

| layer | what is missing | evidence |
|---|---|---|
| parsers | **111 `.py` files fail to parse** : 66% of the non-test source lines ( 122k of 186k ) are not in the kb | `compose-parsers-1` logs `Failed: Location {... colStart = N}`, an offset into the `ast.dump` text |
| queryengine | no Django / DRF handler recognizer. Python has only `endpoints/python/tornado.pl` ( user input, no handlers ) | `endpoints/api.pl:20-57` : handlers come from nextjs, spring, servlet only |
| queryengine | Python sinks are `requests.post` ( `sinks/ssrf/python/requests.pl` ) and tornado redirects only | |
| kb | `weblate/urls.py` parses, but has 0 facts after line 92 : none of the 251 `path(...)` in `real_patterns = [ ... ]` ( `:101` ). `api/urls.py` keeps its top-level `path` / `register` calls | cause not located yet |

The first node each failing file trips on ( one per file, so a file may hide more ):

| node | files | Python |
|---|---|---|
| `NamedExpr` ( `:=` ) | 48 | 3.8 |
| `YieldFrom` | 21 | 3.3 |
| `TypeAlias` | 16 | 3.12 |
| `Invert` ( `~` ) | 8 | |
| `TypeVar` ( PEP 695 `type_params` ) | 6 | 3.12 |
| `Match` | 6 | 3.10 |
| `Nonlocal` | 3 | |
| other | 3 | |

None of these are in `dhscanner.service.parsers/src/PyParser.y`.
It hits exactly the attack surface: `api/views.py`, `api/serializers.py`, `accounts/views.py`, `trans/views/edit.py`, `utils/requests.py` ( the outbound SSRF guard ) all stop at `NamedExpr`;
`trans/views/hooks.py` ( the unauth webhooks ) at `TypeAlias`, `vcs/git.py` at `Match`, `gitexport/views.py` at `YieldFrom`.

### the most important thing to improve

**The Python parser has no `NamedExpr` ( walrus, `:=` ).** It is the first failure in 48 of the 111 files, including the whole REST API ( `api/views.py`, 5.3k lines ).
Example: `accounts/views.py:1334` `if invitation_pk := request.session.get(...)`.
A Django recognizer comes after this : it can't find handlers in files that are not in the kb.

**Quick win:** yes. One expression rule in `PyParser.y` : `NamedExpr(target, value)` -> an assignment of `value` to `target`, used as an expression ( the value flows on ).
It goes through the parsers strict-progress gate ( `dhscanner.1.parsers/AGENTS.md` ), then a parsers release, then a fresh kb.
`YieldFrom` ( 21 ) and `TypeAlias` ( 16, can be dropped ) are the next two.

Also seen:

- 0 handlers is as silent as a missing kb ( rough edge 5 below ) : the loop should say "0 handlers seeded" and exit non-zero.
- `--ignore_testing_code true` keeps Django's `tests.py` files ( 21 in the kb, eg `wladmin/tests.py` ), and a 1st-party `weblate.trans.tests.test_models.BaseTestCase` super shows up as `kb_class_has_3rd_party_super`.
- [#111](https://github.com/OrenGitHub/dhscanner.runner/issues/111) again : 2 `invalid status response` polls during kbgen.

### done: Python parser coverage on Weblate, 83.2% -> 95.4% ( [#124](https://github.com/OrenGitHub/dhscanner.runner/issues/124) )

`dhscanner.service.parsers/py_agent_loop.py` : the Python sibling of `java_agent_loop.py` ( same strict-progress gate ), over Weblate's 630 production `.py` files ( tests and migrations excluded ).
It runs on the runner compose chain + `compose/compose.parsers-dev.yaml` ( `frontpy` on `:5006` ). Unlike Java, the LLM may edit `PyLexer.x` : every missing construct is a new node name, ie a new keyword.
`--target-node <Node>` picks only files failing on that node, `--baseline-only` prints coverage + the failing-node histogram.

| iteration | native node | lowered to | files progressed | coverage |
|---|---|---|---|---|
| baseline | | | | 524 / 630 ( 83.2% ) |
| 1 | `NamedExpr` ( `:=` ) | `Ast.ExpAssign` ( the LLM dropped the target, fixed by hand ) | 47 | 560 ( 88.9% ) |
| 2 | `YieldFrom` | its value expression | 25 | 584 ( 92.7% ) |
| 3 | `TypeAlias` | `Ast.StmtAssign` | 16 | 597 ( 94.8% ) |
| 4 | `TypeVar` ( PEP 695 `def f[T]` / `class C[T]` ) | dropped ( type only ) | 12 | **601 ( 95.4% )** |

0 Happy conflicts before and after. By lines it is lower : the remaining failures are big files.
Left : `Match` 9, `bound` ( `[T: Foo]` ) 8, `Invert` 8, `Nonlocal` 2, other 2.
Next : a fresh Weblate kb through the plain user flow, then the `urls.py` facts gap, then the Django / DRF recognizer.

## DSpace: random 5, source first, after #119 ( 2026-10-27, evening )

Fresh kb ( `/tmp/kb_XXXXXXXX1-0.pl`, 281MB ), parsers 1.1.42, kbgen 1.0.47, queryengine 1.0.74, DSpace `a5b0f0fc17`. 5 sessions, 7 kbapi calls.
Trace: `agent/.scan_traces/kb_XXXXXXXX1-0/20261027T190012Z-97687`.

| endpoint | the source | kb | verdict |
|---|---|---|---|
| `ReviewAction.execute` ( `:44` ) | request params only pick a `switch` case; the cases reach workflow DB writes ( `processAccept`, `super.processRejectPage`, `deleteWorkflowByWorkflowItem` ) | 0 sinks, **and 0 calls from the `switch` body** | safe ✔ |
| `WorkflowItemStepLinkRepository.getStep` ( `:59` ) | DB finds keyed by a typed `Integer` | 0 sinks | safe ✔ |
| `ExternalSourceItemUriListHandler.handle` ( `:48` ) | regex, then `UUID.fromString`, then `itemService.find` | 0 sinks | safe ✔ |
| `SubmissionService.findOriginalFile` ( `:535` ) | `replaceFile` param, then `UUID.fromString`, then `bitstreamService.find` | 0 sinks | safe ✔ |
| `AuthenticationRestController.shortLivedTokenResponse` ( `:210` ) | private helper of POST `/shortlivedtokens` ( `@PreAuthorize AUTHENTICATED`, `:207` ), mints a JWT | 0 sinks, bucket `pre_auth` | safe ✔ |

All 5 verdicts are right, given the kb and given the source. All 5 are `UNKNOWN {?}` helpers, not routes.
The agent still retries an empty sink query at 20 hops ( items 1, 4 ) and still cites base rates ( "unauth=424 vs PreAuthorize=143", "recent verdicts all safe" ).

### the most important thing to improve

**The Java parser drops every `switch` case body.** In `ReviewAction.execute` the kb has the calls at lines 47, 48 and 59, and nothing from lines 49-58:
`processAccept` ( `:50` ), `super.processRejectPage` ( `:52` ) and `processSubmitterIsDeletedPage` ( `:54` ) are not call sites in the kb, so nothing behind them can ever be reached.

The cause is in `dhscanner.service.parsers/src/JavaParser.y:1094` : `stmt_switch` keeps only the scrutinee ( `stmtExp $13` ), and every `switch_case` / `switch_case_child` returns `()`.
`exp_switch` ( `:815` ) does the same for switch expressions.
The TS parser already shows the fix : `stmtSwitch` ( `TsParser.y:743` ) lowers to an `Ast.StmtBlock` of all the case bodies, concatenated.

DSpace has 106 `switch` statements in 74 main-code files ( 15 arrow-style `case ... ->` ). Every call inside them is missing from the kb today: call edges, sinks, auth checks.

**Quick win:** yes. It is one grammar rule plus its actions. Keep `stmt_body` children ( and `exp` children of arrow cases, as `StmtExp` ), and build a `StmtBlock` like TS does.
It goes through the parsers strict-progress gate ( `dhscanner.1.parsers/AGENTS.md` ), then a parsers release, then a fresh kb.
( Deferred for now: looking for more fundamental flaws first. )

### a second five, same kb

Trace: `agent/.scan_traces/kb_XXXXXXXX1-0/20261027T191652Z-97640`. 5 sessions, 7 kbapi calls.

| endpoint | the source | kb | verdict |
|---|---|---|---|
| `DSpaceRestRepository.upload` ( `:418` ) | base method, only throws | 0 sinks | safe ✔ |
| GET `/workflowGroups/{workflowRole}` ( `CollectionGroupRestController.java:384` ) | `@PreAuthorize` READ + in-body ADMIN check ( `AuthorizeUtil.java:306` ); `workflowRole` checked against a role map ( `CollectionRestRepository.java:667` ); DB lookups through the Criteria API ( `CollectionRoleDAOImpl.java:60` ), which is not a catalog sink | 0 sinks, `@PreAuthorize` | safe ✔ |
| `SpecialGroupClaimProvider.getValue` ( `:49` ) | `getSpecialGroups` over the auth methods, no catalog sink | 0 sinks | safe ✔ |
| `OrcidLoginFilter.redirectAfterSuccess` ( `:129` ) | `sendRedirect(redirectUrl)` ( `:151` ) behind a host allow-list, `Strings.CI.equalsAny` ( `:149` ) | sink + dataflow + `TopLevelIfThenElse` sanitizer | safe ✔ |
| `JWTTokenRestAuthenticationServiceImpl.getWwwAuthenticateHeaderValue` ( `:195` ) | builds a header string, no sink | 0 sinks | safe ✔ |

All 5 are right, and this time the kb matches the source too ( given the catalog ).
`OrcidLoginFilter` is the first endpoint across all efforts that runs the whole pipeline: sink, then dataflow, then sanitizer, then a correct exact-host-match argument.

Across the 10 endpoints of this evening: 9 had 0 sinks, and the LLM only restated that ( ~25-30 s each ). The one with a sink is where the LLM did real work ( 58 s ).
8 of the 10 are not routes.

### done: 0 sinks -> no LLM session

The loop now asks the kb first ( `SelectControlFlowReachableSinks` from the handler, all 6 sink kinds, 10 hops ).
On 0 matches it records `safe` itself, with no LLM session. Otherwise the session runs as before.
In the trace that is kbapi call 0 plus a `zero_sinks_verdict` event ( instead of `llm_verdict` ), and the cli summary prints `0 sinks ( no LLM )`.

20 random DSpace endpoints, same kb: 20 settled with 0 sinks, 0 LLM sessions, 245 s ( ~12 s per item, vs 24-59 s before ).

**The next wall is the kb query itself:** every kbapi query takes ~10.5 s, in this run and in the LLM sessions before it,
while the query alone measured p50 0.04 s in the #119 bench.
567 handlers x ~12 s is still ~1.9 hours.

### next quick win ( not done yet ): compile the kb once, at upload

**The cause:** every kbapi query starts a fresh `swipl` process ( `Swipl.hs` `runSwiplWithTimeout` ), and every template opens with `:- [ '{KNOWLEDGE_BASE}' ]`.
So every query re-parses the whole 281MB `kb_XXX.pl` source ( ~846k facts ).

**Measured** inside the running queryengine container ( SWI-Prolog 9.0.4 ), current DSpace kb, loaded the way the templates load it:

| load | time | facts ( `kb_call_resolved` / `kb_called_from` ) |
|---|---|---|
| `kb.pl` ( today ) | **10.8 s** | 93477 / 92259 |
| `kb.qlf` ( compiled ) | **0.5 s** | 93477 / 92259 |
| `qcompile(kb)`, once | 13.5 s, a 77MB `.qlf` | |

~20x per query, same facts. The templates' `:- dynamic` declarations in front of the `.qlf` load still work.

**The fix**, in `dhscanner.service.queryengine`:

1. `postUploadkbR` ( `Main.hs:79` ): after writing `kb_XXX.pl`, run `swipl -g "qcompile('kb_XXX'), halt"` once ( +13.5 s per upload ).
2. `runJsonTemplate` ( `JsonTemplate.hs:33` ): fill `{KNOWLEDGE_BASE}` with `kb_XXX.qlf` when it exists, else the `.pl` ( so old kbs still work ).

**Expected:** a 0-sink item ~12 s -> ~1 s, every LLM session's kbapi call ~10 s cheaper, the seed query faster too.
A full DSpace pass ~1.9 h -> ~10 min.
Ship : queryengine push to `main` ( CI publishes the image ), runner compose bump, then a fresh kb + loop through the plain user flow to confirm.

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
