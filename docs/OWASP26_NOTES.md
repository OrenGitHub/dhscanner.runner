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

**Two-part structure** (settled 2026-09-18):

- **Opening act — workflow demonstration on a *safe* endpoint.** `PUT /api/v2/management/contacts/bulk` (see §5.11). Exercises the coarse-to-fine loop end-to-end: CF-reach enumerates 6 SQL sinks; tier-1 categorical predicate clears 4; tier-2 structural predicate clears the remaining 2 raw-tagged residues (no `Prisma.raw` in interpolations); LLM evicts the endpoint with a well-founded *"safe, move on"* verdict. **No DF invoked at any point.** Great honesty payoff: *"the first candidate we look at turns out safe. That's not a limitation — it's the point."*
- **Finale — vulnerability discovery on a *paired* endpoint.** formbricks CWE-22 path traversal via bucket-C H1↔H2 pair-vertex discovery (§5.5 + §4.8 + §13). Fix commit `9d84bc0c…`. Amplifier: **M=4 sibling call-sites** to `validateAndResolvePath` — one flawed helper, four call-sites all inheriting the flaw. Big story.

The opening act lands the *workflow*; the finale lands the *finding*. Two beats, one demo.

**Prerequisites for the opening act (Assignments 1, 3, 4 in §14):** generic HOC recognizer (surfaces `PUT`), bounded CF-reach kbapi predicate (the query), sink-family hierarchy (tier-1/tier-2 clearance). Assignment 2 (`tx.*` inside `$transaction`) is DEFERRED but load-bearing for the opening act's 6-sink count.

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

### 4.8 Endpoint taxonomy: pre-auth / authenticated / capability-verified

Three-way, not two-way. The dividing line between "authenticated" and "capability-verified" is **provenance of the gate token**, not "how much crypto is involved":

| bucket | gate provenance | first-pass enumeration |
|---|---|---|
| **A. Pre-auth**            | no gate                                                            | **yes** |
| **B. Authenticated**       | gate issued *out-of-band* (login, OAuth, API-key admin)            | **yes** |
| **C. Capability-verified** | gate issued *by another endpoint in this same codebase*            | **no — surfaced only by cross-endpoint pairing** |

Bucket C is deliberately excluded from the first-pass grid: analyzing a C endpoint in isolation is meaningless — its input surface (the capability) is not attacker-controlled unless its pair has a bug, and surfacing it in the first pass only generates noise. C endpoints enter the LLM's queue **as pair-vertices**, when some already-explored H1's response URL literal KB-resolves to them. Full story + implementation plan: §13. Cross-repo evidence for the pattern's generality: §5.8.

**Working name only.** "Capability-verified" is a placeholder — the concept it names (**possession-of-token-issued-by-another-endpoint = authorization**) predates the term and deserves a better label before it lands on a slide. Alternatives to explore: *delegated-authority*, *pair-authorized*, *cross-endpoint-gated*. (*Signed-handoff* is a viable name but only for the cryptographic subset — see §5.9 for opaque-token instances.)

**Three dimensions of variation across instances of bucket C** — all KB-visible, invariant to the exact mechanism used:

- **Capability mechanism** — stateless cryptographic (HMAC / JWT — §5.5, §5.8) *or* stateful opaque DB-backed random token (64-char random string in §5.9, UUID4 primary key in §5.10). The invariant is *unforgeability* + *possession-implies-authorization*, not "signed."
- **Delivery channel** — HTTP response body (§5.5, §5.8) *or* out-of-band (email — §5.9, §5.10). The KB-visible edge is *H1's code constructs the URL literal + binds the capability*; how that URL then reaches the client is downstream.
- **Pre-auth-signaling idiom** (H2 side — how the framework declares "no session consulted here") — derived-via-dataflow (Next.js, §5.5), derived-via-call-graph (Gitea, §5.8), attribute + dataflow (Concrete CMS, §5.9), or **declarative decorator** (`@login_not_required` in Django 5.1+, §5.10). Weblate's is the cheapest to detect — one class-decorator attribute lookup, no dataflow needed. Every framework has its own idiom; the KB must absorb all four (and any new ones we find). This dimension directly informs the recognizer-widening work planned in [`AUTH_POST_RECALL_GAPS.md`](AUTH_POST_RECALL_GAPS.md).

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
- **Pair structure:** the vuln is an H1↔H2 capability-verified pair (see §4.8 for taxonomy). H2 (byte-sink) is not in the first-pass endpoint enumeration by design — it enters the LLM's queue only when H1's response URL literal resolves to it. Two independent cross-repo instances of the same pair pattern documented in §5.8 (gitea LFS + Actions v4).
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

### 5.8 gitea — Capability-verifier endpoint pairs (bucket-C generality evidence)

Two independent instances of the same H1↔H2 pattern in a single well-maintained repo, using two different signing mechanisms — cross-repo confirmation that formbricks §5.5 is not idiosyncratic and that bucket C (§4.8) is a real recurrent class.

**Instance 1 — Git LFS (JWT capability in `Authorization` header).**

| role | route / callable | file:line |
|---|---|---|
| H1 (signer)       | `POST .../info/lfs/objects/batch` → `BatchHandler`             | `gitea/services/lfs/server.go:192` |
| H2 (byte sink)    | `PUT .../info/lfs/objects/{oid}/{size}` → `UploadHandler`      | `gitea/services/lfs/server.go:306` |
| capability build  | `buildObjectResponse` — sets `Actions["upload"].Header["Authorization"]` | `gitea/services/lfs/server.go:488-521` |
| capability verify | `handleLFSToken` — HMAC-SHA256 JWT parse against `setting.LFS.JWTSecretBytes` | `gitea/services/lfs/server.go:577-618` |
| router pairing    | side-by-side `m.Post`/`m.Put` binding                          | `gitea/routers/common/lfs.go:17-22` |

**Instance 2 — Gitea Actions Artifacts v4 (URL-query HMAC capability).**

| role | route / callable | file:line |
|---|---|---|
| H1 (signer)       | internal caller of `buildArtifactURL` — HMAC over query params | `gitea/routers/api/actions/artifactsv4.go:163-177` |
| H2 (byte sink)    | `PUT .../UploadArtifact?sig=…` → `uploadArtifact`              | `gitea/routers/api/actions/artifactsv4.go:395` |
| capability verify | `verifySignature` — `hmac.Equal` + expiry check                | `gitea/routers/api/actions/artifactsv4.go:217-241` |

