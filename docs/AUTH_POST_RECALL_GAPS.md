# Auth-POST Recall Gaps — Follow-up Plan

**Status:** planning doc. No code changes yet. Written at the end of the OWASP-IL 2026
"first-query" exploration session so the next agent session can pick up the fixes
without re-deriving the analysis.

**Parent context:** `docs/OWASP26_NOTES.md` (talk-prep + direction). Specifically
this doc backs slide 15 (Tier 2a — Auth) and the "how do we even start / 2×2
grid" bridge between Tier 1 and Tier 2.

---

## 1. Live baseline (fresh KB, kbapi 1.0.7, queryengine rebuilt from source)

Fresh `--with_agent` scan of the `formbricks/` checkout at the current HEAD;
KB persisted inside the queryengine container at `/tmp/kb_XXXXXXXX11-0.pl`;
2×2 grid fired via `query_grid.py` (untracked helper in the repo root, see
"Reproduction" below).

| Bucket | Returned |
|---|---:|
| `UnauthenticatedHttpGetHandlerRequestObject`  | 9 |
| `AuthenticatedHttpGetHandlerRequestObject`    | 0 |
| `UnauthenticatedHttpPostHandlerRequestObject` | 2 |
| `AuthenticatedHttpPostHandlerRequestObject`   | 1 |

The single auth-POST match:

```json
{
  "url": "apps/web/app/api/v1/management/storage/local",
  "authenticatingFunctionName": "checkAuth",
  "authEvidence": { "tag": "ByAllButOneBadReturn" }
}
```

---

## 2. Ground truth — POST handlers in formbricks `apps/web`

Enumerated via `Select-String -Pattern "^export\s+(const|async\s+function|function)\s+POST\b" -List`
over every `route.ts`, then classified by grep for
`checkAuth|authenticatedApiClient|hasPermission|getServerSession|authOptions|…`.

| Bucket | Ground truth | KB found | Recall | Precision |
|---|---:|---:|---:|---:|
| Pre-auth POST (all)                          | 14 | 2 | 14 % | 100 % |
| Pre-auth POST (top-priority subset — client) | 6  | 2 | 33 % | 100 % |
| **Auth POST**                                | **14** | **1** | **7 %** | **100 %** |

Auth-POST breakdown by mechanism (ground truth):

| Mechanism | Count | Endpoints |
|---|---:|---|
| `checkAuth` (plain function, K-1 bad-return shape) | 2 | `api/v1/management/storage/local` **← KB found**, `api/v1/management/storage` |
| `hasPermission` (permission check, boolean-return) | 5 | `api/v1/management/{action-classes, responses, surveys}`, `api/v1/webhooks`, `ee/contacts/api/v1/management/contact-attribute-keys` |
| `authenticatedApiClient` (HOC wrapper)             | 7 | all `modules/api/v2/**/management/**` + `modules/api/v2/organizations/[organizationId]/{project-teams, teams, users}` + `modules/ee/contacts/api/v2/management/contacts` |

---

## 3. Root causes of the 13 misses

| # | Root cause | Count | Where it lives |
|---|---|---:|---|
| 1 | **HOC-wrapper pattern** — `export const POST = async (request) => authenticatedApiClient({ handler: async ({...}) => {...} })`. The exported `POST` isn't a plain handler; it's a function whose body is a call to a higher-order wrapper. The actual auth check lives inside the wrapper, and the actual handler is the arrow function passed *into* the wrapper. Our predicates neither unwrap the HOC nor treat `authenticatedApiClient` itself as an authenticator. | **7** | `dhscanner.core/dhscanner.service.queryengine/utils.pl` — new leaf clause needed |
| 2 | **Auth-function name catalog gap** — `hasPermission` isn't in `utils_authenticating_function_name/1`, and it returns a boolean (not the K-1-bad-return shape), so neither `ByHeaderNullCheck` nor `ByAllButOneBadReturn` fires on it. | **5** | `utils.pl` — one-line tier-1 catalog addition + possibly a new evidence variant `ByPermissionCheckBoolean` if boolean-return functions deserve their own tag |
| 3 | **Handler param name gap** (`request` vs `req`) — same class of miss as the pre-auth side. Uses `checkAuth` (which IS recognized), but the handler itself fails the name gate at `utils_http_post_handler_request_object_nextjs/3` line 89. | **1** | `utils.pl` — drop `kb_param_has_name(_, 'req')` gate; type gate alone (once relaxed) is sufficient |

---

## 4. Fix path (ordered by impact)

Each fix is a **leaf addition** — one new predicate clause or one catalog entry.
No existing clause is rewritten; no existing consumer needs to change.

