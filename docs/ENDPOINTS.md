# ENDPOINTS

Orientation for future agent sessions: **how the notion of "an HTTP endpoint"
is currently modeled in the dhscanner knowledge base**, where the recognizers
live, and what the extension contract is when a new framework needs to be
supported.

Companion to [`ARCHITECTURE.md`](ARCHITECTURE.md) (runtime view — who talks
to whom) and [`LAYOUT.md`](LAYOUT.md) (disk view — which service lives
where). This doc is scoped to **one concern**: the endpoint layer.

---

## 1. Mental model in one line

An **endpoint** in dhscanner is not a fact in the KB. It is a **callable in
the KB** (a function, a method, or a lambda) that a **framework-specific
recognizer clause** in `utils.pl` decides is dispatched by an HTTP request.

Concretely: kbgen emits language-agnostic primitives (`kb_func_def/4`,
`kb_class_def/3`, `kb_method_of_class/2`, `kb_call_resolved/2`,
`kb_param_i_of_callable/3`, `kb_param_has_resolved_type/2`, …). Prolog
predicates in `dhscanner.core/dhscanner.service.queryengine/utils.pl`
then **project** the callables that match a given framework's dispatch
convention out of that soup. That projection IS the endpoint set.

Consequence: **adding a new framework never changes the KB schema.** It is
always a leaf clause added under an existing disjunction in `utils.pl`. Same
"leaf addition" discipline the parsers submodule uses for grammar coverage
(see [`../dhscanner/dhscanner.1.parsers/AGENTS.md`](../dhscanner/dhscanner.1.parsers/AGENTS.md))
and the auth-recall follow-up plan uses for tier-1 recognizers
(see [`AUTH_POST_RECALL_GAPS.md`](AUTH_POST_RECALL_GAPS.md) §4).

---

## 2. Two orthogonal recognizer families

Endpoint-adjacent questions split into two families in `utils.pl`. A
"complete" framework story usually lands in both, but they answer different
questions and can be shipped independently.

| family | question it answers | top-level predicate |
|---|---|---|
| **endpoint enumeration** | *"Which callables are dispatched by HTTP verb X?"* | `utils_http_get_handler_request_object/3`, `utils_http_post_handler_request_object/3`, `utils_http_put_handler_request_object/3` |
| **user-input origin** | *"From which param / expression does untrusted input enter?"* | `utils_user_input/1` (with `utils_user_input_originated_from_*` leaves) |

Auth-flavored extensions of family 1 exist as 5-arg variants:
`utils_authenticated_http_{get,post,put}_handler_request_object/5` (with
`AuthFuncName` + `AuthEvidence` tuple) and `utils_unauthenticated_*/3`. See
`utils.pl` lines ~281–374 for the shape and
[`AUTH_POST_RECALL_GAPS.md`](AUTH_POST_RECALL_GAPS.md) for the active
recall work on those.

---

## 3. Structural archetypes

Every framework recognizer shipped so far fits one of three archetypes.
When mapping a new framework, first classify it into one of these three —
the recognizer shape then follows mechanically.

### 3.1 File-based + verb-export (Next.js today)

Endpoint identity comes from **file path + top-level export name**. The URL
is (a suffix of) the file path itself.

```prolog
utils_http_post_handler_request_object_nextjs(PostHandler, RequestObject, Url) :-
    kb_func_def(PostHandler, 'POST', FileName, Url),
    kb_param_i_of_callable(RequestObject, _, PostHandler),
    utils_param_has_request_name(RequestObject),
    utils_param_has_request_resolved_type(RequestObject),
    endswith(FileName, 'route.ts').
```

See `utils.pl` lines ~80–158. Note two structural sub-shapes are already
factored: `_direct` (the exported handler IS the handler) and `_wrapper`
(the exported handler is a thin lambda whose body is a single HOC call —
`utils_hoc_dict_handler_unwrap/2` walks into the HOC's dict argument to
bind the real inner handler).

### 3.2 Class-inheritance + method-of-subclass (Tornado today)