**Framework invariance.** Different language (Go vs TS), different router (Gitea chi-derived twice vs Next.js App Router), different capability format (JWT vs URL-HMAC vs form-field HMAC). **Same shape.** Combined with formbricks §5.5, that's three data points across two independent repos.

**Q&A ammo.** The LFS maintainers themselves reason about *capability scope across the pair* in a prose comment at `gitea/services/lfs/server.go:261-270` (`// The object exists in the content store but is not linked to this repo. Do not auto-link it based on cross-repo access…`). Exactly the class of pair-property the query loop is designed to make explicit — *"the maintainers already know this class exists; they defend it in prose. We want to defend it in queries."*

### 5.9 concretecms — Capability-verifier endpoint pairs (opaque-token + email-delivery variant)

Two independent instances of the H1↔H2 pattern in the same auth controller — with **two structural variations from §5.8** that widen bucket C (§4.8): the capability is a stateful DB-backed opaque token rather than a stateless cryptographic assertion, and delivery is out-of-band via email rather than in the HTTP response body. Third language (PHP) after TS (§5.5) and Go (§5.8).

**Shared primitive.** Both instances build on `ValidationHash` — a random 64-char string INSERTed into `UserValidationHashes` (uID, uHash, uDateGenerated, type), verified by DB lookup with no session touch:

| role | callable | file:line |
|---|---|---|
| capability build     | `ValidationHash::add`                    | `concretecms/concrete/src/User/ValidationHash.php:53-64` |
| capability verify    | `ValidationHash::getUserID` / `isValid`  | `concretecms/concrete/src/User/ValidationHash.php:74-83`, `111-116` |

**Instance 1 — Password reset (H1 pre-auth, H2 pre-auth).**

| role | callable | file:line |
|---|---|---|
| H1 (issuer)      | `forgot_password()` — takes email, generates hash, constructs URL, emails to user           | `concretecms/concrete/authentication/concrete/controller.php:216-317` |
| URL construction | `View::url('/login', 'callback', ..., 'change_password', $uHash)`                            | `concretecms/concrete/authentication/concrete/controller.php:279-285` |
| delivery         | mail template `forgot_password`                                                              | `concretecms/concrete/authentication/concrete/controller.php:299-302` |
| H2 (verifier)    | `change_password($uHash)` — verifies capability, `$ui->changePassword(...)`, deletes token   | `concretecms/concrete/authentication/concrete/controller.php:319-355` |

**Instance 2 — Email verification (H1 called by registration flow, H2 pre-auth).**

| role | callable | file:line |
|---|---|---|
| H1 (issuer)      | `StatusService::sendEmailValidation($user)`                                                  | `concretecms/concrete/src/User/StatusService.php:27-44` |
| capability build | `UserInfo::setupValidation()` — inserts fresh hash                                           | `concretecms/concrete/src/User/UserInfo.php:679-692` |
| delivery         | mail template `validate_user_email`                                                          | `concretecms/concrete/src/User/StatusService.php:42-43` |
| H2 (verifier)    | `v($hash = '')` — verifies hash, `$ui->markValidated()` + `triggerActivate('register_activate', USER_SUPER_ID)` | `concretecms/concrete/authentication/concrete/controller.php:458-473` |

**Framework invariance across §5.5 + §5.8 + §5.9.** Three languages (TS / Go / PHP), three routers (Next.js App Router / Gitea chi-derived / Concrete CMS single-page controllers), four capability mechanisms (form-field HMAC / JWT / URL-query HMAC / opaque DB token), two delivery channels (HTTP response body / email). **Same shape.** The invariant that survives every instance is *H1's code constructs a URL literal that resolves to H2 and binds a capability* — everything downstream of that emission varies.

**Note on pre-auth H1.** Both H1 and H2 in Instance 1 are pre-auth (no login required — that's the point of a password-reset flow). This is subtly different from the formbricks / gitea instances where H1 is authenticated. It means the discovery edge is *pre-auth H1 → capability-verified H2*, which is still a valid instance of the bucket-C pattern — the queue-dynamics story from §13 applies unchanged, just with a pre-auth H1 at the seed. Good complementary data point: bucket C's pair edges can originate from either A or B.

### 5.10 weblate — Capability-verifier endpoint pair (Django decorator-declared H2)

Fourth-language instance of the H1↔H2 pattern (Python / Django), and the cleanest bucket-C H2 signal in the evidence base — H2 declares its pre-auth status via a Django 5.1+ class-level decorator (`@login_not_required`), no dataflow needed.

**Instance — User invitation flow (H1 authenticated, H2 pre-auth via decorator).**

| role | callable | file:line |
|---|---|---|
| H1 (issuer)          | `Invitation.send_email()` (called from `InvitationView.post(action='resend')` at line 282 and from admin invite-create flows in `weblate/wladmin/views.py` + `weblate/trans/views/acl.py`) | `weblate/weblate/auth/models.py:2034-2056` |
| capability build     | UUID4 primary key on `Invitation` model (`models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)`) | `weblate/weblate/auth/models.py:1951` |
| URL construction     | `reverse("invitation", kwargs={"pk": self.uuid})`                                                | `weblate/weblate/auth/models.py:2018-2019` |
| delivery             | `send_notification_email(..., "invite", context={"invitation": self, ...})`                       | `weblate/weblate/auth/models.py:2049-2056` |
| H2 (verifier)        | `InvitationView(DetailView)` — `@method_decorator(login_not_required, name="dispatch")` at class level; verifies via `DetailView.get_object()` → `Invitation.objects.get(pk=<uuid>)` | `weblate/weblate/auth/views.py:209-259` |
| expiry check         | `Invitation.is_expired()` — timedelta against `settings.AUTH_TOKEN_VALID`                        | `weblate/weblate/auth/models.py:2021-2024` |
| route wiring         | path-name `"invitation"` registered via `InvitationView.as_view()`                               | `weblate/weblate/accounts/urls.py:98` |

**The novel structural signal.** `@login_not_required` (Django 5.1+) is a class-level, purposeful, declarative opt-out from `LOGIN_REQUIRED_MIDDLEWARE`. It's the most explicit *"no session consulted here"* marker any of the four repos has. A `utils.pl` recognizer for this pattern is a single-fact match:

```prolog
utils_pre_auth_by_login_not_required_decorator(ViewClass) :-
    kb_class_decorator_call(ViewClass, 'django.contrib.auth.decorators.login_not_required').
```

Combined with a capability-shape lookup in the class body (a `Model.objects.get(pk=<param>)` call where the pk argument flows from a request path parameter), that's a full bucket-C H2 recognizer with **no dataflow needed**. Cheapest H2 detection path in the evidence base — directly relevant to the recognizer-widening work in [`AUTH_POST_RECALL_GAPS.md`](AUTH_POST_RECALL_GAPS.md) root cause #1.

**Q&A ammo layer 3 — Weblate defends against the pair-scope bug in code.** Same class of concern as gitea's maintainer-prose defense (§5.8's Q&A ammo bullet), but Weblate handles it in *actual flow control*:

```221:245:c:\Users\tuna_\GitHub\weblate\weblate\auth\views.py
if request.user.is_authenticated:
    request.session.pop("invitation_link", None)
    if not self.object.matches_user(request.user):
        messages.error(
            request,
            gettext(
                "This invitation can be accepted only by the e-mail address "
                "chosen by the inviter; it can't be used by your account."
            ),
        )
        return redirect_param("profile", "#account")
    return None
```

**Three independent security-conscious open-source projects** now form a Q&A pattern:

- **formbricks** *fixed* the pair-scope bug after disclosure (§5.5).
- **gitea** *documents* it in a prose comment (§5.8).
- **weblate** *handles* it in flow control (§5.10).

Deck-facing framing: *"we're not inventing this class of bug — we're inventing the analyzer that finds it before the maintainers have to."*

**Framework invariance across §5.5 + §5.8 + §5.9 + §5.10.** Four languages (TS / Go / PHP / Python), four framework families (Next.js App Router / Gitea chi-derived / Concrete CMS single-page / Django `DetailView`), five capability mechanisms (form-field HMAC / JWT / URL-query HMAC / opaque 64-char string / UUID4), two delivery channels (HTTP response body / email), four pre-auth-signaling idioms (dataflow-derived / call-graph-derived / attribute + dataflow / declarative decorator). **Same shape.** The invariant that survives every instance remains *H1's code constructs a URL literal that resolves to H2 and binds a capability*.

### 5.11 formbricks — Bulk contacts PUT (opening demo endpoint)

Chosen 2026-09-18 as the **opening pedagogical demo endpoint** — the CWE-22 seed vuln (§5.5) remains the finale. Selected after evaluating endpoint #11 (`/organizations/[organizationId]/users` — the first candidate) and finding its two SQL sinks are trivially tier-1-cleared, too shallow a story for the coarse-to-fine narrative. This endpoint exercises **both tier-1 and tier-2 clearance predicates productively on one handler**, closing the demo loop with no tier-3 (DF) invocation.

- **Route:** `PUT /api/v2/management/contacts/bulk`
- **Handler:** `formbricks/apps/web/modules/ee/contacts/api/v2/management/contacts/bulk/route.ts:9`
- **Helper (transitive dispatch):** `formbricks/apps/web/modules/ee/contacts/api/v2/management/contacts/bulk/lib/contact.ts` (function `upsertBulkContacts`)
- **Recognizer note:** verb is **PUT**, not POST — absent from [`tests/expected/facts/formbricks/post_endpoints.txt`](../tests/expected/facts/formbricks/post_endpoints.txt) snapshot; surfaces only after the Assignment 1 recognizer (§14) widens beyond POST.

**Full inventory: 6 Prisma sinks reachable from PUT via `upsertBulkContacts`:**

| # | Line | Sink call | Family | Tier-1 clears? |
|---|---:|---|---|---|
| 1 | 45 | `prisma.contactAttribute.findMany` | Prisma object-form | ✓ |
| 2 | 60 | `prisma.contact.findMany` | Prisma object-form | ✓ |
| 3 | 83 | `prisma.contactAttributeKey.findMany` | Prisma object-form | ✓ |
| 4 | 304 | `tx.contact.createMany` | Prisma object-form | ✓ |
| 5 | 274 | `tx.$queryRaw` INSERT `ContactAttributeKey` | Prisma raw-tagged | ✗ needs tier-2 |
| 6 | 342 | `tx.$executeRaw` INSERT `ContactAttribute` | Prisma raw-tagged | ✗ needs tier-2 |

(Line 229 `prisma.$transaction([...])` is a batching wrapper, not a sink — captured but classified as `prisma_batching_wrapper` in the taxonomy.)

**Tier-2 zoom-in on the 2 raw-tagged residues:** every `${...}` interpolation is `Prisma.sql`-wrapped; no `Prisma.raw(...)` appears anywhere. Prisma parameterizes all interpolations by construction (even nested inside `Prisma.sql\`...\`` — array elements become individual bind parameters). Purely local AST inspection at each sink site clears both — **no DF invocation anywhere in the analysis**.

**Complete analytical pipeline on this endpoint — zero dataflow:**

1. **CF-reach**: `PUT` → *[HOC-recognizer shortcut, Assignment 1]* → handler lambda → `upsertBulkContacts` → 6 sink call sites.
2. **Tier-1 categorical** (`sink_family_safe(_, prisma_object_form)`): clears 4 of 6 in one predicate.
3. **Tier-2 structural** (`sink_family_safe(_, prisma_raw_tagged_no_raw_interpolation)`): clears both residues.
4. **Verdict:** safe. Endpoint evicted from the queue.

**Why this endpoint over the seed vuln for the OPENING slot** (both stay in the deck, different narrative purpose):

- The seed vuln (§5.5) demonstrates bucket-C pair-vertex discovery — H2 (byte-sink) surfaces via H1's URL emission. That's the finale beat.
- This endpoint demonstrates the *coarse-to-fine loop itself* — tier-1 + tier-2 firing productively on the same endpoint, both clearing the residue, no vuln to reveal. Pure workflow demonstration.
- Honesty payoff: *"the first candidate we look at turns out safe. The workflow correctly clears it. That's not a limitation — it's the point of the whole talk. Not every candidate is a vuln, and correct 'safe, move on' is a first-class capability."*