| Rank | Fix | File / line | Est. recall bump on auth POST |
|---:|---|---|---:|
| 1 | **HOC-unwrap clause** — recognize `authenticatedApiClient({handler: F})` pattern; treat `authenticatedApiClient` as an authenticator via a new `AuthEvidence` variant (candidate name: `ByHocWrapper(WrapperName)`) so the LLM agent knows the recognition path | `utils.pl` — new clause for `utils_authenticating_function/3`; `dhscanner-kbapi/src/Content.hs` — new `AuthEvidence` constructor; queryengine `parseEvidenceTerm` — new branch | 1/14 → 8/14 |
| 2 | **Add `hasPermission` to the tier-1 name catalog** (plus possibly a new `ByPermissionCheckBoolean` evidence variant if we want to distinguish permission-checks from full auth-checks — semantically they're authz, not authn) | `utils.pl` line 233: `utils_authenticating_function_name('hasPermission').` | 8/14 → 13/14 |
| 3 | **Drop the handler name gate** — replace `kb_param_has_name(RequestObject, 'req')` with subtype-aware type gate `utils_is_request_like_type(RequestObject)` that admits both `next/server.NextRequest` and standard-Web `Request` (they're in a subtype relationship: `NextRequest extends Request`) | `utils.pl` lines 89-90 | 13/14 → 14/14 |

Same fix #3 also recovers ~5 pre-auth POST endpoints on the other side of the
grid (the `displays`, `responses`, `contacts/user` handlers that use
`request: Request` instead of `req: NextRequest`).

**Projected end-state after all three:** ~14/14 auth POST, ~7–13/14 pre-auth POST
(depending on how many of the CRON-secret / SAML / webhook-sig handlers we
choose to also model as "authenticated by non-user mechanism" — a separate
design decision).

---

## 5. Design constraint — the recognizer stays a *signal*, not a *verdict*

Even after these three fixes land, the recognizer remains a **structural
heuristic**. The `by_all_but_one_bad_return` shape is *shared* between
authentication and input-validation (same K-1-bad-return + 1-fall-through
signature). What discriminates the two is:

- **Reusability** — is the function called from many handlers, or inlined once?
  (Current predicate uses this via `kb_called_from` — accidental-correct on
  `displays` because its validation is inlined.)
- **Return-value flavor** — 401 is unambiguously "not authenticated"; 403 is
  contested territory (auth-failure OR capability-failure OR feature-gate).
  Callee names like `notAuthenticatedResponse` / `unauthorizedResponse` are
  strong signals; `forbiddenResponse` / `badRequestResponse` are weak.
- **Guard touchpoint** — does the guard read from `session` / `cookies` /
  `token` / `authorization`?

A future refinement of `ByAllButOneBadReturn` should require *≥ 1 explicit
401 bad-return* (or a callee whose name matches the auth-flavored catalog)
to promote structural shape to structural evidence. That's a fourth leaf
addition, out of scope for this doc but noted for the follow-up.

The `AuthEvidence` tagged union exists precisely so the LLM agent (or a
human reviewer) can weigh trust per-match rather than consuming a boolean.
**We cite evidence; we do not classify.**

---

## 6. Reproduction

Assumes the compose stack is up (`docker compose --env-file .env -f
./compose/compose.base.yaml -f ./compose/compose.app.yaml -f
./compose/compose.fronts.yaml -f ./compose/compose.prebuilt.yaml -f
./compose/compose.workers.yaml up -d`) and the queryengine was rebuilt
after the local `dhscanner.core` and `dhscanner.packages/dhscanner.kbapi`
submodule edits (`docker compose ... build queryengine`).

```powershell
# 1. Fresh KB from a formbricks checkout under ./formbricks/
$env:PYTHONIOENCODING = 'utf-8'
python -m cli run --scan_dirname formbricks --ignore_testing_code true --with_agent
# → note the kb_location printed in the final line (e.g. /tmp/kb_XXXXXXXX11-0.pl)

# 2. Fire the 2×2 grid (edit KB_LOCATION at the top of query_grid.py if it changed)
python query_grid.py
# → summarized to stdout + query_grid.log

# 3. Enumerate ground truth (POST handlers + auth/pre-auth split)
$hits = Get-ChildItem -Path formbricks/apps/web -Recurse -Filter "route.ts" |
  Select-String -Pattern "^export\s+(const|async\s+function|function)\s+POST\b" -List
$pattern = 'checkAuth|authenticatedApiClient|hasPermission|getServerSession|authOptions'
$hits | ForEach-Object {
  $c = [System.IO.File]::ReadAllText($_.Path)
  $bucket = if ($c -match $pattern) { 'AUTH' } else { 'PRE-AUTH' }
  "{0}  {1}" -f $bucket, $_.Path.Replace((Get-Location).Path + '\', '')
} | Sort-Object
```

The 2×2 grid + summary is emitted by `query_grid.py`; the last known-good run
is preserved in `query_grid.log` (untracked) for reference.

---

## 7. Non-goals for the follow-up PR

- **No new tests.** The recognizer is a probabilistic signal; test cases would
  ossify structural details that we expect to iterate on. Confidence is
  driven by re-running the reproduction against real-world targets
  (formbricks + at least one more repo from the OWASP talk's target list),
  not by fixture-based unit tests.
- **No parser changes.** Everything above is `utils.pl` + tiny `dhscanner-kbapi`
  additions + tiny queryengine decoder additions. If a parser gap is
  uncovered along the way (e.g., HOC unwrapping requires kbgen to emit a
  new fact), route that separately per the parsers-submodule AGENTS.md.
- **No `AuthenticatedHttpGetHandlerRequestObject` work yet.** Auth-GET is
  0/? on formbricks; the same three fixes above are expected to apply
  symmetrically once auth-POST is at good recall.
