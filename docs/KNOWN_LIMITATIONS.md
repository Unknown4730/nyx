# NYX known limitations

This page lists what NYX V1 does not do, what it does not claim, and what was not verified.
Each item says where it matters. Nothing here is hidden elsewhere in the product; these are the
boundaries a presenter or reader needs to know.

## Scope boundaries (by design)

- **No provisioning.** NYX never creates, changes or calls cloud infrastructure. The architecture
  is a conceptual blueprint.
- **No live prices.** The cost model compares *relative* monthly units (RICU) from rates in
  `backend/app/rules/cost_rates.py`. There is no currency, no discount model, no reserved capacity,
  no data-transfer tiers, and no price has been checked against a provider's price list in this
  release. Do not present a RICU figure as a price.
- **No compliance or certification claims.** The security review checks the architecture described.
  It is not a penetration test, a formal audit, or a statement of regulatory compliance.
- **Out of scope for V1:** billing, subscriptions, advertising, real cloud provisioning, enterprise
  authentication, multi-user accounts and production hosting.
- **Single local user.** Saved projects live in a local SQLite file. There is no authentication,
  no per-user separation and no sharing.

## Analysis limits

- **Scores are rule-based heuristics** over the description and the structured fields. Their value
  depends on how specific the input is. The provisional verdict exists so that gaps are visible: when
  the missing weight reaches 30% of the deciding weight, NYX withholds a firm verdict. The sample
  *Document Processing Pipeline* is the example.
- **Free-text extraction is keyword-based.** A requirement the keyword rules do not recognise will be
  recorded as not stated rather than guessed.
- **Assumptions are labelled, not hidden.** Where the engine supplies a default, the result says so
  (for example, “was not stated; the engine assumed 350”). Those defaults are the engine's, not the
  user's, and may not match a real system.
- **The gauge shows whole numbers.** The score 78.1 is displayed as 78. The exact value is in the
  JSON export and the API.
- **Summary wording.** The narrative sentence in the Markdown report counts only the factors with a
  non-neutral effect (for example “from 10 weighted factors”), while the factor table lists all twelve.
  The two numbers are both correct but can read as a contradiction.
- **Assumption wording changed in this release.** Assumption sentences now say “the engine assumed X”
  and use readable labels (“object storage”, “steady CRUD”). The values are unchanged; the parity check
  in the completion audit confirms this for all five samples.

## Governance decision awaiting owner sign-off

- **The 0.34 component-level gate was removed.** `COMPONENT_MISSING_WEIGHT_LIMIT = 0.34` could never fire,
  because the largest missing weight a component can carry is 0.26. It was removed in this release
  rather than kept as dead code. A comparison of the full engine output for all five samples before and
  after showed no change to any score, outcome, cost, security finding, migration phase or architecture.
  Because `backend/docs/SUITABILITY_ENGINE.md` previously recorded this as a deliberate, owner-level
  decision, the project owner should confirm the removal. Until then it is recorded as a decision awaiting
  sign-off, not as settled.

## Architecture diagram

- **Fit at desktop width.** The default view is 100% so that labels are readable. The *Fit to width*
  control goes down to a 40% floor. At 1440px the proposed diagram at 40% can still be wider than its
  panel, so its right-hand boxes are reached by scrolling inside the diagram region.
- **Cosmetic space on mobile.** At 390px there is a large empty area above the first column of the
  diagram. The diagram scrolls horizontally inside its own region, as intended. The empty area is
  cosmetic and was not fixed.
- **Keyboard.** Tab moves between components and Enter selects one. The full focus order across the
  whole results page was not audited.

## Verification gaps

- **AI-assisted path.** No OpenAI-compatible endpoint was configured in the sandbox, so the AI path was not
  exercised end to end. The disabled path, timeouts, rate limits, malformed output and provider errors are
  covered by `backend/tests/test_ai_provider.py`. When AI is off, every result says it was produced by the
  deterministic rules engine.
- **Windows.** The PowerShell instructions in the README are the standard equivalents. They were not run on
  a Windows machine by the project team.
- **Browsers and devices.** The browser walkthrough runs in Chromium. Mobile was checked by viewport
  emulation at 390px, not on real devices. Other browsers were not tested.
- **Accessibility.** Checks are by unit tests, keyboard use and inspection. No automated accessibility
  audit or screen-reader session was run for this release.
- **Catalogue links.** The 81 service links point to provider documentation. They were not re-checked
  against the live sites in this release.
- **Independent review.** None was performed. The completion audit is a self-audit.

## Data and content

- The five sample applications are **synthetic** and labelled as samples. They are prefilled inputs,
  not stored answers.
- The three example projects created on first start are labelled *Sample* and generated by the real
  pipeline.
- The local demo database accumulates the projects you save during a demonstration. Delete the ones you
  do not want from the Projects page, or reset the SQLite file under `backend/data/`.

## Open items

The open defects, with their priority and status, are listed in the completion audit:
[`audits/NYX_COMPLETION_AUDIT.md`](audits/NYX_COMPLETION_AUDIT.md#open-items). That table is the
source of truth for what remains open; this page describes the limits that will stay in V1.
