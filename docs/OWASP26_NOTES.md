# OWASP-IL 2026 — Notes & Direction

This document has two intentionally overlapping purposes:

1. **Talk preparation reference** for the 30-minute OWASP-IL 2026 presentation on `dhscanner`.
2. **Direction document for `dhscanner` itself** — the KB-primitive design, the eager-preprocessing thesis, the cross-language / cross-framework unification story, and the decisions those imply for what we build next.

The talk is the *pretext* for crystallising the direction — most of what's captured below (KB primitives, `utils.pl`'s role, the amortisation vs LLM-inline framing, the framework-invariance thesis) survives the talk and shapes the product's next 12 months.

**Style constraint (talk only):** minimalist slides (≤ 3 one-word bullets each); the bulk of the content is delivered verbally in a "bonfire storyteller" cadence.

**Related artifacts:**

- Deck HTML: `../../owasp26talk/index.html` (reveal.js) — visual artifact, styling only.
- Prose / talking version: `../../owasp26talk/notes.txt` — verbatim-ish speaker notes.
- **This file:** structured reference — decisions, evidence, one-liners, cross-cutting themes, direction anchors.

> **Rule of thumb (talk):** the deck shows universal words; the specific vocabulary is delivered verbally.
> **Rule of thumb (direction):** every claim in the talk should be recoverable from a KB primitive, a `utils.pl` clause, or a parser/kbgen instrumentation point — if it isn't, that's a roadmap item.

---

## 1. Core Thesis

Modern SAST discourse has drifted toward two poles:

1. **Predefined / rule-authored analyzers** (huge public rulesets, community-curated queries).
2. **Pure-LLM agentic scanners** (feed the LLM the codebase, let it grep/read/reason).

`dhscanner` occupies a third position: **an eager, query-ready knowledge base of universal semantic primitives, driven adaptively by an LLM.** The LLM never wastes tokens rediscovering plumbing; it spends them on **insight**. The KB primitives are language- and framework-agnostic; the mechanism-diversity of the underlying world is absorbed once, at parse time, inside `utils.pl` and the parser/kbgen layer.

**Anchor sentence:** *"Amortize once. Query many. Spend tokens on insight, not on book-keeping."*

**Alternative anchor:** *"The LLM shouldn't be a compiler."*

---

## 2. Deck Structure at a Glance

Two-tier presentation of dhscanner's contribution, bracketed by framing and closed by a live demo + generalization.

| # | slide / section | status | one-word tag |
|---|---|---|---|
| 1 | Title / greeting | ✅ locked | *SAST* |
| 2 | Traditional SAST framing (Semgrep, CodeQL ecosystems — **unnamed**) | ✅ locked | *predefined* |
| 3 | The elephant: is SAST even a thing in Sep 2026? | ✅ locked | *elephant* |
| 4 | Why not pure-LLM? Point 1: **Observability** (limited) | ✅ locked | *observability* |
| 5 | Why not pure-LLM? Point 2: **FinOps** (hundreds of commits = $$$) | ✅ locked | *finops* |
| 6 | ReAct / ACI framing — dev primitives vs sec primitives | ✅ locked | *primitives* |
| 7 | Title tweak: ~~Predefined~~ → **Adaptive** | ✅ locked | *adaptive* |
| 8 | Better primitives: **unification, algorithms, facts, api** | ✅ locked | *unification* |
| 9 | **Tier 1 opener** — Context Overload (framing) | 🟡 pending | *overload* |
| 10 | Tier 1a: **endpoints** (phpbb `mark_read` Symfony 3-file) | ✅ layout locked | *endpoints* |
| 11 | Tier 1b: **fqns / Qualified Names** (formbricks `responses`) | ✅ layout locked | *fqns* |
| 12 | Tier 1c: **call sites** (Go structural typing) | 🟡 pending | *call sites* |
| 13 | Tier 1 closer — eager pre-processing / LSP parallel | 🟡 pending | *amortize* |
| 14 | **Tier 2 opener** — AppSec cornerstones (framing) | 🟡 pending | *cornerstones* |
| 15 | Tier 2a: **auth** (phpbb ≈ formbricks shape invariance) | 🟡 pending | *auth* |
| 16 | Tier 2b: **crypto** | 🟡 pending | *crypto* |
| 17 | Tier 2c: **polarity** | 🟡 pending | *polarity* |
| 18 | Live demo: formbricks CWE-22 (M=4 sibling call-sites) | 🟡 pending | *demo* |
| 19 | Generalization: HackerOne targets | 🟡 pending | *generalize* |
| 20 | Architecture (2-mode pipeline, 21 services) | 🟡 pending | *architecture* |
| 21 | Wrap / call to action | 🟡 pending | *wrap* |

**Narrative arc:** framing → why-not-pure-LLM → what's the right primitive → *Tier 1 (structural quick wins)* → *Tier 2 (security cornerstones)* → *proof* (demo + generalization) → architecture → wrap.

---

## 3. Slide-by-Slide Notes (locked & pending only)

