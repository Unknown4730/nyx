# NYX: college lab submission report

**Project:** NYX, AI-assisted serverless migration and cloud architecture advisor (V1)
**Context:** College Cloud Computing lab project
**Status of this report:** describes the V1 release as verified on 2026-10-14. The evidence is in
[`audits/NYX_COMPLETION_AUDIT.md`](audits/NYX_COMPLETION_AUDIT.md).

## 1. Problem

Teams often ask whether an application should move to serverless computing, and what the cloud
architecture would look like on AWS, Google Cloud or Azure. Many tools answer with a confident
recommendation and no visible reasoning. NYX takes the opposite approach: it gives a verdict only as
far as the stated evidence allows, shows each factor, and lists what it does not yet know.

## 2. What NYX does

Given an application description and optional structured fields, NYX:

1. extracts requirements and records where each value came from (stated, from a template, inferred from
   text, or a default);
2. classifies the workload and identifies logical components;
3. produces a conventional (serverful) and a proposed (serverless-first) architecture, with cloud service
   mappings from a catalogue of 81 services;
4. scores serverless suitability from twelve weighted factors, with a provisional verdict when too much
   weight rests on missing inputs;
5. compares relative monthly cost in an explicitly labelled relative unit (RICU), with sensitivity to
   traffic;
6. lists architecture-level security findings with certainty levels, baseline risks and verification gaps;
7. proposes a phased migration plan with exit criteria;
8. saves analyses as projects, and exports Markdown and JSON reports.

NYX does not provision infrastructure and does not call a cloud provider.

## 3. Design decisions

- **Deterministic core.** The rules engine needs no paid service, API key, cloud account or database server.
  The same input gives the same result.
- **Optional AI, clearly labelled.** An OpenAI-compatible endpoint can be configured to propose
  requirement values. It cannot replace the rules, and every result states whether AI was used.
- **One source of truth.** The backend computes every score, cost and finding. The web client renders them.
- **Explainability over precision.** Every score lists its factors and evidence. Missing evidence is never
  counted as favourable.
- **Honest scope.** Cost is a relative model, not a price. The security review is architectural, not a
  penetration test or a compliance certification.

## 4. Architecture

A FastAPI backend holds the rules, the pipeline and a SQLite project store. A React and Vite web client calls
it through same-origin `/api` paths. Details are in [`ARCHITECTURE.md`](ARCHITECTURE.md). The HTTP contract,
including the error envelope and input limits, is in [`API_CONTRACT.md`](API_CONTRACT.md).

## 5. Evidence of results

Five synthetic sample applications are included. They are prefilled inputs; choosing one runs a fresh
analysis. The documented results, produced by the rules engine with AI off, are:

| Sample | Score | Outcome |
| --- | --- | --- |
| College Attendance Portal | 69.0 | suitable with modifications |
| Online Examination Platform | 78.1 | strong candidate |
| Online Store | 77.1 | suitable with modifications |
| Food Delivery Platform | 75.3 | suitable with modifications |
| Document Processing Pipeline | 53.9 (provisional 67.0) | further assessment required |

The Document Processing Pipeline is the deliberate example of an honest “not yet”: too much of its deciding
weight rests on inputs the description did not state.

## 6. Verification

- Backend tests: 310 passed.
- Frontend tests: 62 passed across six files; typecheck, lint (no warnings allowed) and production build pass.
- Live API smoke test: 25 of 25 checks, including the sample results above.
- Browser walkthrough in Chromium: 23 of 23 steps, from sample to verdict, architecture inspection, save,
  reopen, export and validation, with no page or console errors.
- Engine parity: for all five samples, scores, outcomes, cost, security, migration and architectures match
  the previous release. Only assumption wording changed.

Commands and their expected results are in [`TESTING.md`](TESTING.md).

## 7. Limitations

The main limits are listed in [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md). In brief:

- Scores are heuristics over the description; their value depends on how specific it is.
- Cost figures are relative units, not prices. No live price was checked.
- The security review does not replace a penetration test or a compliance audit.
- The AI-assisted path was not tested against a real endpoint in this release.
- The PowerShell instructions were not run on Windows by the project team.
- The architecture diagram at desktop width may need horizontal scrolling at its smallest zoom.
- An independent review has not been performed.

One governance point is for the project owner to confirm: a dormant engine gate (0.34) was removed in this
release, with no change to any output. See section 6 of the completion audit.

## 8. How to run it

Quick-start steps for macOS, Linux and Windows PowerShell are in the [README](../README.md). The
demonstration script is [`DEMO_RUNBOOK.md`](DEMO_RUNBOOK.md).

## 9. Use of tools and sources

- The rules, weights and catalogue were written for this project. The method is described in
  [`METHODOLOGY.md`](METHODOLOGY.md).
- Service names and links in the catalogue refer to provider public documentation, used for comparison.
  They were not re-checked against live pages in this release.
- Development was assisted by an AI coding agent. The evidence in this report comes from the recorded command
  runs listed in the completion audit and in `TESTING.md`.
