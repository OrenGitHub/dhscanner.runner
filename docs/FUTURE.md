# FUTURE

Companion to [`GOAL.md`](GOAL.md). The current-phase goal (July–October 2026)
is proving general applicability of the dhscanner paradigm across languages
against real-world open-source applications listed on
[HackerOne bug bounty programs](https://hackerone.com/opportunities/all/search?asset_types=SOURCE_CODE).

This doc names the concrete cross-language target set for the
**post-OWASP-IL-2026 phase**: one bounty-listed open-source application per
major language. Landing one real, acknowledged vulnerability per target is
the substantiation plan for the *"same architecture, N structurally different
language stacks"* claim (see §3).

---

## 1. Target matrix

| # | language | target                                                                           | domain                     | disclosure path                              |
|--:|----------|----------------------------------------------------------------------------------|----------------------------|----------------------------------------------|
| 1 | C#       | [`bitwarden/server`](https://github.com/bitwarden/server)                        | password manager / vault   | HackerOne program                            |
| 2 | Go       | [`go-gitea/gitea`](https://github.com/go-gitea/gitea)                            | git forge                  | Security policy + CVE track record           |
| 3 | PHP      | [`phpbb/phpbb`](https://github.com/phpbb/phpbb)                                  | forum                      | Security policy + CVE track record           |
| 4 | Python   | [`WeblateOrg/weblate`](https://github.com/WeblateOrg/weblate)                    | translation platform       | Security policy + CVE track record           |
| 5 | TypeScript | *(to be selected)*                                                             |                            |                                              |
| 6 | JavaScript | [`TryGhost/Ghost`](https://github.com/TryGhost/Ghost)                          | publishing / CMS           | Security policy + public hall of fame        |
| 7 | Ruby     | [`discourse/discourse`](https://github.com/discourse/discourse)                  | forum                      | HackerOne program                            |
| 8 | Java     | [`DSpace/DSpace`](https://github.com/DSpace/DSpace)                              | digital repository / archive | Published security advisories + CVE track record (deferred; see §4) |

---

## 2. Selection criteria for the `<find>` slots

Every candidate must satisfy all five:

1. **Open source** — public repository, freely readable license.
2. **Application, not infrastructure.** Forums, CMSes, git forges, form
   platforms, LMSes, CRMs, e-commerce, collaboration platforms. **Not**:
   language runtimes, package managers, web frameworks themselves, standard
   libraries, general-purpose developer tools. The endpoint-recognizer /
   auth-recognizer / sink-recognizer story per
   [`ENDPOINTS.md`](ENDPOINTS.md) is meaningful only for user-facing HTTP
   surfaces.
3. **Real attack surface** — multi-user authentication, admin / privileged
   paths, uploads, real-world deployment footprint. Toy apps do not
   substantiate the generality claim.
4. **Bug bounty program or documented security disclosure path** — preferred:
   listed on HackerOne / Bugcrowd. Acceptable: a `SECURITY.md` with a
   published track record of acknowledged fixes and CVEs.
5. **Actively maintained** — commits in the last 90 days. A finding needs a
   live maintainer channel to be acknowledgeable.

---

## 3. Rationale for N = 8, one-per-language

**Epistemic threshold.** N = 8 is roughly where *"same tool, N structurally
different language stacks, N real vulns"* stops being dismissible as
cherry-picking and starts being evidence of a *systematic capability*.
Below N = 5–6 the claim reads as anecdote; above N = 7–8 the return on
additional targets diminishes.

**One application per language, not N per language.** Maximizes cross-stack
diversity per unit of scanning budget, which is what the "language-agnostic
architecture" claim requires. In-language recall is a different (also
valuable) research question — explicitly not the goal here.

**Why open-source apps specifically, and not proprietary bounty targets.**
Reproducibility. Every finding needs to be re-runnable from the published
ScanTrace ([`OWASP_NOTES_FINALIZED.md`](OWASP_NOTES_FINALIZED.md) §4) by
anyone in the audience or on a review committee. Proprietary targets break
that chain.

---

## 4. Java caveat

`frontjava` does not exist in [`LAYOUT.md`](LAYOUT.md) §`compose.fronts.yaml`
today (shipped fronts: js, ts, php, py, rb, cs, go — seven). The Java slot
is contingent on standing up a Java native front, likely built around
JavaParser or Eclipse JDT. That is a multi-week workstream in its own right
and precedes any target selection for Java.

If Java slips, the "8 languages" threshold degrades to 7 — still comfortably
above the 5–6 epistemic minimum. Honest framing in that case:
*"7 languages shipped, Java native front in flight."*

---

## 5. Per-target workstream shape

For every target, the work follows the same three-phase contract:

1. **End-to-end scan smoke test.** Confirm the language's front + parsers +
   kbgen path lowers the target's real code without crashes. Any gap here
   routes to the parsers submodule per
   [`../dhscanner/dhscanner.1.parsers/AGENTS.md`](../dhscanner/dhscanner.1.parsers/AGENTS.md).
2. **Endpoint / auth / sink recognizer coverage.** Add per-framework leaf
   clauses in `utils.pl` under the archetype the target fits, per
   [`ENDPOINTS.md`](ENDPOINTS.md) §3 and the leaf-addition contract in
   [`AUTH_POST_RECALL_GAPS.md`](AUTH_POST_RECALL_GAPS.md) §4.
3. **Drive to a real finding.** Agent-mode scan, LLM outer loop, publish
   the ScanTrace. Submit to the target's disclosure channel; success
   condition is a maintainer-acknowledged fix (formbricks precedent per
   [`GOAL.md`](GOAL.md)).

---

## 6. Related docs

- [`GOAL.md`](GOAL.md) — the current-phase goal this executes against.
- [`ENDPOINTS.md`](ENDPOINTS.md) — recognizer archetypes each target exercises.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) / [`LAYOUT.md`](LAYOUT.md) — pipeline and front coverage.
- [`AUTH_POST_RECALL_GAPS.md`](AUTH_POST_RECALL_GAPS.md) — leaf-addition contract for per-target recognizer work.
- [`OWASP_NOTES_FINALIZED.md`](OWASP_NOTES_FINALIZED.md) — where the cross-language evidence set feeds the ScanDigest / ScanTrace story.

---

## 7. Change log

- **2026-09-25** — Initial persist of the 8-language target set. Committed
  targets (C#, Go, PHP, Python) selected against §2 based on repo/bounty
  maturity and representative-archetype coverage per
  [`ENDPOINTS.md`](ENDPOINTS.md) §3. TS / JS / Ruby / Java slots left as
  `<find>` for follow-up selection.
- **2026-09-25** — Ruby slot filled: `discourse/discourse`. Rationale:
  cleanest §2 fit among Ruby OSS bounty candidates (evaluated Discourse
  vs. GitLab CE vs. Mastodon); Discourse-as-Ruby paired with phpBB-as-PHP
  is also a rhetorical asset — same problem domain, two structurally
  different language stacks, same architecture recognizing both.
- **2026-09-25** — JavaScript slot filled: `TryGhost/Ghost`. Rationale:
  most prominent CMS in the Node ecosystem (evaluated Ghost vs. Etherpad
  vs. Node-RED vs. Habitica); Express-based stack is architecturally
  disjoint from the Next.js/TypeScript formbricks precedent, satisfying
  the TS-vs-JS non-overlap constraint; the CMS domain is otherwise
  uncovered by the matrix.
- **2026-09-25** — Post-clone measurement: Ghost's effective source
  corpus (excluding tests, `node_modules`, `dist`, `build`) is roughly
  2,077 `.js` / 2,694 `.ts` files — **44 % JS / 56 % TS.** Ghost has
  progressively migrated to TypeScript since prior-knowledge cutoff.
  Decision (first pass): **keep Ghost in slot #6** and accept the mixed
  labeling; `frontjs` and `frontts` both fire regardless, so scanning
  is unaffected. Talk-framing consideration: if a reviewer challenges
  the JS-target labeling, honest response is *"Ghost is a mixed
  JS/TS codebase in active migration; we scan both and count it as
  the JS slot because Express + CommonJS-flavored patterns dominate
  the request-handling surface."* Revisit if a cleaner JS-first
  target becomes preferable during the workstream.
- **2026-09-26** — Java slot filled: `DSpace/DSpace` (deferred pending
  `frontjava` per §4; this is target selection, not scheduling).
  Rationale: evaluated XWiki, Jenkins, Apache OFBiz, Keycloak,
  GeoServer, DSpace, openHAB. DSpace picked for three reasons:
  (a) **domain uniqueness** — digital repository / institutional
  archive is completely uncovered by the rest of the matrix and
  distinct from every existing target's attack-surface story;
  (b) **Spring Boot recognizer amortization** — DSpace's REST backend
  uses Spring, so the recognizer work invested here directly serves
  the mainstream Java-web ecosystem for any subsequent target;
  (c) **credible disclosure path** — published DSpace security
  advisories with a real CVE track record satisfy §2 criterion #4
  without requiring a formal HackerOne program.
  Scope note (locked): the DSpace matrix slot refers **only to the
  `DSpace/DSpace` Java REST backend**. The separate `DSpace/dspace-angular`
  frontend repository is Angular/TypeScript, not Java, and is
  explicitly out of scope for this slot. If we later want to also
  scan the Angular frontend, that becomes a separate matrix
  addition, not a redefinition of the Java slot.