### Slide 3 — The Elephant

**On screen:** two logos (OpenAI, Anthropic), aligned horizontally.
**Punch:** address the "why not just let LLM agents do the whole scan?" objection up front, not defensively.

### Slides 4–5 — Observability + FinOps

**Point 1 (Observability):** pure-LLM scans are opaque; hard to reproduce, hard to audit, hard to explain a finding.
**Point 2 (FinOps):** re-scanning across hundreds of commits with a pure-LLM approach is genuinely expensive. Not a theoretical objection.
**Reserved for later:** don't middle-word FinOps — it's a bookend, not a recurring theme.

### Slide 6 — ReAct / ACI framing (canonical citations)

**On screen:** two-column table.

| dev primitives | sec primitives |
|---|---|
| grep | endpoints |
| find | fqns |
| wget | auth |
| write | (…more) |

**Canonical papers to reference verbally (do not put on slide):**

- **ReAct** — Yao et al., 2022 ("ReAct: Synergizing Reasoning and Acting in Language Models").
- **SWE-agent / ACI** — Yang et al., 2024 ("SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering"). The paper that formalized the shift from copy-paste-into-browser to install-on-desktop tool loops with a shaped agent-computer interface.

**Verbal anchor:** *"Naïve grep-5-lines-above-10-below is an ultra-powerful context guide — a hunt-the-treasure game. We keep the game, but we replace grep with **endpoints**, find with **fqns**, and so on."*

### Slide 7 — Title tweak

Change from ~~predefined~~ (struck-through in red) → **adaptive**. "Predefined" is one word (confirmed).

### Slide 8 — Better primitives

**Four steps chosen:** `unification`, `algorithms`, `facts`, `api`.

### Slide 10 — endpoints (phpbb `mark_read`)

**Rejected alternatives:** `report.yml` (weak IDOR framing), `ucp.yml` reset-password (UCP prefix noisy), edit-post (legacy `posting.php?mode=edit`, not modern Symfony routed).
**Chosen endpoint:** `mark-read/{id}` — nice IDOR framing (URL is just an integer, mixes running-in-sec-folks).

**Three files, three roles:**

| # | file | role | key lines |
|---|---|---|---|
| 1 | `phpBB/config/default/routing/notifications.yml` | *routing* — URL + controller reference | 6 lines total |
| 2 | `phpBB/config/default/container/services_notification.yml` | *wiring* (DI) — controller service definition + injected deps | lines 255–263 |
| 3 | `phpBB/phpbb/notification/controller/mark_read.php` | *handler* — actual PHP class | ns line 14; class line 27; `handle` line 78; anon check lines 82–89 |

**Verbal punch — "Symfony ≥ 5.2 local specification":** the newer inline-attribute routing style is much easier to parse — it's literally colocated with the function/method. This slide shows the *older, still-common* 3-file style to demonstrate the context-overload point.

**Concrete count for the slide:** three files, but the number that matters is **three hops of symbolic lookup**, not "deps." The KB primitive collapses those three hops into one query.

**Silent shot:** the criticism of "book-keeping of hundreds of YAML rules" (Semgrep) and "hundreds of QL queries" (CodeQL) — do NOT name either. *Silent snipes are the best snipes.*

**Utils.pl callback:** the framework-specific quirks of Symfony's 3-file pattern are absorbed once inside `dhscanner.core/dhscanner.service.queryengine/utils.pl` (48KB, actively maintained). Utils.pl is where the "kinetic energy" of framework quirks converts to "potential energy" of a query-ready primitive.

**Incremental scans angle (optional, save for verbal delivery):** knowing all endpoints upfront + persisting past LLM queries lets us detect that a code change *doesn't* affect the endpoint surface → skip a full re-scan. **Not yet implemented**, but reachable.

### Slide 11 — Qualified Names (formbricks `responses`)

**Title on slide:** `Qualified Names (FQNs)` — drop "Fully" to reduce cognitive load; keep FQN in the acronym; explain verbally on first mention.
**FQN familiarity check:** term is well-known in a Java/.NET-heavy audience, but not universal at OWASP-IL — hence the acronym-plus-narration approach.

**On-screen 4-row layout** (locked):

| row | on-screen label | what it points at |
|---|---|---|
| 1 | `tsconfig.json` | path-alias chain (`@/*` → `./*`), `extends` up 3 levels, workspace-package ref, moduleResolution `bundler` |
| 2 | *indirection* | barrel files (`index.ts` re-exports) — verbally: *"you might have heard the term **barrel files**"* |
| 3 | *native types* | JS/TS built-ins (`Response.json(...)`) — flag: term "native" is overloaded; alternatives `built-ins` / `globals` (**decision pending**) |
| 4 | *3rd party* | vendor packages via `node_modules` |

**Concrete example on the slide:**

```ts
import { responses } from '@/app/lib/api/response';   // (1) path alias via tsconfig
                                                       // (2) resolves through indirection
                                                       // (3) responses = object of named arrow fns
Response.json({ /* ... */ });                          // (4) native built-in
```