Endpoint identity comes from **subclass-of-framework-base + method name**.
No filename gate; no verb export.

```prolog
utils_user_input_originated_from_pip_tornado_get_query_argument(Call) :-
    kb_call_method_of_class(Call, 'get_query_argument', Subclass),
    kb_class_has_3rd_party_super(Subclass, _, 'tornado.web.RequestHandler').
```

See `utils.pl` lines ~1174–1183. Note this leaf is scoped to the
`get_query_argument` **read** (user-input family); the class-inheritance
skeleton is the reusable part when a new class-inheritance-shaped framework
needs endpoint enumeration too.

### 3.3 Explicit registration call + lambda (Express, Echo today)

Endpoint identity comes from a **registration call** (`router.get(url, fn)`)
whose argument list carries the URL string and the handler lambda.

```prolog
utils_user_input_originated_from_npm_express_request_handler(Param) :-
    kb_call_resolved(GetRequestHandler, 'express.Router.route.get'),
    kb_param_has_name(Param, 'req'),
    kb_param_i_of_callable(Param, 0, Lambda),
    kb_arg_i_for_call(Lambda, 0, GetRequestHandler).
```

See `utils.pl` lines ~1184–1198. Echo (Go) sits right below with the same
shape against `echo.Group.GET`.

---

## 4. Primitives available to a recognizer

Declared `discontiguous` / `dynamic` at the top of `utils.pl` (lines 1–29).
Populated by kbgen; the KB payload is language-agnostic.

- **Callables & classes**: `kb_func_def/4` (name + file + url), `kb_class_def/3`,
  `kb_class_has_named_super/2`, `kb_class_has_1st_party_super/3`,
  `kb_class_has_3rd_party_super/3`, `kb_class_has_resolved_super/2`,
  `kb_subclass_of/2`, `kb_method_of_class/2`, `kb_callable_annotated_with/2`,
  `kb_callable_source_body_length/2`.
- **Params & args**: `kb_param_i_of_callable/3`, `kb_param_has_name/2`,
  `kb_param_has_type/2`, `kb_param_has_resolved_type/2`,
  `kb_arg_i_for_call/3`.
- **Calls**: `kb_call_resolved/2`, `kb_call_method_of_class/3`,
  `kb_call_method_of_untyped_named_param/3`,
  `kb_call_1st_party_func_defined_in_dir/3`,
  `kb_call_1st_party_func_defined_in_file/3`.
- **Values**: `kb_const_string/2`, `kb_const_null/1` (int/bool coverage
  partial — see the note at `utils.pl` line ~535 about `kb_const_int/2`).
- **Dataflow**: `kb_dataflow_edge/2`, plus the bounded intra-procedural
  walker `utils_intra_dataflow_path/3` (default depth 10).

