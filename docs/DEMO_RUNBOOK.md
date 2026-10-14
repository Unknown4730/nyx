# NYX demo runbook (about 10 minutes)

This is the script for showing NYX V1 to a lab group or examiner. Every result quoted
here was produced by the deterministic rules engine (rule pack `2026.10`) with AI switched
off. If you see different numbers, you have changed an input or a rule. The table in
[Expected sample results](#expected-sample-results) is the reference, and
`scripts/api_smoke.py` checks the same values against a running backend.

## Before you start

1. Start the API and the web client (see the README, quick start for your platform).
2. Run the readiness gate. It exits with status 0 only when the live service matches this
   runbook:

   ```bash
   .venv/bin/python scripts/api_smoke.py
   ```

   PowerShell: `.\.venv\Scripts\python.exe scripts\api_smoke.py`

3. Open **http://localhost:5173**. The header chip should read **API online**.
4. Optional: check the Projects page for saved projects you do not want to show. The three
   examples are created on first start and carry a *Sample* chip, so they cannot be
   mistaken for user work.

## 1. The promise (1 minute)

On the **Home** page, point out:

- “Rethink your architecture.” is the product line.
- The API and AI status are read from the running service, not hard-coded. With no AI
  endpoint configured, NYX says the rules engine is doing all the work.
- The method summary is the honest version: describe, analyse, decide.

## 2. A strong candidate (3 minutes)

1. Go to **New analysis**. Under *Sample applications*, choose **Online Examination
   Platform** and press *Use “Online Examination Platform”*. Samples are prefilled inputs,
   not stored answers: running one performs a fresh analysis.
2. Show the filled form. Fields with no information are shown as *Not stated*, not guessed.
   Click **Run analysis**.
3. On **Overview**:
   - The score gauge shows **78**. That is the rounded value of **78.1**; the exact score
     is in the JSON export.
   - The verdict is **strong candidate** and the pattern is serverless first.
   - *Method*: twelve factors. Each shows its weight, its effect and its evidence. Say:
     “This is the whole calculation. There is no hidden model.”
   - *Inputs*: each value is labelled by where it came from (you stated it, template value,
     inferred from text, or default).
4. Open **Architecture**:
   - Use the **Current (serverful)** and **Proposed (serverless-first)** views.
   - Click a box. The **Inspector** shows its tier, deployment target, the cloud service for
     the chosen provider, and warnings.
   - Switch the provider (AWS, Google Cloud, Azure). The same components are relabelled;
     nothing is deployed.
   - Keyboard: Tab to a component and press Enter. Expand *Text alternative* to show the same
     content as a table, for screen-reader users.
   - Long component names wrap onto two lines; the full name is in the tooltip.

## 3. Cost, honestly (2 minutes)

Open **Cost model**.

- The disclaimer and the unit are on screen: **RICU**, a *relative* monthly unit. No currency
  is implied.
- For this sample the proposed design is about **0.66×** the conventional one in the model.
- Scroll to *Sensitivity*. Say: “Conventional cost moves in steps when an instance is added;
  the proposed model moves with traffic. That is the elasticity argument, shown as a number.”

Talking point: “The model compares shapes of cost. It is not a budget. Prices, discounts and
data transfer tiers are out of scope, and the page says so.”

## 4. Security and migration (2 minutes)

- **Security**: for this sample the proposed design has no findings under the current rules.
  Do not oversell that. Point to *Verification gaps*: “These are the questions the model
  cannot answer from a description.” Then open the baseline risks: “The current design has
  real findings; the migration is judged against them.”
- **Migration**: nine phases, each with exit criteria. The *Per component* table says what
  changes and how complex each change is.

## 5. Save, reopen, export (2 minutes)

1. Click **Save project**. The header changes to *Saved to projects*.
2. Go to **Projects**. Filter *Samples* and *Mine* to show the difference. Open a sample.
   The same result appears.
3. Back on a result, click **Export Markdown**, then **Export JSON**. The Markdown file is a
   readable report with the same tables. The JSON file is the full contract (`nyx.analysis/1`).
   Both files are named from the analysis title, for saved and unsaved results alike.

## 6. The honest answer: a provisional verdict (2 minutes)

This is the most important part to demonstrate. Choose **Document Processing Pipeline** from
the samples and run it.

- The score is **53.9**, but the verdict is **further assessment required**. The provisional
  score of **67.0** is shown for orientation only.
- The *Missing inputs* list says why: traffic variability, statelessness and availability were
  not stated. The engine withholds a firm verdict when the missing weight reaches **30%** of
  the deciding weight.
- Say: “A tool that always gives a confident answer is less useful than one that tells you
  what to find out first.”

## Expected sample results

These are the reference values. `scripts/api_smoke.py` checks the score and outcome of each
sample against this table (`EXPECTED_SAMPLE_OUTCOMES`). If a rule change is deliberate,
update both places together.

| Sample (template id) | Score | Outcome | Pattern | Proposed ÷ conventional (model) |
| --- | --- | --- | --- | --- |
| College Attendance Portal (`college-attendance`) | 69.0 | suitable with modifications | serverless where suitable | 0.62× |
| Online Examination Platform (`online-examination`) | 78.1 | strong candidate | serverless first | 0.66× |
| Online Store (`ecommerce-application`) | 77.1 | suitable with modifications | serverless where suitable | 1.00× |
| Food Delivery Platform (`food-delivery-platform`) | 75.3 | suitable with modifications | serverless where suitable | 1.07× |
| Document Processing Pipeline (`file-processing-pipeline`) | 53.9 (provisional 67.0) | further assessment required | further assessment | 0.47× (not a verdict) |

The Online Store and Food Delivery samples show the proposed design costing about the same or
slightly more in the model. Mention this when asked whether serverless always saves money. It
does not, and NYX shows where it does not.

Other facts a check should see: each sample has twelve scoring factors; the migration plan has
10, 10, 8, 9 and 9 phases in the order above; the Document Processing Pipeline sample is the
only one whose verdict is withheld.

## Questions to expect

- **Is this a real price comparison?** No. It is a relative model in RICU. The method page
  explains each rate.
- **Does it deploy anything?** No. It never calls a cloud provider.
- **Does it need an AI key?** No. AI is optional and only fills requirement fields. It is off
  unless an endpoint is configured.
- **Can I trust the security findings?** They are architectural checks with stated certainty.
  They are not a penetration test or a compliance audit.
- **What happens with bad input?** Field-level messages appear next to the control. Nothing
  crashes, and no stack trace is shown.
- **Where do the rules live?** `backend/app/rules/`. The method is documented in
  [`METHODOLOGY.md`](METHODOLOGY.md) and the weights are read from the same code the API uses.

## If something goes wrong during the demo

- *“NYX cannot reach its API”* on the Projects page or in the header: the backend stopped.
  Restart it, then press the status chip in the header.
- *The Projects list is empty*: the examples are created on first start. Restart the backend
  with `NYX_SEED_EXAMPLES=1`, or delete the SQLite file under `backend/data/` to reset.
- *A result looks different from this runbook*: check that you ran the same sample, and that
  AI assist is off in the form (the result header says *Deterministic rules engine*).
