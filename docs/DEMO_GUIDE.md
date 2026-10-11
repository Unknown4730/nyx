# NYX demo guide (10 minutes)

This is a script for showing NYX V1 to a lab group or examiner. Every result quoted
below was produced by the deterministic rules engine (rule pack 2026.10) with AI
switched off. If you see different numbers, you have changed an input or a rule. Check
the audit document for the expected values.

## Before you start

1. Start the API and the web client (see the README, quick start for your platform).
2. Open **http://localhost:5173**. The header chip should read **API online**.
3. Optional: make sure no one has saved projects you do not want to show. The three
   examples are labelled *Sample* and cannot be confused with user work.

## 1. The promise (1 minute)

On the **Home** page, point out:

- “Rethink your architecture.” is the product line.
- The API status and the AI status are read from the running service, not hard-coded.
  With no AI endpoint configured, NYX says the rules engine is doing all the work.
- “How a result is produced” is the honest summary: describe, analyse, decide.

## 2. A strong candidate (3 minutes)

1. Go to **New analysis**. Under *Sample applications*, choose **Online Examination
   Platform** → *Use “Online Examination Platform”*.
2. Show the filled form. Point out that fields with no information are set to
   *Not stated*, not guessed. Click **Run analysis**.
3. On **Overview**:
   - Score **78.1**, verdict **Strong candidate**, pattern **Serverless first**.
   - *Method*: twelve weighted factors. Each shows its weight, its effect and its
     evidence. Say: “This is the whole calculation. There is no hidden model.”
   - *Inputs* table: each value is labelled *You stated it*, *Template value* or
     *Inferred from text*.
4. Open **Architecture**:
   - Use the **Current (serverful)** and **Proposed (serverless-first)** tabs.
   - Click a box. The **Inspector** shows its tier, deployment target, the cloud service
     for the provider chosen, and warnings.
   - Switch the provider (AWS, Google Cloud, Azure). The same components are relabelled;
     nothing is deployed.
   - Keyboard: Tab to a component and press Enter. Expand *Text alternative* to show
     the same content as a table, for screen-reader users.

## 3. Cost, honestly (2 minutes)

Open **Cost model**.

- The disclaimer and the unit are on screen: **RICU**, a *relative* monthly unit. No
  currency is implied.
- For this sample the proposed design is **0.66×** the conventional one in the model.
- Scroll to *Sensitivity*. Say: “Conventional cost moves in steps when an instance is
  added; the proposed model moves with traffic. That is the elasticity argument, shown
  as a number.”

Talking point: “The model is for comparing shapes of cost, not for budgeting. Prices,
discounts and data transfer tiers are out of scope, and the page says so.”

## 4. Security and migration (2 minutes)

- **Security**: the proposed design has no findings under the current rules. Do not
  oversell that. Point to *Verification gaps*: “These are the questions the model cannot
  answer from a description.” Then open *Baseline* risks: “The current design has real
  findings; the migration is judged against them.”
- **Migration**: nine phases, each with exit criteria. The *Per component* table says
  what changes and how complex each change is.

## 5. Save, reopen, export (2 minutes)

1. Click **Save project**. The header changes to *Saved to projects*.
2. Go to **Projects**. Filter *Samples* and *Mine* to show the difference. Click
   **Open** on a sample. The same result appears.
3. Back on a result, click **Export Markdown**, then **Export JSON**. Open the Markdown
   file: it is a readable report with the same tables. The JSON file is the full
   contract (`nyx.analysis/1`).

## 6. The honest answer: a provisional verdict (2 minutes)

This is the most important part to demonstrate. Choose **Document Processing Pipeline**
from the samples and run it.

- The score is **53.9**, but the verdict is **Further assessment required**. The
  provisional score of **67.0** is shown for orientation only.
- The *Missing inputs* list says why: traffic variability, statelessness and availability
  were not stated. The engine withholds a verdict when the missing weight reaches 30%.
- Say: “A tool that always gives a confident answer is less useful than one that tells
  you what to find out first.”

## Other results to know

| Sample | Score | Verdict | Pattern | Proposed vs conventional (model) |
| --- | --- | --- | --- | --- |
| Online Examination Platform | 78.1 | Strong candidate | Serverless first | 0.66× |
| College Attendance Portal | 69.0 | Suitable with modifications | Serverless where suitable | 0.62× |
| Online Store | 77.1 | Suitable with modifications | Serverless where suitable | 1.00× |
| Food Delivery Platform | 75.3 | Suitable with modifications | Serverless where suitable | 1.07× |
| Document Processing Pipeline | 53.9 (provisional 67.0) | Further assessment required | Further assessment | 0.47× (not a verdict) |

The Online Store and Food Delivery samples show the proposed design costing about the
same or slightly more in the model. Mention this when asked whether serverless always
saves money. It does not, and NYX shows where it does not.

## Questions to expect

- **Is this a real price comparison?** No. It is a relative model in RICU. The method
  page explains each rate.
- **Does it deploy anything?** No. It never calls a cloud provider.
- **Does it need an AI key?** No. AI is optional and only fills requirement fields.
  Turn it on in the form only when an endpoint is configured.
- **Can I trust the security findings?** They are architectural checks with stated
  certainty. They are not a penetration test or a compliance audit.
- **What happens with bad input?** Field-level messages appear next to the control.
  Nothing crashes, and no stack trace is shown.
- **Where do the rules live?** `backend/app/rules/`. The method is documented in
  `docs/METHODOLOGY.md` and the weights are read from the same code the API uses.

## If something goes wrong during the demo

- *“NYX cannot reach its API”*: the backend stopped. Restart it, then press the status
  chip in the header.
- *The Projects list is empty*: the examples are created on first start. Restart the
  backend with `NYX_SEED_EXAMPLES=1`.
- *A result looks different from this guide*: check that you ran the same sample, and
  that AI assist is off in the form (the result header says *Deterministic rules
  engine*).