Anything a framework recognizer needs beyond this list is a **kbgen gap**,
not a recognizer gap — route it upstream to the kbgen / codegen / parser
stages per [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## 5. Framework matrix (shipped)

| framework | endpoint enumeration (§2 family 1) | user-input origin (§2 family 2) | auth-wrapped variants (§2 auth) |
|---|:---:|:---:|:---:|
| Next.js (`route.ts` + verb export) | ✅ GET / POST / PUT | ✅ | ✅ (`by_header_null_check`, `by_all_but_one_bad_return`) |
| Tornado (`RequestHandler` subclass) | ❌ | ✅ (only `get_query_argument`) | ❌ |
| Express (`Router.route.get` + lambda) | ❌ | ✅ | ❌ |
| Echo (Go, `Group.GET` + lambda) | ❌ | ✅ | ❌ |
| Yii (PHP) | ❌ | ❌ | ❌ (sink-only via `sqli_php_yii`) |

**Endpoint-enumeration coverage today is Next.js only.** Everything else is
user-input-origin coverage that assumes the endpoint set is already
known (or reachable) by other means. See placeholders in `utils.pl` —
lines 76 (`% add more kinds here ...`) and 518
(`% ... add more kinds here ( _python, _go, _php, ... ) ...`).

---

## 6. Adding a new framework — checklist

1. **Classify the framework into one of §3's archetypes.** If it doesn't
   fit any, that's a design conversation before code — flag it.
2. **Probe the KB.** Scan one representative file from the target
   framework in agent mode and confirm the primitives the recognizer needs
   are actually populated. Typical gaps: FQN resolution for the language's
   `import` / `use` / `require` construct, or class-super list emission for
   the language's `extends` construct. Route parser-side gaps through
   [`../dhscanner/dhscanner.1.parsers/AGENTS.md`](../dhscanner/dhscanner.1.parsers/AGENTS.md).
3. **Write leaf clauses in `utils.pl`.** One new
   `utils_..._<framework>/N` predicate per verb / per shape. Wire it into
   the existing top-level disjunction (family 1, family 2, or both). Do
   **not** rewrite any existing clause — leaf additions only, same
   contract as [`AUTH_POST_RECALL_GAPS.md`](AUTH_POST_RECALL_GAPS.md) §4.
4. **URL synthesis if needed.** File-based frameworks get the URL for
   free from `kb_func_def/4`; convention-based frameworks (e.g., Matomo's
   `?module=<PluginDir>&action=<method>`) need a small string helper on
   the recognizer side. No KB change needed.
5. **kbapi surface (optional).** If the new recognizer should be
   callable by name from the LLM outer loop, add a query wrapper in
   `dhscanner.packages/dhscanner.kbapi` and re-build queryengine. If it
   only needs to feed existing higher-level predicates (like
   `utils_user_input/1` → sink reachability), no kbapi change is required.
6. **No new tests.** Per [`AUTH_POST_RECALL_GAPS.md`](AUTH_POST_RECALL_GAPS.md)
   §7 — recognizers are probabilistic structural signals; validation is
   real-world scans, not fixtures.

---

## 7. Where each pipeline stage contributes

Quick pointer table so the next session doesn't have to re-derive the
per-stage responsibilities from `ARCHITECTURE.md`:

| stage | service | contribution to the endpoint layer |
|---|---|---|
| native front | `frontjs` / `frontts` / `frontphp` / `frontpy` / `frontrb` / `frontcs` / `frontgo` | language-native AST — must preserve class inheritance, decorators / attributes, top-level export declarations, and typed-param annotations |
| dhscanner parser | `parsers` (Happy grammars in `dhscanner.core/dhscanner.service.parsers/src/*.y`) | normalizes native AST into `dhscanner.ast` — this is where `stmtClassSupers`, `stmtClassMethods`, verb-export detection etc. get carried through |
| codegen | `codegen` | per-callable IR; also records `Callable.numOriginalSourceInstructions` used by `kb_callable_source_body_length/2` (needed by the Next.js HOC-unwrap recognizer) |
| kbgen | `kbgen` | emits the `kb_*` facts listed in §4. **Never** emits `utils_*`. |
| queryengine | `queryengine` | hosts `utils.pl` — this file is where every framework recognizer lives. Loaded together with the assembled KB. |
| kbapi | `dhscanner.packages/dhscanner.kbapi` | Haskell-side query surface exposed on `queryengine:3000` in agent mode; wraps a subset of the `utils_*` predicates as named queries for the LLM outer loop |

---

## 8. Related docs

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — runtime pipeline, both modes
  (normal / agent) at the queryengine stage.
- [`LAYOUT.md`](LAYOUT.md) — disk view: which service lives in which
  compose file / submodule.
- [`AUTH_POST_RECALL_GAPS.md`](AUTH_POST_RECALL_GAPS.md) — worked example
  of the leaf-addition contract, on Next.js auth recognizers against
  formbricks.
- [`OWASP_NOTES_FINALIZED.md`](OWASP_NOTES_FINALIZED.md) — where endpoint
  enumeration sits in the outer-loop / ScanDigest / ScanTrace story.
- [`../dhscanner/dhscanner.1.parsers/AGENTS.md`](../dhscanner/dhscanner.1.parsers/AGENTS.md)
  — parser-coverage iteration loop; the place upstream KB gaps get closed.
