# EVAL — the agent surface, against a product that sells it

> **Status: pre-registered, not yet run.** The subject, the claim list, the
> verdicts, the fixtures and the bar below were written **before a single claim
> was classified**, which is the discipline `EVAL-editor-parity.md` uses and the
> reason the milestone description forbids the other order. This document
> **claims no result**: it holds no verdict, no fixture output and no count of
> covered / declined / gap. A number appearing here before [#162] has run is a
> protocol violation, not a finding.
>
> **Decisions bound:** **D-e** — the seam is baseline-referencing rules only
> ([#152]). **D-f** — the product is named, quoted verbatim, and dated.
> **Sequence:** this is **A1** of the four-track plan recorded on [#152] —
> track A is the map (A1 protocol → A2 run → A3 decision), track B is the
> contract, C is distribution, D is the adoption-cost measurement. [#162] is A2
> and runs the fixtures and classifies; [#164] is A3 and writes the decision on
> [#6].
>
> **`#NN`** here are this repo's public issue numbers; **[#6]** is its
> milestone 6, *agent surface — measured*.

---

## 0. The subject, and what the unit of measurement is

**Code Guardian**, a commercial guard layer for Claude Code, sold by Provimedia
GmbH. Source: <https://www.provimedia.de/code-guardian>, **fetched
2026-08-23**. The page dates itself the same day ("Zuletzt aktualisiert: 23.
August 2026") and names the product version it describes as **v16.127**.

The page presents itself with a count:

> "5 Modi" · "6 Gates" · "18 Hooks" · "17 Detektoren"

**The page states that count twice, in two spellings**, and both are recorded
here verbatim rather than reconciled: the figures above are the stat block, and
the prose spells the first two out — "Fünf Modi, sechs Gates, 18 Hooks, 17
Detektoren" (C18). Neither is a paraphrase of the other; the page carries both.

**The page does not name them individually.** There is no list of the eighteen
hooks, no list of the seventeen detectors, no rule ids. Exactly one hook is
named anywhere on the page — `destructive-command-check.sh`, in the interactive
demo — and no detector is.

So the counts are **not** the unit of measurement, and nothing in [#162] is
scored against them. Two reasons, and the second is the load-bearing one:

1. A count of unnamed things cannot be matched against anything. "17
   Detektoren" versus this repo's 12 conventions / 40 rule ids is arithmetic
   between two different definitions of a thing, and it would produce a number
   that looks like evidence and is not.
2. **The counts move.** [#152] recorded this headline as *"4 Modi, 5 Gates, 10
   Hooks, 18 Detektoren"*; the page on the date above reads 5 / 6 / 18 / 17.
   Whether that is a product that shipped versions in between or a
   transcription that drifted, this document does not know and does not
   guess — it records what the page said on the date it was fetched. That is
   what D-f is for, and a measurement anchored to a moving count would have
   been wrong within a week.

**The unit is a claim: one named capability the page does assert.** §1
enumerates them, each with the German source text it came from and a neutral
English gloss. §2 fixes the three verdicts. §3 fixes the fixture each
measurable claim gets. §4 is the bar. §5 is what none of this can reach.

**On the quoting rule.** Every quotation below is the vendor's own wording,
copied exactly, in German, with the gloss kept separate and marked as ours. No
claim is paraphrased into something stronger than the page says — and §1 already
carries one correction of that kind (C17), made against this repo's own issue
text rather than against the vendor's.

---

## 1. The claims, verbatim

Sixteen capability claims, one scope statement, and the headline counts —
recorded for the date stamp and excluded from measurement. The eight that [#160]
named
in advance are marked **(listed on #160)**; the rest are claims the page makes
that the issue's list did not enumerate, and they are included because the unit
of measurement is *what the page claims*, not *what we remembered it claiming*.

### C1 — a four-stage approval workflow before any write **(listed on #160)**

> "Jede Aufgabe beginnt schreibgeschützt." … "Erst Ihr Klick öffnet den
> Schreibzugriff."

Stage labels, in the page's order: "schreibgeschützt", "Interview", "Plan",
"Ihre Freigabe".

*Gloss (ours).* Every task starts read-only; the agent explores, puts each open
decision to the user singly, and presents a plan; write access opens only on the
user's approval.

### C2 — destructive commands blocked at the tool boundary **(listed on #160)**

> "Ein Kommando, das Arbeit vernichtet, wird an der Werkzeuggrenze verweigert:
> bevor es läuft, nicht danach im Bericht."

The demo names one hook, `destructive-command-check.sh`, and offers these
commands as its examples: `git reset --hard`, `rm -rf src`,
`php artisan migrate:fresh`, `rsync -az ./ user@prod:/var/www/`,
`npm install reqests`, `rm -rf node_modules`.

*Gloss (ours).* A command that destroys work is refused before it executes,
rather than reported afterwards.

### C3 — transfer classification of files **(listed on #160)**

> "Übertragen und Existieren sind zwei verschiedene Achsen."

Under the heading "Nichts erreicht einen Server unklassifiziert.", over a
ten-file transfer list containing, among others, `.env`, `storage/app/private/`,
`.git/`, a `.sql` dump and a build artifact.

*Gloss (ours).* May-be-transferred and may-exist-there are separate axes; a
production `.env` must never be transferred and must still be present on the
server, a database dump may be neither. Files are classified before transfer.

### C4 — migrations treated as irreversible until proven otherwise **(listed on #160)**

> "Eine Migration gilt als irreversibel, bis das Gegenteil bewiesen ist."

The worked example is a Laravel `$table->dropColumn('rabatt_prozent');` against
which the gate emits a backup table (`CREATE TABLE _backup_… AS SELECT …`).

*Gloss (ours).* Application code is recoverable with `git revert`; a dropped
column is not, so an irreversible schema change is gated and a backup is taken
first.

### C5 — package reputation, not package existence **(listed on #160)**

> "Deshalb prüft das Gate Reputation statt Existenz : Alter, Download-Verlauf,
> ein echtes Repository mit mehr als einem Beitragenden, und die Namensnähe zu
> einem bekannten Paket."

The page frames this against slopsquatting — a model hallucinating a package
name reproducibly, someone registering that name, and the existence check then
answering yes.

*Gloss (ours).* A new dependency is judged on age, download history, a real
multi-contributor repository, and name proximity to a known package — because
"does this package exist" is the check the attack is built to pass.

### C6 — a data judgement is a judgement about the whole schema **(listed on #160)**

> "Ein Urteil über Daten ist ein Urteil über das ganze Schema."

The page's example is a `SELECT` over four columns of an orders table that
declares rows orphaned because the reader did not know a waiting column existed.
The page also states that this gate alone has no hook: "nur das Daten-Gate hat
bewusst keinen".

*Gloss (ours).* Before acting on a conclusion drawn from a partial query, the
full row and the surrounding schema are read; the gate advises and does not
block, by design.

### C7 — every assertion backed by command output

> "…jede Behauptung mit Kommando-Ausgabe belegen."

*Gloss (ours).* A claim the agent makes must be evidenced by the output of a
command it actually ran.

### C8 — an assertion is a hypothesis, checked by independent lenses

> "BESTÄTIGT gibt es nur, wenn die Ausführungslinse reproduziert hat.
> Mehrheitsentscheid ist verboten…"

The three lenses are labelled "Ausführung", "Absicht", "Umgebung", with a
fourth reviewer "der den Autor nicht kennt".

*Gloss (ours).* A bug read out of source is not confirmed until it has been
reproduced by executing something; three readings do not outvote one executed
refutation.

### C9 — no option question without a recommendation

> "Keine Optionsfrage ohne Empfehlung."

*Gloss (ours).* Every choice put to the user carries a recommended option first,
with reasons; an agent that lists three equivalent paths has handed the work
back.

### C10 — an unattended mode that escalates rather than decides

> "Ein Autopilot für Läufe, bei denen niemand am Bildschirm sitzt."

*Gloss (ours).* For runs with nobody watching, questions that would go to the
user go to the product's advisory council instead and are recorded verbatim.

### C11 — twelve review agents that read cold

> "Die zwölf Prüf-Agenten laufen kalt : ohne das Gespräch, ohne den Plan, ohne
> das Urteil des Autors."

*Gloss (ours).* The reviewers see the code without the conversation, the plan or
the author's own verdict.

### C12 — a whole-repository audit against AI sloppiness

> "Ein Voll-Repo-Audit gegen KI-Schlamperei…"

The page's own measurement of it, quoted as the page states it: "36 /36
mechanische Slop-Regeln greifen auf den Fallen".

*Gloss (ours).* A repo-wide scan for the classes of mess an AI agent
characteristically leaves; the vendor reports 36 of 36 mechanical rules firing
on their traps with none on the clean counterparts.

### C13 — a hard safety condition on the cleanup layer

> "0 produktive Symbole je zum Löschen freigegeben"

*Gloss (ours).* The cleanup layer has never released a production symbol for
deletion; a violation fails the run.

### C14 — a task list that survives a crash

> "…eine Aufgabenliste, die einen Absturz überlebt."

*Gloss (ours).* Session task state is durable across a crash.

### C15 — tools that wire static analysis into a foreign project

> "…zwei Werkzeuge, die statische Analyse in einem fremden Projekt einrichten —
> für PHP und für JS/TS/Vue."

*Gloss (ours).* Two of the fifteen skills set up static analysis in a project
that does not have it, for PHP and for JS/TS/Vue.

### C16 — licence key retrieved by Claude Code **(listed on #160)**

> "Lizenzschlüssel für den automatischen Abruf durch Claude Code"

*Gloss (ours).* The subscription supplies a licence key that Claude Code uses to
fetch new versions automatically.

### C17 — the stated language support **(listed on #160)**

Under the page's own "Was es nicht kann." heading:

> "Statische Analyse und Mutationstests sind für PHP/Laravel und JS/TS/Vue
> verdrahtet. Der Slop-Scanner liest zusätzlich Python, Go, Rust und Ruby."

and, for the remainder:

> "Auf einem anderen Stack bekommen Sie die Gates, die Reflexe und den Scanner,
> aber kein Analyse-Gate…"

*Gloss (ours).* Static analysis and mutation testing are wired for PHP/Laravel
and JS/TS/Vue. The slop scanner additionally reads Python, Go, Rust and Ruby.
On any other stack the gates, the reflexes and the scanner still run; the
analysis gate does not, because it has nothing to delegate to.

> **Correction, recorded against ourselves.** [#160] glosses this claim as
> "PHP/Laravel, JS/TS/Vue primary, Python/Go/Rust/Ruby **read-only**". The page
> does not say read-only. It says the slop scanner *additionally reads* those
> four, and it says separately that the gates and the scanner run on any stack.
> "Read-only" is a stronger and different claim than the vendor makes, and
> classifying against it in [#162] would have measured our paraphrase instead of
> their product. The wording above is the page's.

### C18 — the counts, recorded and not measured

> "Fünf Modi, sechs Gates, 18 Hooks, 17 Detektoren"

Recorded for the date stamp only. It is **not** a claim [#162] classifies —
§0 states why.

---

## 2. The three verdicts, and the test that decides each

Every claim **C1–C16** gets exactly one verdict in [#162]. The seam test is
applied first and decides the label; the fixture is run either way.

**C17 and C18 get no verdict, and that is not an omission.** C17 is the
product's own scope statement: its job is to bound which of C1–C16 could apply
to a tree this baseline ships for, so it is recorded as context on every other
row rather than scored on its own. C18 is the counts, excluded in §0. §3b
carries both rows with that reason attached, so neither can be quietly scored
later.

| # | Verdict | The test |
|---|---|---|
| 1 | **declined** | The claim **fails the seam test** of D-e (it does not reference the baseline itself — it protects a person in any repo, and belongs in `~/.claude`), **or** `docs/CONCEPT.md` §1 excludes it (no AI review pipeline; every detector here is a denylist and an exit code). The reason is written out per claim, naming which of the two applies. Never implied. |
| 2 | **covered** | It passes the seam test, **and** something already in Layer 1, Layer 2 or `configs/agent/` **fires on the planted fixture** §3 names for it. Fires means an exit code or a finding, produced by a run, pasted into [#162] — never inferred from a config file. |
| 3 | **gap** | It passes the seam test, and nothing fires. |

**The seam decides the label; the fixture still runs.** These are two questions
and only the first one picks the word. A claim that fails the seam test is
*declined* whether or not anything here fires on it, because the seam of D-e
governs what this baseline builds and that does not change on a detection
result.

**But a declined claim is still run**, wherever §3 gives it a fixture, and this
is the half that is easy to drop. If declining a claim also excused us from
running it, "we decline this" would be indistinguishable from "we never looked",
and the tree would be described by an argument instead of by a result. So the
fixture goes in, and the row carries what came back:

- **declined, and nothing fires** — out of scope, and we do not do it today.
- **declined, and something fires anyway** — out of scope, and we do it
  regardless. The row names what fired (`declined — fires via …`). This is not a
  contradiction and it is not promoted to *covered*: it is a thing the baseline
  happens to catch on its way to catching something else, and [#164] may read it
  either way.

Those two are different facts about the tree, and a verdict that could not tell
them apart would be hiding the more interesting one.

**A claim with no fixture gets no verdict of covered.** §3 marks each such claim
"not measurable, because …"; those are classified on the seam test alone and
[#162] records them as **declined** or **gap** with the missing-fixture reason
attached. A claim cannot become *covered* by argument.

`configs/agent/` above is the agent contract from [#158] and [#161] — four
rules, its seam stated in its own README §1. It is the B track of this milestone,
merged to `develop` on 2026-08-23 and still moving under [#163]; §3 states what
[#162] does when a row's subject is not there on the day of the run.

---

## 3. The fixture each claim gets, pre-registered

**No fixture is created by this document** — [#160] does not create them, and
creating one here would be running the eval. Two rows point at artefacts that
already exist (C7's `stop-` cases, C15's `adopt` and `examples` jobs); those are
**cited, not created**, and the row says so. Everything else is planted in
[#162]. Each row fixes **the artefact [#162] will use** and **the tool that
would have to fire** for the claim to be classified *covered*. Naming the tool is not predicting that it fires; it is
fixing in advance which tool's silence counts as a miss, so a claim cannot be
quietly re-pointed at a tool that happened to say something.

**New fixtures live under `eval/code-guardian/`, not under `samples/`**, and
the reason is `CLAUDE.md` §5 rather than tidiness: `samples/` *is* the test
suite, every directory in it is either a planted bug that must fail or a clean
control that must pass, and CI holds it to that. An eval fixture is neither. It
exists to be run once and recorded, and some of these are expected to produce
nothing at all — which under `samples/` is indistinguishable from a config that
regressed. Putting them there would erode the one invariant that makes a red
sample mean something. Whether `eval/code-guardian/` survives past the run is
[#164]'s to decide, not this document's.

**Rows naming `configs/agent/`, `scripts/agent-guard/` or `samples/agent-guard/`
came from the B track**, and it has landed — [#158] and [#161] merged to
`develop` on 2026-08-23, so those paths resolve and the rows below name real
files. The rule stands anyway, because the two tracks run in parallel and the
contract is still moving: [#162] runs against whatever exists on the day of the
run and states which, and a row whose subject is absent is recorded as un-run,
never silently as a miss.

### 3a. Measurable claims

| Claim | Fixture planted in [#162] | The tool that would have to fire |
|---|---|---|
| **C1** approval workflow | a `PreToolUse` payload for `Edit` on an ordinary source file, in a session with no plan and no approval — the same payload shape `samples/agent-guard/cases/` already uses | a `PreToolUse` hook wired by `configs/agent/settings.json`; today the only one on `Edit` is `scripts/agent-guard/sample-guard.py` |
| **C2** destructive commands | three `PreToolUse` payloads for `Bash`: `git reset --hard`, `rm -rf src`, and `rsync -az ./ user@prod:/var/www/` | a `PreToolUse` hook on `Bash` wired by `configs/agent/settings.json`; today the only one is `scripts/agent-guard/no-verify-guard.py` |
| **C3** transfer classification | a fixture tree holding a populated `.env`, a `dump-*.sql`, a build artefact and a private storage path, plus a `Bash` payload that rsyncs the tree to a remote host | two different questions, and [#162] records them separately: the **transfer** half needs a hook wired by `configs/agent/settings.json`; the **at-rest secret** half is Gitleaks via `scripts/scan.sh`. Gitleaks finding the planted secret is *not* the transfer claim, and the row says so |
| **C4** irreversible migration | one drop-column migration per language this baseline ships: `eval/code-guardian/migrations/typescript/` (a knex/Prisma migration), `…/dotnet/` (EF Core `migrationBuilder.DropColumn`), `…/python/` (Alembic `op.drop_column`), `…/rust/` (a `sqlx` migration with `ALTER TABLE … DROP COLUMN`), `…/java/` (a Flyway `V2__…sql`) | Layer 2 Semgrep over the tree, plus that language's Layer 1. Which of the 40 rule ids fires, if any, is what [#162] records — this row fixes the tools, not the outcome |
| **C5** package reputation | two manifests carrying a name one character from a real one — a `package.json` depending on `reqests`, and a `requirements.txt` on `requirments` — one with a lockfile entry and one without | OSV-Scanner via `scripts/scan.sh`. [#162] records the category difference in the same row: OSV answers *is this package known-vulnerable*, the claim is *is this package reputable*, and a miss for one reason is not a miss for the other |
| **C6** data / schema judgement | a migration containing a destructive statement with no backup (`DELETE FROM … WHERE …`, and an `UPDATE` with no `WHERE`), and a query assembled by string concatenation next to it | `semgrep/security/sql-string-concat.yaml` for the concatenation half, Layer 2 Semgrep over the migration for the destructive-statement half. The two halves are recorded as two results, because a hit on one is not a hit on the other |
| **C7** claims backed by command output | the existing `stop-` cases in `samples/agent-guard/cases/` — `stop-01-no-receipt` (a turn ending with changed content and no gate run), `stop-03-receipt-stale` and `stop-04-receipt-fail` — cited, not rewritten | `scripts/agent-guard/stop-gate.py`. This is the one claim where the fixture already exists, and [#162] must cite the case ids it ran rather than re-describing them |
| **C12** slop audit | a TypeScript fixture carrying the mechanical shapes: an unreferenced export, a duplicated block, a left-behind debug print, a `TODO` with no issue reference | knip via `actions/deadcode/`, plus `semgrep/general/debug-print-left-behind.yaml` and `semgrep/general/todo-without-issue.yaml`, plus Layer 1 typescript-eslint |
| **C15** wiring analysis into a foreign project | none planted. The comparable artefact is `adopt.sh` on `examples/typescript-npm`, which the `adopt` and `examples` jobs already assert end to end | `adopt.sh`, via the existing CI evidence, for the JS/TS half only. The PHP half has no measurement here at all: PHP is not a language this baseline ships, and `CLAUDE.md` §4 is why — no in-house demand, so nothing exists to run |

### 3b. Claims that are not measurable, and why

Each of these is classified in [#162] on the seam test alone, and none can
become *covered*. The two exceptions are C17 and C18, which get no verdict at
all — §2 says why.

| Claim | Not measurable, because … |
|---|---|
| **C8** hypothesis lenses | the mechanism is model-mediated — three readers and a fourth reviewer. `docs/CONCEPT.md` §1 excludes AI review pipelines, and no deterministic fixture can stand in for a model's judgement. There is nothing to plant that would make it fire or fail to fire |
| **C9** recommendation-first questions | it is a property of prose the model emits during a session, not of an artefact in a tree. No exit code exists to observe |
| **C10** unattended mode | it is a mode of the product's own session loop. Nothing can be planted in a repository that would exercise it |
| **C11** twelve cold reviewers | model-mediated, same exclusion as C8 |
| **C13** zero symbols released | it is an invariant of the product's cleanup layer, asserted about the product's own runs. There is no artefact to plant, and the vendor's number is not reproducible from outside |
| **C14** crash-durable task list | session-state durability. It is a property of a running product, and this repo has no session to crash |
| **C16** licence key retrieval | it is a distribution mechanism for a paid product. `CLAUDE.md` §5 (free/OSS only) makes it a scope statement, not a detection question, and there is no fixture that would make it one |
| **C17** language support | it is a scope statement about the product, not a capability that fires. Its role in [#162] is to bound which of C1–C15 could apply to a tree this baseline ships for, and it is recorded as context on every other row rather than scored on its own |
| **C18** the counts | excluded in §0, and not classified at all |

**Every claim in §1 appears in exactly one of 3a or 3b.** That is the property
this section exists to hold: a claim that is awkward to test is written down as
awkward, with the reason, rather than dropped from the run because nobody
noticed it was missing.

---

## 4. The bar

**The only outcome that changes this baseline is a claim classified *gap* that
passes the seam test of D-e — it changes it by opening one issue for that one
claim, on its own evidence — and every other outcome changes nothing, including
a claim classified *covered*, a claim classified *declined*, and any count of
the three.** The milestone is not reopened on the score, and a total is not a
result here.

Three consequences, stated now so the run cannot argue them later:

- **A low score is not a failure of this baseline** and does not justify
  building anything. Every gap still has to pass the seam test, and most of the
  page's capabilities are about a session's behaviour rather than about this
  baseline — which is the D-e line, decided before the product was read.
- **A high score is not a reason to claim parity.** §5 says why: this is a
  comparison against advertising copy, not against a product that was run.
- **A gap does not become a detector by being recorded.** [#164] writes the
  decision; a follow-up issue that survives it builds one thing, with its own
  fixture, under the ordinary rule that a rule is justified by a real bug that
  got through.

---

## 5. What this cannot measure

- **The product was never run.** No licence was bought, nothing was installed,
  no session was observed. Nothing in this document or in [#162] is a statement
  about whether Code Guardian works.
- **Its internals were not examined.** The detectors are unnamed, the hooks are
  unnamed, and the one hook the page names is named in a demo. There is no
  ruleset to diff against `semgrep/`.
- **Marketing copy is evidence of a category, never of detection.** A claim on
  a vendor page establishes that someone sells this capability and thinks it
  worth advertising. It establishes nothing about hit rate, false positives, or
  what the thing does on a repository that is not the vendor's.
- **The vendor's own numbers are theirs.** "646 echte Migrationen geprüft", "342
  Tests für die Detektoren", the 36/36 in C12 — quoted where they belong to a
  claim, never carried into a comparison. They were produced by a method this
  repo cannot see, on a corpus it does not have.
- **The testimonial is one person.** The page says so itself and prints the
  weaknesses alongside; it is recorded here as context and is not evidence of
  anything measured.
- **The page is a moving target.** §0 already shows the headline counts
  differing from what [#152] recorded. Every quotation here is stamped
  2026-08-23; a later reader comparing against a newer page is comparing two
  different documents, and should re-fetch rather than assume drift is an error
  in this one.
- **Pricing is quoted, not assessed.** The page states 142,80 € once and 29,75 €
  a month, both inclusive of German VAT. Whether that is good value is not a
  question this document asks — `CLAUDE.md` §5 rules paid tooling out before
  price enters the argument, and a cheaper closed-source product would be ruled
  out identically.
- **Nothing about the consuming repos appears in this document, in the fixtures
  it pre-registers, or in the run that follows.** `CLAUDE.md` §2.

---

[#6]: https://github.com/maximalcode/maxi-quality/milestone/6
[#152]: https://github.com/maximalcode/maxi-quality/issues/152
[#158]: https://github.com/maximalcode/maxi-quality/issues/158
[#160]: https://github.com/maximalcode/maxi-quality/issues/160
[#161]: https://github.com/maximalcode/maxi-quality/issues/161
[#162]: https://github.com/maximalcode/maxi-quality/issues/162
[#163]: https://github.com/maximalcode/maxi-quality/issues/163
[#164]: https://github.com/maximalcode/maxi-quality/issues/164