**Evidence file (formbricks):** `apps/web/app/lib/api/response.ts` (lines 262–272) exports an object literal of 10 named arrow functions (`unauthorizedResponse`, `notFoundResponse`, `badRequestResponse`, ...). Callers do e.g. `responses.unauthorizedResponse()` — every call must be resolved back to the specific arrow function.

**Real cold-LLM cost to resolve one `@/foo` import:**

- Read `apps/web/tsconfig.json` (has `paths`, `extends`)
- Read `packages/config-typescript/nextjs.json` (extends `./base.json`, sets `moduleResolution: "bundler"`)
- Read `packages/config-typescript/base.json` (root of chain)
- Find the workspace-package reference target
- ≈ **6 tool calls** for one import, in a warm codebase. **Multiply by every import in every file.**

**Cross-language barrel-file coverage (across dhscanner's 7 supported languages):**

| language | barrel? | mechanism |
|---|---|---|
| ts | ✅ | `index.ts` re-exports |
| js | ✅ | `index.js` re-exports (predates TS) |
| py | ✅ | `__init__.py` with `from .x import y` |
| rb | ✅ | `lib/gem.rb` cascading `require`s |
| cs | ❌ | namespaces flatten |
| go | ❌ | package = directory |
| php | ❌ | PSR-4 autoload |

**Verbal aside:** *"Four of the seven languages we support have this indirection pattern, and the other three each opt out for a different reason."* — one sentence, quiet cross-language credibility.

**Cross-language config-lineage coverage (tsconfig-style):**

| language | equivalent | shape |
|---|---|---|
| ts / js | tsconfig.json, jsconfig.json, package.json `imports`, bundler configs (webpack/vite/rollup/babel) | arbitrary aliases; **deep chain** via `extends`; often 5+ files active at once |
| php | `composer.json` `autoload.psr-4` | prefix-only (namespace → dir); **flat fan-out** — one file per package, no `extends`; vendor deps contribute their own |
| py, rb | *(none first-class; `sys.path` / `$LOAD_PATH` are runtime)* | — |
| go | `go.mod` `replace` | module-level, mostly local dev / forks |
| cs, java | *(no equivalent — namespace = path)* | — |

**Verbal shorthand:** *"tsconfig is a chain; composer is a fan-out."*

### Slide 12 — Call Sites (PENDING — recommended layout)

**Story shape:** "who calls this function?" — the third fundamental axis of a code KB.
**Axes covered by the trio:**

| slide | axis of mechanism-diversity | what makes it hard |
|---|---|---|
| endpoints | framework | pieces scattered across files |
| fqns | language + ecosystem | pieces scattered across config layers |
| **call sites** | **type system paradigm** | pieces **not written down anywhere** — the compiler infers them |

**Resolution model landscape:**

| paradigm | languages | candidate search space |
|---|---|---|
| nominal + closed (`implements` / `: Base`) | Java, C#, Kotlin, C++ | enumerable from class hierarchy |
| nominal + traits | Rust | enumerable from `impl Trait for Type` |
| **structural static** | **Go**, TypeScript interfaces | **the entire type universe** |
| structural dynamic | Python, Ruby, JS | undecidable statically |

**The Go payoff (this is the slide's spine):** for `r.Read(buf)` where `r: io.Reader`:

- In Java: walk a finite `implements` graph. Done.
- In Go: scan *every type in the codebase and every dependency*. A struct in an unrelated package, whose author never heard of `io.Reader`, still counts. **Eligibility is inferred by the compiler, not declared by the programmer.**

**Go-specific grep-defeaters (great ammo):**

1. **Pointer vs value receivers** — `func (f *Foo) Read(...)` is in `*Foo`'s method set but not `Foo`'s. A value fails `io.Reader`; a pointer satisfies it.
2. **Embedded types (promotion)** — `struct { io.Reader; ... }` promotes methods. Struct can satisfy interface with zero visible method definitions in its own body.
3. **Anonymous composed interfaces** — `type ReadWriter interface { Reader; Writer }` — transitive satisfaction.
4. **Generic type constraints** — `func Foo[T Reader](x T)` — constraint solving expands candidate set.

**Killer one-liners for the slide:**

- *"In nominal-typed languages, `implements` is a **manifest**. In structurally-typed languages, `implements` is a **theorem** — and you have to prove it once per interface, per type, per project."*
- *"In Java, 'find call sites' is a graph walk. In Go, 'find call sites' means the compiler already ran a whole-program structural matching pass — and if you're not running that pass, you're guessing. Grep can't guess this. An LLM shooting greps can't guess this."*

### Slide 13 — Tier 1 Closer (PENDING — recommended)

**Punch:** name the pattern the audience has just seen three instances of.

**On screen (suggested):**

```
eager pre-processing → query-ready KB
= every IDE. every search engine. every database index.
```

**Verbal delivery:** the LSP parallel.

**LSP explainer (in case audience needs it):** Language Server Protocol, Microsoft 2016, born from VS Code. Solves N×M editor-language pairing via JSON-RPC contract. `gopls`, `rust-analyzer`, `pyright`, `clangd`, `jdtls` — each pre-parses the workspace into a symbol graph on startup, answers `textDocument/references` etc. in ~10ms from its in-memory index.

**Perfect framing sentence:**

> *"Every developer at OWASP-IL is using an IDE that pre-parses their codebase into a query-ready graph. It's why 'find references' takes 50 ms instead of 5 seconds. We're doing the same thing — for security queries instead of navigation ones. This isn't a novel idea. It's the boring, correct engineering choice."*

**Bonus — this framing also lands FinOps classily:** eager pre-processing is **O(1) amortized per query**; lazy LLM-only is **O(codebase-size) per query**. Same algorithmic asymmetry that makes Google's index worth ~$100B. *Money argument in Big-O notation.*

### Slide 15 — Auth (Tier 2a, PENDING)

**Ammo already in hand:** shape-invariance of the auth check across phpbb and formbricks — validated in earlier conversation.

- **phpbb:** `if (user_id == ANONYMOUS) throw http_exception(403)`
- **formbricks:** `if (!session) return unauthorizedResponse()`

**Different PL, different framework, different syntax, same architectural shape.** This IS the "unification" thesis in one visual comparison.

**Extended surface (for verbal delivery, not slide clutter):**

| mechanism | where it lives |
|---|---|
| middleware chain | `MIDDLEWARE = [...]` in Django settings, `app.use(...)` in Express |
| route-group prefix | Rails `before_action`, Express `router.use('/admin', requireAuth)` |
| decorator / annotation | `@login_required`, `@IsAuthenticated`, Spring `@PreAuthorize` |
| framework config | Symfony `security.yaml` regex-per-URL, phpbb's `$user` DI argument |
| in-handler check | phpbb + formbricks (above) |
| optional auth | handler runs either way but branches — the hardest case |

**Compositional payoff:**

> *"endpoints × fqns × call sites × auth = **`which endpoints call sensitive functions without an auth guard?`** = **Broken Access Control** = OWASP #1."*

### Slides 16–17 — Crypto + Polarity (PENDING)

Reserved slots — content TBD.

- **crypto**: crypto misuse patterns (weak algorithms, hardcoded secrets, IV reuse, insecure random, etc.). Compositional payoff: "endpoints × crypto = crypto misuse reachable from the internet."
- **polarity**: (TODO — Oren's term; needs one-paragraph definition when he defines it). Compositional payoff: "polarity confirms the sink actually fires."

### Slide 18 — Demo (PENDING)

**Target:** formbricks CWE-22 path traversal.
**Fix commit:** `9d84bc0c…`.
**Amplifier:** **M=4 sibling call-sites** to `validateAndResolvePath` — one flawed helper, four call-sites all inheriting the flaw. Big story.

### Slides 19–21 — Generalize / Architecture / Wrap (PENDING)

- **Generalize:** HackerOne target catalog; broader vuln classes reachable by the same primitives.
- **Architecture:** 2-mode pipeline (normal Prolog vs `agent_mode` with `kb_location`), 21 services across 5 compose files, 7 language frontends (cs / go / js / php / py / rb / ts) + YAML in-proc.
- **Wrap:** call to action / repo / contact.

---

## 4. Cross-Cutting Themes

These recur across multiple slides — flag them mentally so they don't feel like new material each time.

### 4.1 Universal words on screen, specific vocabulary verbally

Slides show `predefined`, `adaptive`, `unification`, `overload`, `endpoints`, `fqns`, `call sites`, `auth`. The specific mechanisms (`tsconfig.json paths`, `composer.json autoload`, `structural typing`, `PSR-4`, `Symfony DI`) live in the verbal delivery. This is what enables the ≤ 3 one-word-bullet style without losing depth.

### 4.2 Unification (PL-agnostic → framework-agnostic)

Repeated framing: dhscanner claims **no silver bullet** — AppSec is about **security mechanisms that are shared across PL and framework**. The right API abstracts both. Every slide is another data point for this thesis.

**Instances stacked in evidence base:**

- Endpoint declaration (routing YAML / attribute / decorator / file-based)
- Auth checks (`throw http_exception` / `return unauthorizedResponse()` / `@login_required`)
- Wiring (DI container / globals / decorators)
- Barrel files (`index.ts` / `__init__.py` / `mod.rs` / umbrella `.h`)
- Config lineage (tsconfig chain vs composer fan-out)
- Method resolution (nominal vs structural)

*Same architectural need every time, wildly different mechanisms — perfect substrate for a universal KB primitive.*

### 4.3 Context Overload (Tier 1 middle term)

Better than "FinOps" for framing the Tier 1 problem — it captures the *cognitive* asymmetry, not just the dollar asymmetry. Straightforward aggregation of "what defines an endpoint" can be done without an LLM — no reason to have it involved, wasting time and context bandwidth.

**FinOps stays a bookend, not a middle term.** Once at start (why not pure-LLM), maybe once at end (implicit via Big-O). Not repeated.

### 4.4 "Systematic and reusable" (framing preferred over "automated")

For talk safety in Q&A, always describe our approach as **systematic and reusable**, not "automated." "Automated" invites obvious questions about failure modes; "systematic and reusable" invites methodological respect.

### 4.5 "Share infrastructure, isolate runtime state"

Cross-framework DI pattern (Symfony services default `shared: true` + `shared: false` opt-out; Spring beans singleton/prototype/request; .NET Core Singleton/Scoped/Transient; NestJS `@Injectable({scope})`; Django/Flask module globals; FastAPI `Depends()`).

**Historical lineage worth citing verbally:**

- EJB (1998) → REST/Fielding (2000) → 12-Factor App VI: "Processes" (2011).
- Same principle, three different eras, three different vocabularies.

**Answer to "does designing this way force a global mental image?":** partially yes, but not as much as it looks — the DI container is the shared workspace; individual endpoints stay locally reasoned. Even in "share-nothing" frameworks (Flask, FastAPI), the same effect is achieved via module-level imports — just a different mechanism.

### 4.6 Colocation trend

Modern frameworks trend toward colocating the routing, wiring, and handler into one file (attributes / decorators / file-based routing). Symfony ≥ 5.2 local specification. Next.js `app/` router. FastAPI decorators. Rails `resources`. Django's `path()`. This reduces the LLM's context load for endpoint discovery in modern codebases, but **doesn't eliminate the underlying complexity** — auth middleware, DI, and framework config still live elsewhere.

### 4.7 Do NOT name Semgrep or CodeQL

Talk is stronger without direct naming. *Silent snipes are the best snipes.* The audience knows exactly who is meant when we say "predefined ruleset" and "hundreds of QL queries." Direct naming invites tribalism; silence invites recognition.

---

## 5. Concrete Evidence Base

### 5.1 phpbb — Symfony 3-file endpoint (Slide 10)

| file | path | key lines |
|---|---|---|
| routing | `phpbb/phpBB/config/default/routing/notifications.yml` | 6 lines total |
| wiring (DI) | `phpbb/phpBB/config/default/container/services_notification.yml` | lines 255–263 (5 dependencies) |
| handler | `phpbb/phpBB/phpbb/notification/controller/mark_read.php` | ns line 14; class line 27; `handle` method line 78; anonymous check lines 82–89 |

**Handler auth check (formatted for slide):**

```php
if ($this->user->data['user_id'] == ANONYMOUS) {
    throw new http_exception(403, 'NOT_AUTHORISED');
}
```

**DI arguments confirmed on `handle` service:** `@request`, `@user`, plus notification manager, template, and controller helper. Specifying `@user` in the arguments list *forces* the service to instantiate a user object → de-facto authenticated endpoint (via DI).

### 5.2 formbricks — Response helpers (Slide 11)

- **File:** `formbricks/apps/web/app/lib/api/response.ts`, lines 262–272.
- **Shape:** exported object literal containing 10 named arrow functions.
- **Consumer example:** `formbricks/apps/web/app/api/v1/management/storage/local/route.ts`, line 34 → `responses.unauthorizedResponse()`.

### 5.3 formbricks — tsconfig chain (Slide 11)

- `apps/web/tsconfig.json` — declares `"paths": { "@/*": ["./*"] }`, extends `@formbricks/config-typescript/nextjs.json`
- `packages/config-typescript/nextjs.json` — extends `./base.json`, sets `moduleResolution: "bundler"`
- `packages/config-typescript/base.json` — root of chain

### 5.4 formbricks — Auth check (Slide 15)

```ts
if (!session) {
    return responses.unauthorizedResponse();
}
```

### 5.5 formbricks — CWE-22 seed vulnerability (Slide 18)

- **Vuln class:** CWE-22 (path traversal).
- **Fix commit:** `9d84bc0c…`.
- **Amplifier:** M=4 sibling call-sites to `validateAndResolvePath`.
- **Extended demo notes:** `demo/formbricks.md` (162 KB — only first 200 lines read so far).

### 5.6 utils.pl (Slide 10 verbal callback)

- **Path:** `dhscanner.core/dhscanner.service.queryengine/utils.pl`
- **Size:** 48,645 bytes
- **Actively maintained:** last edit 2026-09-09.
- **Role:** absorbs the "kinetic energy" of framework-specific quirks (Symfony YAML resolution, decorator patterns, etc.) into "potential energy" — a query-ready primitive layer.

### 5.7 Architecture facts

- **Two modes:** normal Prolog vs `agent_mode` with `kb_location` (for LLM query loop).
- **KB API primitives:** `endpoints`, `fqns`, `auth`, `dataflow?`.
- **21 services, 5 compose files.**
- **7 language frontends:** `cs`, `go`, `js`, `php`, `py`, `rb`, `ts`. Plus YAML in-proc.
- **Job status states** live in Redis.

**Important correction (was in last year's deck):** Java is **not** in the frontends list. Swap the Java logo → YAML (real, in-proc support).

---

## 6. One-Liners to Have in Pocket

Ranked roughly by memorability. Pick 3–4 to actually memorize; the rest are safety net for Q&A.

**Tier 1 openers / closers:**

- *"The LLM shouldn't be a compiler."*
- *"Amortize once. Query many. Spend tokens on insight, not on book-keeping."*
- *"Pre-compute the boring. Save tokens for the interesting."*
- *"Every LSP already does this. We're just doing it for security."*
- *"It's the difference between grep and Elasticsearch."*

**Per-slide closers:**

- **endpoints:** *"Frameworks scatter endpoints across files. We reassemble them once, at parse time."*
- **fqns:** *"Names have config files. We read the config files once, at parse time."*
- **call sites:** *"In structurally-typed languages, `implements` is a **theorem**. We prove it once, at parse time."*
- **Trio callback (Tier 1 closer):** *"eager pre-processing = every IDE, every search engine, every database index. We're just doing it for security."*

**Language-diversity throwaways (verbal asides, quiet credibility):**

- *"Four of the seven languages we support have this indirection pattern, and the other three each opt out for a different reason."*
- *"tsconfig is a chain; composer is a fan-out."*
- *"In the TS/JS world there are literally five different files that can define an alias, and a real project usually has several of them active at once."*
- *"In nominal-typed languages, `implements` is a manifest. In structurally-typed languages, `implements` is a theorem."*

**Auth / composition:**

- *"endpoints × fqns × call sites × auth = **Broken Access Control** = OWASP #1."*
- *"AppSec is about security mechanisms — which are shared across PL and framework. The right API should be agnostic to both."*

**Big-O / FinOps (understated):**

- *"Eager pre-processing is O(1) amortized per query. Lazy LLM-only is O(codebase-size) per query."*

**Meta / thesis:**

- *"I'm not claiming a silver bullet. I'm claiming the right level of abstraction."*
- *"AppSec is a **pattern** problem. The **mechanism** is a language detail."*

---

## 7. Naming Conventions & Terminology

**Locked terminology:**

- `predefined` (one word) → `adaptive`.
- `unification, algorithms, facts, api` — the "better primitives" four-step.
- `Qualified Names (FQNs)` — drop "Fully" on-screen; keep in acronym; narrate on first use.
- `overload` (short for "context overload") — Tier 1 middle term.
- `cornerstones` — Tier 2 middle term.
- `barrel files` — mention verbally as an *"if you might have heard"* aside; keep `indirection` on-screen.
- `systematic and reusable` — safe alternative to "automated" in Q&A.
- `share infrastructure, isolate runtime state` — the DI-pattern one-liner.

**Terms explicitly rejected:**

- `automated` (Q&A hazard).
- `edit-post` as example endpoint (legacy, not Symfony-routed).
- Naming Semgrep / CodeQL directly.

**Terms pending decision:**

- `native types` (Slide 11 row 3) — flagged as overloaded in JS/TS; alternatives `built-ins` or `globals`. **Not yet decided.**

**Canonical citations to name-drop verbally:**

- **ReAct** — Yao et al., 2022.
- **SWE-agent / ACI** — Yang et al., 2024.
- **Language Server Protocol** — Microsoft, 2016.
- **12-Factor App VI ("Processes")** — Heroku / Wiggins, 2011.
- **EJB / Java Spring / .NET Core scopes** — historical lineage for DI (throwaway).

---

## 8. Open Decisions

- [ ] Slide 11 row 3 terminology: `native types` vs `built-ins` vs `globals`.
- [ ] Slide 12 layout (call sites): recommended content is drafted in §3 above; visual layout still TBD.
- [ ] Slide 13 (Tier 1 closer): text drafted; visual layout TBD.
- [ ] Slide 15 (auth): use phpbb + formbricks snippets side-by-side; visual layout TBD.
- [ ] Slides 16 (crypto), 17 (polarity): full content TBD. Polarity term needs one-paragraph definition.
- [ ] Slide 18 (demo): decide live-run vs recorded video vs static screenshots.
- [ ] Slide 19 (generalize): choose 2–3 HackerOne targets to name-check.
- [ ] Optional: implement Symfony YAML resolver in `utils.pl` before the talk — bounded Haskell/Prolog work, not required for the demo but would strengthen the "utils.pl absorbs kinetic energy" claim on Slide 10.
- [ ] Optional: swap Java logo → YAML logo in the "supported languages" visual (if that slide is being reused from last year's deck).

---

## 10. Next Session — Live Go Example Hunt

**Current focus.** Slide 12 (call sites) needs 1–2 real-world Go code snippets that concretely demonstrate the **structural static** interface-satisfaction paradigm. The rest of the slide (framing, resolution-model table, one-liners) is already drafted in §3. What's missing is the *visual proof* — a snippet on screen that grep can't statically decide.

**Style constraint:** each snippet must survive ≤ 8 lines on screen + ≤ 60 seconds of verbal delivery.

**What to look for (ranked by slide value):**

1. A struct in package A that satisfies an interface defined in package B, **where A does not import B**. The canonical "eligibility is inferred by the compiler, not declared by the programmer" moment.
2. A pointer-vs-value receiver asymmetry — the same type satisfying or failing an interface depending on `T` vs `*T`. Grep's blind spot.
3. Interface promotion via struct embedding — a type gaining interface satisfaction with zero visible method definitions in its own body.
4. *(Bonus)* A generic constraint (`func Foo[T Reader](x T)`) — for the type-theory literate in the audience.

**Candidate Go repos** (roughly ordered by expected signal density):

| repo | why it's a good hunting ground |
|---|---|
| **Go standard library** | `io.Reader` / `io.Writer` are *the* paradigmatic example. `bytes.Buffer`, `strings.Reader`, `os.File`, `net.Conn`, `bufio.Reader` all satisfy `io.Reader` via completely disjoint code paths. **Recommended starting point.** |
| Kubernetes (`k8s.io/kubernetes`) | massive interface-heavy code; `runtime.Object`, informers, `client-go` |
| Docker (`moby/moby`) | container plumbing, lots of `io.Reader/Writer` + custom interfaces |
| Prometheus (`prometheus/prometheus`) | metric collectors as interface implementations; mixed receiver styles |
| Terraform (`hashicorp/terraform`) | provider interfaces, plugin patterns |
| Cobra (`spf13/cobra`) | CLI framework, well-known, smaller than the giants above |
| dhscanner's own Go frontend | eat-our-own-dogfood credibility if suitable examples exist in-tree |

**Success criteria for a slide-worthy snippet:**

- Fits in ≤ 8 lines on screen.
- **No visible `implements`-like marker** — that's the whole point.
- Verbally explainable in ≤ 60 seconds.
- *Ideal (not required)*: pairs naturally with a Java equivalent for a side-by-side layout showing the paradigm difference.

**What to bring back into this file:**

- 1–2 chosen snippets with file paths + line numbers, added to §3 Slide 12 layout.
- (Optional) paired Java equivalent.
- Updated Open Decisions checkbox for Slide 12 layout.
- New Change Log entry.

**Bootstrap prompt for the fresh session** (paste at the top of a new chat):

> *"I'm preparing my OWASP-IL 2026 talk on `dhscanner`. Please read `docs/OWASP26_NOTES.md` first — especially §3 Slide 12 (call sites) and §10 (Next Session — Live Go Example Hunt). Then help me find 1–2 real-world Go code snippets demonstrating structural static interface satisfaction for that slide. Start with the Go standard library (`io.Reader` implementations) unless you find something stronger elsewhere."*

---

## 11. Change Log

- **2026-09-12** — Initial persist of full session state. Deck structure locked through Slide 8; Tier 1 layout locked for Slides 10–11; Tier 1 trio decision (endpoints / fqns / call sites) locked; Tier 2 trio decision (auth / crypto / polarity) tentatively locked; call-sites Go-structural-typing angle chosen; LSP / eager-preprocessing framing chosen for Tier 1 closer.
- **2026-09-12** — Renamed `OWASP26.md` → `OWASP26_NOTES.md`. Reframed the document from "talk preparation reference" to a **dual-purpose talk + direction document**. The talk is the pretext; the direction (KB primitive design, eager-preprocessing thesis, cross-language/framework unification, `utils.pl`'s role as kinetic-to-potential energy converter) is the durable content.
- **2026-09-12** — Added §10 "Next Session — Live Go Example Hunt" to make the handoff to a fresh session explicit. Renumbered Change Log → §11. Next session's task: pick 1–2 real-world Go snippets that demonstrate structural static interface satisfaction, for Slide 12.
- **2026-09-14** — Landed [PR #65](https://github.com/OrenGitHub/dhscanner.runner/pull/65) (2×2 grid + `AuthEvidence` tagged union pipeline: kbapi 1.0.7 + queryengine 1.0.53).
- **2026-09-15** — Landed [PR #66](https://github.com/OrenGitHub/dhscanner.runner/pull/66) (round-1 recon widening: removed tier-1 name catalogs → `:- dynamic` decls, widened Next.js POST recognizer to accept `'req'|'request'` + `NextRequest|nodejs.Request`, queryengine 1.0.54). Delta on `formbricks` v3.16.0: unauth POST 2 → 18, auth POST 1 → 2 (100% precision on both). Snapshot-tested in CI against [`tests/expected/facts/formbricks/post_endpoints.txt`](../tests/expected/facts/formbricks/post_endpoints.txt). Dockerfile apt-race fix bundled to stabilize queryengine CI.

---

## 12. Next Session — Round-2 Queries (Within-Bucket Ranking)

**Where we left off.** Round-1 recon (the 2×2 grid `{auth, pre-auth} × {GET, POST}`) is landed, snapshotted, and CI-gated on `formbricks`. Precision is 100% on both AUTH POST and AUTH GET; miss taxonomy is documented in [`docs/AUTH_POST_RECALL_GAPS.md`](AUTH_POST_RECALL_GAPS.md). This is a **complete first-query artifact** — everything below is the second wave the LLM agent fires once it's *inside* a bucket.

**The framing.** Round-1 answered *"which endpoints exist and which are gated?"*. Round-2 answers *"which of these gated / ungated endpoints are actually dangerous?"*. Every round-2 query is a **compositional refinement** — it takes a round-1 result as input and adds one dataflow / structural predicate on top.

### Query catalog (all composable on top of what's already shipped)

Within the 18 pre-auth POST bucket, the agent asks *"which ones reach a dangerous sink?"*:

| # | Predicate name (tentative) | Sink family | AuthEvidence-like tag |
|---|---|---|---|
| 1 | `reaches_sql_sink` | `prisma.$queryRaw`, `mysql.query`, `.exec(SQL)` | `BySqlExecutionCall` |
| 2 | `reaches_command_exec` | `child_process.exec`, `spawn(shell:true)` | `ByCommandExecCall` |
| 3 | `reaches_ssrf_sink` | `fetch(user_url)`, `http.get(user_url)` | `BySSRFHttpCall` |
| 4 | `reaches_file_write` | `fs.writeFile(user_path)` | `ByFileWriteCall` |
| 5 | `reaches_deserialize` | `JSON.parse(req.body)`, `yaml.load` | `ByDeserializeCall` |

Within the 2 auth POST bucket (and any future auth POST once HOC-unwrap lands), the agent asks *"which are missing an ownership check?"* — this is the **BOLA** signal:

| # | Predicate name (tentative) | What it checks |
|---|---|---|
| 6 | `missing_ownership_check` | Handler reads `params.[resourceId]` but never calls `checkOwnership` / `hasAccess` (the classic BOLA gap) |
| 7 | `reaches_mass_assignment` | Spreads `req.body` directly into a DB update (`prisma.x.update({ data: { ...body } })`) |

### Shipping pattern per query (mirrors this session)

Each round-2 query is a **leaf-add** in the exact same shape as `AuthenticatedHttpPostHandlerRequestObject`:

1. New `utils_*` predicate in [`utils.pl`](../dhscanner.core/dhscanner.service.queryengine/utils.pl) composed on top of the existing round-1 predicates.
2. New Haskell type in [`Content.hs`](../dhscanner.packages/dhscanner.kbapi/src/Content.hs) + new query variant in [`Kbapi.hs`](../dhscanner.packages/dhscanner.kbapi/src/Kbapi.hs) (kbapi minor bump).
3. New handler module + Prolog template in [`dhscanner.service.queryengine/src`](../dhscanner.core/dhscanner.service.queryengine/src) + [`templates`](../dhscanner.core/dhscanner.service.queryengine/templates).
4. New CI snapshot in [`tests/expected/facts/formbricks/`](../tests/expected/facts/formbricks) diff-tested against the formbricks KB.

The AuthEvidence tagged union pattern is the template: each query emits **evidence tags** rather than verdicts, so the LLM agent frames its findings as *"we cite structural evidence"* not *"we assert vulnerability"*.

### Bootstrap prompt for the fresh session (paste at top of new chat)

> *"I'm continuing the `dhscanner` OWASP-IL 2026 work. Please read `docs/OWASP26_NOTES.md` §12 (Next Session — Round-2 Queries) and `docs/AUTH_POST_RECALL_GAPS.md`. Round-1 recon is landed in [PR #66](https://github.com/OrenGitHub/dhscanner.runner/pull/66). Let's start with query #1 (`reaches_sql_sink`) — sketch the `utils.pl` predicate on top of the existing `utils_unauthenticated_http_post_handler_request_object/3`, then run it against the formbricks KB to see the initial hit count. Use the existing `2x2 grid` shipping pattern (kbapi type + queryengine handler + CI snapshot)."*

### Open decisions for round-2

- [ ] Do we ship queries **one per PR** (safer, easier reviews) or **batched into a `Round2QuerySuite` variant** (fewer commits, shared boilerplate)?
- [ ] For BOLA (#6), do we treat `params.[resourceId]` extraction as a **new KB primitive** (kbgen extractor) or a **structural detector** on top of existing `kb_arg_i_for_call` facts?
- [ ] Should the round-2 CI snapshots go under `tests/expected/facts/formbricks/round2/` (new subfolder) or stay flat next to the round-1 file?
- [ ] Whether to gate round-2 queries on **HOC-unwrap** landing first (would give us realistic auth bucket sizes) or ship round-2 first and let HOC-unwrap expand the input set later.

- **2026-09-15** — Added §12 "Next Session — Round-2 Queries" with the 7-query catalog, the leaf-add shipping pattern, and the bootstrap prompt for the fresh session. Round-1 recon considered complete; next session's task: pick query #1 (`reaches_sql_sink`) and ship it end-to-end.