**Recognizer meta-story worth pinning** (see also `AUTH_POST_RECALL_GAPS.md` root cause #1): the endpoint uses `authenticatedApiClient({handler: ...})` — the HOC-wrapper pattern that today's recognizer doesn't unwrap. Under Assignment 1 (§14) the recognizer widens generically for any HOC-shape entry-point export across all HTTP verbs; this endpoint appears in the enumeration as a byproduct of that widening. The auth classification is separately handled by another catalog (out of scope for the opening demo); this endpoint stays labeled pre-auth after Assignment 1 lands, which is a *severity-mislabel only, conservative direction* — acceptable for the research talk framing (see §14 "known limits").

**Full engineering prerequisites (§14):**
- Assignment 1 (generic HOC recognizer) — enumerates the PUT verb.
- Assignment 3 (bounded CF-reach as kbapi predicate) — the query the LLM fires.
- Assignment 4 (sink-family hierarchy `sql`/`sql_prisma`/`sql_prisma_object_form`/`sql_prisma_raw_form` + tier-1/tier-2 clearance predicates) — closes the loop.
- Assignment 2 (Prisma DB-call capture, including `tx.<model>.<op>` inside `$transaction` callbacks) — DEFERRED, needs chat before scoping. Without it, 4 of the 6 sinks are invisible to Assignment 4's classifier.

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
- **2026-09-16** — Formalized the endpoint taxonomy as **three-way** (pre-auth / authenticated / capability-verified) — new §4.8 with *provenance of the gate token* as the dividing line between B and C, and bucket C deliberately excluded from first-pass enumeration. Added §5.8 (gitea LFS + Actions v4 as two independent cross-repo instances of the H1↔H2 pair pattern, plus a maintainer-comment "capability scope" prose citation for Q&A). Added §13 (bucket C plan — queue-dynamics story, coarse-to-fine framing with the CF-reach/DF split justification and call-graph soundness caveat, `precompute-at-kbgen` design constraint, three API adds, signal-value ranking with the response-status-vocabulary 2×2, and the naming caveat that "capability-verified" is a placeholder). Cross-link bullet added to §5.5. Next session's task: sketch `utils_capability_verifier_call/2` end-to-end.
- **2026-09-16** (2nd) — Extended bucket C evidence to a **third language** — added §5.9 (concretecms password-reset + email-verification pairs using stateful DB-backed `ValidationHash` tokens delivered via email — two orthogonal variations from §5.8 that widen the concept). §4.8's definition rewording drops the "signed" adjective (*possession-of-**token**-issued-by-another-endpoint*) and adds two named dimensions of bucket-C variation: **capability mechanism** (crypto vs opaque) and **delivery channel** (HTTP-body vs email). §13's `capabilityShape` enum extended with `OpaqueDbToken`; new `deliveryChannel` field added to `emitsCapabilityToHandler`. Framework-invariance evidence now stands at **three languages / three routers / four capability mechanisms / two delivery channels** across four independent H1↔H2 pair instances.
- **2026-09-16** (3rd) — **Fourth-language** bucket-C evidence — added §5.10 (weblate invitation flow using UUID4 capabilities delivered via email, verified by `InvitationView(DetailView)` decorated with Django 5.1+ `@login_not_required`). §4.8 extended from two to **three dimensions of variation** with a new **pre-auth-signaling-idiom** axis (dataflow-derived / call-graph-derived / attribute + dataflow / **declarative decorator**). Weblate's `@login_not_required` is the cheapest H2 signal in the evidence base — one class-decorator lookup, no dataflow — and directly informs the recognizer-widening work in `AUTH_POST_RECALL_GAPS.md` root cause #1. Framework-invariance now stands at **four languages / four framework families / five capability mechanisms / two delivery channels / four pre-auth-signaling idioms** across five independent H1↔H2 pair instances. Q&A layer 3 added: three independent open-source projects (formbricks / gitea / weblate) each defend against the pair-scope bug in different ways (fix / prose comment / flow control).
- **2026-09-18** — Deep session on demo-endpoint selection and the coarse-to-fine loop's concrete engineering. Selected §5.11 opening act (`PUT /contacts/bulk`) after evaluating endpoint #11 (`/organizations/[organizationId]/users`) and finding its two SQL sinks trivially tier-1-cleared. Endpoint #18 exercises **both tier-1 and tier-2 productively** with 6 Prisma sinks (4 object-form + 2 raw-tagged, all safe by structural inspection — no DF invoked). Added §5.11 (full sink inventory + clearance chain), §14 (four assignments — HOC recognizer, bounded CF-reach kbapi predicate, sink-family hierarchy; Assignment 2 for `tx.*` inside `$transaction` deferred), and updated Slide 18 in §3 to reflect the two-part demo structure (opening act = workflow, finale = finding). Crystallised the **pattern-directed shortcut heuristic** that unlocks Assignment 1 — recognise the *outer framework idiom* at caller-side syntactic shape (`export const <VERB> = async (req) => <ANY-CALLEE>(<dict-literal-with-callable>)`), skip HOF flow through wrapper internals. Legitimacy: industry-standard SAST convention (Semgrep, CodeQL, Datadog all cheat the same way). Four known-limit categories framed as *"community-fixable modular gaps"* for the research-talk narrative. `AUTH_POST_RECALL_GAPS.md` root cause #1 updated to reflect the generic-pattern approach + verb widening across all HTTP methods (was originally scoped as `authenticatedApiClient`-specific).

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

---

## 13. Next Session — Bucket C (capability-verified endpoints)

**Where we left off.** §12 (Round-2 queries) implicitly assumed the 2×2 grid `{auth, pre-auth} × {GET, POST}` was the full first-pass endpoint surface. Session 2026-09-16 expanded the taxonomy to **three buckets** (formalized in §4.8): pre-auth (A), authenticated (B), and **capability-verified (C)**. Bucket C is a categorically distinct gate class whose authenticator is *another endpoint in the same codebase* — not middleware, not a session store, not an out-of-band credential. It's the gate type on the byte-sink side of the H1/H2 vulnerability class from [`demo/formbricks.md`](../demo/formbricks.md) (see §5.5), and it recurs cleanly in two independent gitea subsystems (§5.8).

**The framing.** Bucket C is deliberately **excluded from the first-pass endpoint enumeration**. Analyzing a C endpoint in isolation is meaningless — its input surface (the capability) is not attacker-controlled unless its pair has a bug — and surfacing it in the first pass only generates noise. C endpoints enter the LLM's queue **as pair-vertices**, when some already-explored H1's response URL literal KB-resolves to them. The queue therefore grows *monotonically as cross-endpoint pair edges are discovered*, never as re-scoring shuffles it — pure BFS semantics on a graph that grows during traversal.

### Queue-dynamics story (slide-ready)

| turn | agent action | H2 status |
|---:|---|---|
| 1     | *2×2 grid: A ∪ B, {GET, POST}*                                                        | **not in the set** |
| 2     | *Triage A ∪ B by URL + path params + handler complexity + response status vocabulary* | absent |
| 3     | *CF-reach screen on shortlist*                                                        | absent |
| 4–N   | *Fine-pass DF on top candidates*                                                      | absent |
| N+1   | *Cross-endpoint URL-emission signal on H1 resolves to a C-bucket handler*             | **enters queue, already annotated as "paired with H1"** |
| N+2   | *DF over the H1↔H2 pair — does the same field cross unnormalized?*                    | **CVE confirmed** |

Turn N+1 is the load-bearing beat. Not *"the endpoint we skipped got rescued"* — but *"the endpoint that wasn't in the first-pass set became reachable through a pair edge."* Different mechanism, cleaner story, and it justifies bucket C's exclusion as a design property, not an accident.

### Coarse-to-fine framing (control-flow shortlist → dataflow citation)

Underlying algorithm story that makes bucket C's design coherent with the runtime budget:

- **CF-reach is the shortlist; DF is the citation.** CF-reach is a *sound over-approximation* of DF-reach given a sound call graph — no false negatives from the filter. Perfect for triage.
- **Two design decisions, two justifications.** Intra-proc DF is precomputed eagerly because DF edges ≫ CF edges within a procedure (3–10× in practice). Inter-proc DF is stitched lazily in Prolog because the supergraph is combinatorially expensive to materialize *and* most (source, sink) pairs are never queried. **Sparsity of demand** — not density of edges — is what makes lazy right for inter-proc. Don't bundle both under one "cheaper" argument; the pushback lands otherwise.
- **Soundness caveat that helps you:** the sound over-approximation is exactly what makes the shortlist safe.
- **Soundness caveat that should be said first, before Q&A finds it:** CF-reach is only as sound as the call graph. HOC-unwrap (root cause #1 in [`AUTH_POST_RECALL_GAPS.md`](AUTH_POST_RECALL_GAPS.md)) matters for the soundness of **every** downstream CF-reach filter, not just for the auth-bucket recall count. Frame HOC-unwrap on the slide as *"we widen the call graph so the cheap screen stays sound."*

### The design constraint the story reveals

**Every primitive that flips priority mid-exploration has to be cheap enough to precompute at kbgen time.** If the cross-endpoint URL-emission signal cost as much as full DF, the agent would never fire it inside the time budget and H2 would stay buried forever. So "response URL literal + KB-resolves-to-handler" has to be a **kbgen-time fact**, essentially free at query time. Same discipline as intra-proc DF summaries, applied to a different edge kind. Direct tie-back to [`GOAL.md`](GOAL.md)'s *"meaningful prioritization is only possible if every query respects a configurable upper time bound"* — the coarse pass isn't cheap by accident, it's cheap **by contract**.

### API additions (three leaf-shaped adds, same shipping pattern as §12)

1. **New KB primitive** — `utils_capability_verifier_call/2` in [`utils.pl`](../dhscanner.core/dhscanner.service.queryengine/utils.pl). A call that verifies a cryptographic assertion *without* consulting session/cookie/live-user state (HMAC compare, JWT parse against a shared secret, signed-URL sig check, expiry check). Distinguished from the existing auth catalog by the **absence** of session/identity coupling — same shape that already separates B from A, extended one step further.
2. **New kbapi query variant** — `CapabilityVerifiedHttpPostHandlerRequestObject` (and its GET twin) alongside `Authenticated…` and `Unauthenticated…`. **Critically: this query is *not* fired in the first-pass grid.** It's fired implicitly, as the resolution target of the cross-endpoint URL-pairing query on H1.
3. **New field on H1's endpoint record** — `emitsCapabilityToHandler: [{handler: <H2>, capabilityShape: 'JWT' | 'URLQueryHMAC' | 'FormFieldHMAC' | 'OpaqueDbToken', deliveryChannel: 'HttpResponse' | 'Email' | 'Unknown', boundFields: ['fileName','oid']}]`. This is what puts H2 on the queue as a pair-vertex, with the pairing metadata already attached — no separate re-derivation step. **The `capabilityShape` enum spans crypto and non-crypto mechanisms** (see §5.9 for the opaque DB-token case); **the `deliveryChannel` distinguishes HTTP-body from out-of-band** — the latter typically indicates account-recovery flows, which are high-value attack targets with different threat models than machine-to-machine upload flows.

### Signal-value ranking (crystallized in same session — for slide phasing)

Endpoint-record fields a good triage agent wants, ranked by decision-value:

- **Phase 2 (triage within the first-pass A ∪ B set):** URL decomposition (verb-hidden-in-noun; `/management/` in pre-auth bucket = red flag; version drift; `/(internal)/`; `/ee/`); path params → IDOR fuel; **handler complexity** (LOC / branch count / methods-in-file) — framed as a *heuristic prior*, not a signal; **response HTTP status vocabulary** (401 present/absent) — with a 2×2 asymmetry that lets the agent self-audit its own bucket label:

  |                        | handler emits 401  | handler never emits 401 |
  |------------------------|--------------------|-------------------------|
  | label = **pre-auth**   | **contradiction — re-examine** | consistent |
  | label = **auth**       | consistent         | **suspicious — failing open or middleware-gated** |

- **Phase 3 (cross-endpoint):** sinks reached transitively (with **explicit empty-list contract** — "we looked, nothing there"); and **response-URL literals + KB-resolves-to-handler pairing** — the two fields that create bucket C's discovery edges.

Narrative choice for the demo: introduce endpoint **#11 `/organizations/[organizationId]/users`** (from [`tests/expected/facts/formbricks/post_endpoints.txt`](../tests/expected/facts/formbricks/post_endpoints.txt)) as the *first-picked* endpoint — its shape (management-shaped + `[organizationId]` path param + wrong bucket) demonstrates the reasoning framework generically, whereas picking `/storage/local` first would compress into *"we picked the vuln because it was the vuln."* The formbricks CWE-22 seed then arrives naturally at turn N+1 as the pair-vertex bucket C discovers.

### Cross-repo evidence for the pattern's generality

§5.8 documents two independent gitea instances (LFS + Actions v4) of the exact same H1↔H2 pattern, using two different signing mechanisms. Combined with formbricks §5.5, that's **three data points across two independent repos, three languages/routers, three capability formats**. Framework-invariance thesis (§4.2) validated cleanly for bucket C.

### Open decisions for bucket C

- [ ] **Better name than "capability-verified"** — current term is a placeholder. Candidates: *delegated-authority*, *signed-handoff*, *pair-authorized*, *capability-gated*. Whatever we pick must survive both `utils.pl` clause names *and* a slide bullet.
- [ ] Should bucket C get its own **CI snapshot** (`tests/expected/facts/formbricks/capability_verified_endpoints.txt`) analogous to the round-1 POST snapshot, or is it only meaningful as a *derived* set surfaced through H1 pair-resolution?
- [ ] Should `emitsCapabilityToHandler` be a **new kbgen-emitted fact** (cheaper at query time) or a **`utils.pl` derivation** over existing `kb_call_resolved` + `kb_const_string` + `kb_returned_from` facts (leaf add with no kbgen touch)?
- [ ] Does the capability-verifier detector go **conservative** (only fires on well-known HMAC/JWT library APIs) or **structural** (fires on any "extract signed field from request → `hmac.Equal(...)` / `jwt.Parse` shape")? Precision-vs-recall tradeoff, same shape as `AuthEvidence` — probably wants its own evidence-tag sum type (`ByJWTVerify`, `ByHmacEqualOnQueryParams`, `ByFormFieldHmacCheck`, …).

### Bootstrap prompt for the fresh session (paste at top of new chat)

> *"I'm continuing the `dhscanner` OWASP-IL 2026 work. Please read `docs/OWASP26_NOTES.md` §4.8 (endpoint taxonomy), §5.5 (formbricks CWE-22 seed vuln), §5.8 (gitea capability-verifier evidence), and §13 (bucket C plan). Also skim `demo/formbricks.md` for the H1↔H2 seed vuln that motivates the whole bucket. Round-1 recon (§12) is landed. Next task: sketch the `utils_capability_verifier_call/2` predicate in `utils.pl` on top of existing kbapi primitives, then a matching `emitsCapabilityToHandler` field on H1's endpoint record. Use the leaf-add shipping pattern from §12 (kbapi type + queryengine handler + CI snapshot). Skip the naming decision for now — placeholder is fine."*

- **2026-09-16** — Added §13 "Next Session — Bucket C (capability-verified endpoints)" with the three-way endpoint taxonomy (persisted separately as §4.8), the queue-dynamics story (H2 enters as pair-vertex, not by re-scoring), the coarse-to-fine framing (CF-reach shortlist → DF citation, with two-decisions-two-justifications and the call-graph soundness caveat), the *precompute-at-kbgen* design constraint, three API adds (`utils_capability_verifier_call/2` + `CapabilityVerifiedHttpPostHandlerRequestObject` variant + `emitsCapabilityToHandler` field on H1), and the signal-value ranking with the response-status-vocabulary 2×2. Cross-repo evidence persisted as §5.8 (gitea LFS + Actions v4). Next session's task: sketch `utils_capability_verifier_call/2` end-to-end.

---

## 14. Next Session(s) — HOC Recognizer, Bounded CF-Reach, Sink-Family Hierarchy

**Where we left off.** Session 2026-09-18 designed the concrete engineering path to make the *opening* demo endpoint (§5.11 — formbricks bulk PUT `/contacts/bulk`) enumerable, queryable, and clearable end-to-end. The seed vuln (§5.5 / §13) remains the finale; this section covers the workflow-demonstration act that precedes it. Four assignments identified; three fully-scoped (1, 3, 4); one deferred pending further chat (2).

The session also crystallised **the heuristic that unlocks everything** — a pattern-directed shortcut for wrapper-defined HTTP handlers that skips general higher-order-function analysis in favour of caller-side syntactic recognition. This is industry-standard SAST convention (Semgrep, CodeQL, Datadog, Snyk, Fluid, Checkmarx all do the same) and is the *why* behind Assignment 1's design.

### The heuristic — pattern-directed shortcut recognition

**The problem it solves.** Under standard nested-lambda modeling, the exported `PUT`'s procedure node has exactly one outgoing call-graph edge (to the HOC wrapper). The user's handler lambda is a *value* passed into the wrapper's config-object argument, not a callee reached by any edge. Sound HOF flow through the wrapper chain (through `apiWrapper` → destructured `handler` param → dispatched at `api-wrapper.ts:115`) requires inter-procedural parameter-flow + dict-property-lookup + destructuring analysis. Untractable at scale, and unnecessary when the framework idiom is stable.

**The shortcut.** Recognise the *outer framework idiom* at its caller-side syntactic shape:
```
export const <VERB> = async (req) => <ANY-CALLEE>(<dict-literal-with-any-callable-field>)
```
Synthesise a call-graph edge from the top-level `<VERB>` export directly to the body of any callable found inside the dict-literal argument. Skip the wrapper's internals entirely.

**Legitimacy.** This is the design every mature SAST uses — nobody does general HOF flow through arbitrary wrapper chains. Framework conventions are stable enough to encode at the caller-side pattern layer. The failure mode when the framework changes its API is obvious (no endpoints found), which is a healthy signal.

**Known limits (all bounded, all research-talk-honest, all invite-contribution shaped):**

| # | Limit | Consequence | Frame for the talk |
|---|---|---|---|
| A | Over-approximation when the dict contains *multiple* callables, not all dispatched | Not present in formbricks (single `handler:` field per config) | Skip for the corpus; refine to conventional-key-name lookup (`handler`, `execute`, `run`, `POST`, `GET`) if it appears elsewhere |
| B | Under-approximation when the handler is a variable reference / function composition / spread source | Not present in formbricks (direct inline arrows everywhere) | Skip for the corpus |
| C | Auth classification is skipped — endpoint stays labeled pre-auth even when the HOC enforces auth | Severity-mislabel only (**conservative direction: overstates, not understates**); finding validity preserved | Include as *"modular gap the community can contribute"* — orthogonal recognizer catalog of auth-enforcing HOC names |
| D | Handler args are pre-processed (Zod-`safeParse`d) inside the wrapper — the lambda's `parsedInput.body.<field>` isn't the raw request body | Matters for DF/taint (Zod as first-line sanitizer, taint-source refinement); irrelevant for CF-reach | Include as *"downstream DF layer will consume Zod schemas as taint-source declarations"* — future work |

### Assignment 1 — Generic HOC-shape HTTP handler recognizer

**Scope:** Prolog only in [`utils.pl`](../dhscanner.core/dhscanner.service.queryengine/utils.pl). AST already preserves the shape; the parser needs no changes. Complex semantic recognition is Prolog's job.

**Pattern:** as described above — generic outer syntax, no HOC-name catalog, all HTTP verbs `{GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS}`.

**Action:** synthesise a call-graph edge from the `<VERB>` export to every callable value inside the dict-literal argument.

**Success criteria:**

1. `PUT` and other non-POST verbs enumerated alongside `POST` in the existing 2×2 grid infrastructure.
2. Endpoint #18 — `PUT /contacts/bulk` — appears in the enumeration (see §5.11).
3. The 18-entry pre-auth-POST snapshot in [`tests/expected/facts/formbricks/post_endpoints.txt`](../tests/expected/facts/formbricks/post_endpoints.txt) preserved or expanded (regression check — no drops).
4. Snapshot for the newly-widened verbs added: e.g. `tests/expected/facts/formbricks/put_endpoints.txt`, deliberate diff-audit protocol per the header of the existing POST snapshot.

**Cross-reference:** [`AUTH_POST_RECALL_GAPS.md`](AUTH_POST_RECALL_GAPS.md) root cause #1 — this assignment is the concrete implementation of that fix, redesigned around today's generic-pattern decision (was originally scoped as a named-catalog fix for `authenticatedApiClient`).

### Assignment 3 — Bounded CF-reach as a new kbapi predicate

**Scope:** Prolog predicate in `utils.pl` **plus** new Haskell type in [`dhscanner.packages/dhscanner.kbapi`](../dhscanner.packages/dhscanner.kbapi) alongside the existing two predicates (currently exposes `AuthenticatedHttpXxxHandlerRequestObject` and `UnauthenticatedHttpXxxHandlerRequestObject`), **plus** a matching queryengine handler + Prolog template.

**Query shape — both endpoints fixed, no transitive-closure enumeration:**
```prolog
cf_reaches(+EntryPoint, +SinkSite).
```

- Both `+EntryPoint` and `+SinkSite` are ground on entry — bounds the search naturally by query shape.
- BFS on the call graph with a **hop-count cap** (proposed default: 20; tunable per-query if a future consumer needs different limits).
- Returns success/failure only — no path witness needed for the demo's use case (path reconstruction is out of scope; can be added later if a consumer requires it).
- Composes with Assignment 1's synthesised HOC-shortcut edges — the recognized handler lambda is the *effective* entry point for CF-reach purposes.

**Success criteria:**

1. `cf_reaches` fires from `PUT /contacts/bulk` (post-Assignment-1 entry point) to each of the 6 Prisma sink sites in §5.11's table.
2. Exposed as a new kbapi query variant.
3. Respects the queryengine's per-query time budget from [`docs/GOAL.md`](GOAL.md).
4. Regression-test on formbricks KB: known-negative pairs return failure within the hop cap.

### Assignment 4 — Sink-family hierarchy predicates

**Scope:** Prolog only in `utils.pl`. Layered ontology per the design chat 2026-09-18:

```prolog
%% ---- top layer: sink categories the LLM asks about ----
sql(Site) :- sql_prisma(Site).
%% future: sql(Site) :- sql_sqlalchemy(Site). sql_activerecord(Site). etc.

%% ---- mid layer: per-ORM/driver family ----
sql_prisma(Site) :- sql_prisma_object_form(Site).
sql_prisma(Site) :- sql_prisma_raw_form(Site).

%% ---- bottom layer: DB-interaction name lookup tables ----
sql_prisma_object_form(Site) :-
    kb_call_resolved(Site, Name),
    prisma_object_form_name(Name).

prisma_object_form_name("prisma.<model>.findMany").
prisma_object_form_name("prisma.<model>.findUnique").
prisma_object_form_name("prisma.<model>.findFirst").
prisma_object_form_name("prisma.<model>.create").
prisma_object_form_name("prisma.<model>.createMany").
prisma_object_form_name("prisma.<model>.update").
prisma_object_form_name("prisma.<model>.updateMany").
prisma_object_form_name("prisma.<model>.upsert").
prisma_object_form_name("prisma.<model>.delete").
prisma_object_form_name("prisma.<model>.deleteMany").
prisma_object_form_name("prisma.<model>.count").
prisma_object_form_name("prisma.<model>.aggregate").
prisma_object_form_name("prisma.<model>.groupBy").

sql_prisma_raw_form(Site) :-
    kb_call_resolved(Site, Name),
    prisma_raw_form_name(Name).

prisma_raw_form_name("prisma.$queryRaw").
prisma_raw_form_name("prisma.$queryRawUnsafe").
prisma_raw_form_name("prisma.$executeRaw").
prisma_raw_form_name("prisma.$executeRawUnsafe").
```

**Safety predicates layer cleanly on top (tier-1 categorical + tier-2 structural):**
```prolog
%% tier-1: prisma object-form is safe by construction (parameterized by definition)
sink_family_safe(Site, prisma_object_form) :-
    sql_prisma_object_form(Site).

%% tier-2: prisma raw tagged-template is safe iff no Prisma.raw(...) in interpolations
sink_family_safe(Site, prisma_raw_tagged_no_raw_interpolation) :-
    sql_prisma_raw_form(Site),
    kb_call_resolved(Site, Name),
    prisma_raw_tagged_name(Name),                    %% NOT the Unsafe variants
    \+ interpolation_contains_prisma_raw(Site).

prisma_raw_tagged_name("prisma.$queryRaw").
prisma_raw_tagged_name("prisma.$executeRaw").
```

**Success criteria:**

1. `sql/1` matches all 6 Prisma sinks reachable from `PUT /contacts/bulk` (Assignment-2-dependent for `tx.*` calls — see below).
2. `sink_family_safe/2` classifies 4 of the 6 as `prisma_object_form` and 2 of the 6 as `prisma_raw_tagged_no_raw_interpolation`.
3. Composed with Assignment 3's `cf_reaches`: the query *"reach any sink from `E` that is NOT `sink_family_safe`"* returns the empty residue for endpoint #18 (the "safe, move on" verdict).
4. CI snapshot on formbricks for the composed query — locks the 4/2 split against future regressions.

**Community-friendly design point.** Every layer is a plain lookup table. Adding new ORMs / drivers / sink families / safe-family instances is a PR against `utils.pl` catalog facts — no algorithm changes needed. Deck-facing framing: another instance of *silent snipes* (§4.7).

### Assignment 2 — Prisma DB-call capture (DEFERRED)

**Status:** deferred by user 2026-09-19 pending further chat. Persist current thinking so a later session can pick up without re-deriving.

**Three sub-questions on the table:**

- **Q2.1 — `tx.<model>.<op>` and `tx.$queryRaw` / `tx.$executeRaw` inside `prisma.$transaction(async (tx) => {...})` callbacks.** `tx` is a callback parameter, not the global `prisma`. Without recognition, 4 of the 6 sinks on §5.11's endpoint are invisible to Assignment 4's ontology. **This is the complicated sub-question.**
  - **Option A — Scope-aware rewriting.** Inside a `prisma.$transaction(async (X) => {...})` callback, treat all `X.<Y>.<Z>` as `prisma.<Y>.<Z>` for classification purposes. Requires either KB-emission-time rewriting (kbgen change) or query-time Prolog scope walks over `$transaction` callback bindings.
  - **Option B — "Cheat" (parallel spirit to Assignment 1's HOC shortcut).** Just add both `prisma.<any>.<op>` and `tx.<any>.<op>` to the family-name lookup tables in Assignment 4. Over-approximates in the theoretical case where someone names a non-Prisma variable `tx` in the same file; the convention against that is strong enough in practice that this may be acceptable for the research talk.
  - **Discussion pending.** User note 2026-09-19: *"can't concentrate on Q2 — persist and circle back after 1+3 are implemented."*

- **Q2.2 — `prisma.$transaction([...])` / `prisma.$transaction(callback)` counting.** Not a sink itself; it's a batching wrapper. Proposed: capture as a call node, tag with taxonomy fact `prisma_batching_wrapper`, keep out of `sql_prisma_*`. Small; likely uncontroversial.

- **Q2.3 — `Prisma.sql` and `Prisma.raw` capture.** Needed for the tier-2 `interpolation_contains_prisma_raw/1` predicate defined in Assignment 4. Proposed: capture in the same pass; tag with taxonomy facts `prisma_sql_wrapper` (safe) and `prisma_raw_wrapper` (unsafe-parameterization-bypass). Small; likely uncontroversial.

**Circle-back prompt (for the later session that picks this up):**

> *"Assignment 2 (Prisma DB-call capture) was deferred on 2026-09-18. Read `docs/OWASP26_NOTES.md` §14, subsection 'Assignment 2 — DEFERRED'. Focus on Q2.1 (`tx.<...>` inside `prisma.$transaction` callbacks) — decide between Option A (scope-aware rewriting) and Option B (add both `prisma.*` and `tx.*` to the Assignment 4 lookup tables). Q2.2 and Q2.3 are likely small; scope them alongside whichever direction Q2.1 goes."*

### Cross-cutting — language corpus for these sessions

**JS/TS only.** Get the formbricks demo path fully working end-to-end (Assignments 1, 3, 4, then eventually 2) before porting recognizer/predicate work to the other corpus languages (Go/Gitea, Python/Weblate, PHP/Concrete-CMS + phpBB modern). The HOC-shape pattern in Assignment 1 has structural cousins in every language of the corpus (§5.10 documents the Django decorator analog; §5.8 documents Go router-registration; §5.9 documents PHP class-method dispatch), but each needs its own per-language recognizer expression.

### Bootstrap prompt for the fresh session

> *"I'm continuing the `dhscanner` OWASP-IL 2026 work. Please read `docs/OWASP26_NOTES.md` §5.11 (bulk PUT demo endpoint) and §14 (HOC recognizer / bounded CF-reach / sink-family hierarchy) plus `docs/AUTH_POST_RECALL_GAPS.md` root cause #1 (which today's §14 supersedes with a generic-pattern approach). Start with Assignment 1 — the generic HOC-shape recognizer in `utils.pl`. Success criteria: `PUT /contacts/bulk` appears in the enumeration alongside the existing POST snapshot, and the POST snapshot count is preserved (18) or expanded. Skip Assignment 2 (deferred). After #1 lands, proceed to Assignment 3 (bounded CF-reach kbapi predicate), then Assignment 4 (sink-family hierarchy)."*

- **2026-09-18** — Added §14 "Next Session(s) — HOC Recognizer, Bounded CF-Reach, Sink-Family Hierarchy" with four assignments (three scoped, one deferred), the pattern-directed shortcut heuristic that unblocks the whole plan, four known-limit categories framed for research-talk honesty, and the sink-family predicate hierarchy sketch (top `sql` → mid `sql_prisma` → bottom `prisma_object_form_name`/`prisma_raw_form_name` lookup tables, plus tier-1/tier-2 `sink_family_safe` predicates on top). Added §5.11 documenting the opening demo endpoint (`PUT /contacts/bulk`) with its full 6-sink inventory + tier-1/tier-2 clearance chain. `AUTH_POST_RECALL_GAPS.md` root cause #1 updated in parallel to reflect the generic-pattern approach. Next session's tasks (in order): Assignment 1 → Assignment 3 → Assignment 4 → chat about Assignment 2.
