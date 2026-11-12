# Data room evaluation tool

Scores the findings of the discrepancy checker, and of every baseline model, against the answer key.
It covers Part D of the brief: load the answer key, load a run, match findings to cases, calculate
the metrics, list misses, false positives and wrong classes, check the evidence, and compare
systems and versions.

## Start

```bash
pip install -r requirements.txt
```

```bash
streamlit run app.py
```

```bash
python -m eval score
```

The second command opens the app. The third scores every stored run in the terminal and writes
`reports/report.md` and `reports/scores.csv`.

## Checking a Vericap run (the first screen)

`streamlit run app.py` opens on **Vericap run check**. It takes one run of our own system and answers five
questions: how much of the ground truth it found, what it missed, what it found only partly, what it
reported that the ground truth does not have, and how it ranks against the baselines.

The flow:

1. Pick the data room and, if you like, type a name for the run.
2. Paste the JSON, upload the file, or open an earlier check.
3. Press **Read the run**. The run does not have to follow the output contract. The tool finds the list
   of findings wherever it sits in the JSON, reads each field under any of its common names, and says
   what it could not read ("3 findings name no document"). Open "Every finding as read" to check it.
4. Press **Run the check**. It makes one model call per ground-truth case, then one per finding that
   maps to no case, then applies the rule gate.

What each status means:

| Status | Meaning |
|---|---|
| Found | A finding states the same problem with its essential facts. |
| Partially found | A finding is about the problem but leaves out or gets wrong an essential part. |
| Missed | No finding is about the problem. |
| Not flagged, Labelled correctly | A known non-issue was left alone, or mentioned as explained. |
| Wrongly flagged | A known non-issue was reported as a problem. |
| Real issue, not in ground truth | The documents show the issue. The ground truth does not have it. |
| Known change | The difference is a recorded change, or two forecasts that moved. |
| Not a discrepancy | The passages exist but agree, or differ on basis, phase or unit. |
| Not in documents | The figures or quotes are not in the pages. Invented or misread. |
| Needs review | The model could not decide, or its verdict failed a safeguard. |

The numbers:

- **Accuracy** is points over possible points. A found case earns its weight (Critical 8, High 4,
  Medium 2, Low 1). A partially found case earns half.
- **Backed by documents** is the share of findings tied to a found or partially found case, plus
  findings judged a real issue.
- **Against the baselines** ranks the run with the same fixed rules used for every run, with no manual
  decisions for our run. It can differ from the accuracy at the top, which comes from the model's verdicts.

Other things to know:

- **Manual verdicts.** Select a case in the coverage map and change its verdict with a reason. A manual
  verdict always wins. "Go back to the model's verdict" removes it.
- **Resuming.** Every verdict is saved the moment it exists. If the provider's limit stops the check,
  press the button again later and it carries on. The same run with the same model reopens the same check.
- **Downloads.** The report as Markdown and the full results as JSON.
- **Keep this run with the other runs** stores it in `submissions/system/` so the other screens show it.
- **Show baseline runs on the other screens** in the sidebar is off by default, so the other screens show
  only our runs until you tick it.
- **What was sent to the model** lists every document page that left the machine, and to which model.

## Sending a run to the tool

A run is one JSON file in the output contract (see `examples/example_run.json`, or the
"Add a run" screen). There are three ways in, and all three do the same thing: check the file
against the contract, store it under `submissions/`, score it.

1. Upload the file on the "Add a run" screen.
2. From the terminal:

```bash
python -m eval submit path/to/run.json
```

3. Over HTTP, so the discrepancy checker can post its result when it finishes:

```bash
python -m eval serve --port 8000
```

```bash
curl -X POST http://127.0.0.1:8000/runs -H "Content-Type: application/json" -d @path/to/run.json
```

A file that breaks the contract (a label that is not ours word for word, a citation with no quote,
a missing field) is rejected and nothing is stored. The reply lists every problem.

The HTTP reply holds the overall scores and the case-by-case results for the development set only.
Withheld cases never leave the tool. Set the environment variable `EVAL_API_KEY` to require the
same value in an `X-API-Key` header.

## Keeping the answer key up to date

The Google Sheet stays the place where cases, facts, documents, rules and baseline runs are written.
The tool loads its export and shows what will change before anything is written.

**Uploading the sheet.** On the **Upload evaluation sheet** screen, upload the .xlsx export. The tool
shows, per tab, how many rows are new, changed and removed, with before and after for every changed case
and fact. Blocking errors (a duplicate ID, a label outside the lists, a citation to an unknown document, a
quote in a new or changed row that is not in the document) switch off **Confirm**. Warnings do not. From
the terminal:

```bash
python -m eval import-sheet path/to/sheet.xlsx
```

```bash
python -m eval import-sheet path/to/sheet.xlsx --yes
```

The first prints the preview. The second writes.

**Tabs and columns.** The existing tabs are Ground Truth, Documents, Baseline Runs, Baseline Findings and
Severity Weights. Two tabs are new and optional: **Fact Sheet** and **Context Rules**. Documents has two
new optional columns: **Document date** and **Authority**. A tab that is missing leaves what is stored
untouched. **Download the sheet template** gives an empty workbook with every tab and column.

**Working draft and freezing.** Uploads and accepted candidates go to a working draft
(`answer_key/library_draft.json`). Frozen snapshots (`library_v1.json`, `library_v2.json`) never change.
Every screen scores against the snapshot chosen under **Answer key** in the sidebar; the newest frozen
snapshot is the default. **Freeze as Library vN** (or `python -m eval freeze`) turns the draft into the
next snapshot, with a copy of the facts and rules so an old score can be reproduced. From then on every
stored run, baselines included, is scored against it.

**Change log.** Every change to the answer key is written to `answer_key/changelog.json` with its reason
and where it came from (the file name or the check). The Upload evaluation sheet screen shows it.

**Candidate review.** When a check finds a real issue the ground truth does not have, it is a candidate.
The screen shows the claim, the evidence from each document side by side with the quote check, an
admission checklist, the three closest existing cases, and the model's case for and against. You then
accept it as a case, accept it as a non-issue case, reject it, or decide later. A reason is required.
Nothing enters the ground truth without that decision.

- An accepted case goes to the pending rows (`answer_key/pending.json`) and into the working draft at
  once. **Download pending rows** gives the rows in the exact Ground Truth columns to paste into the
  sheet. An upload that contains the case ID clears the row.
- A rejected finding is stored in `answer_key/rejected_candidates.json`. The same finding in a later
  check is rejected automatically (rule C13).
- "The ground truth is wrong here" on a case stores a correction request. The case changes only when
  the corrected sheet is uploaded.

**A run's own additions are reported apart.** Cases that came from a run keep their origin. The check
shows the accuracy with them and without them, so a run never looks better only because its own findings
were added to the answer key. No existing case is ever edited to turn a miss into a hit.

## The rule bundle

Some differences in a data room are known, not discrepancies. The rules say which. They are used three
ways: the model is shown them with every call, a rule pre-check reads the fact sheet before the model is
asked, and a rule gate decides afterwards what a reviewer needs to see.

There are three types. **Reject**: a finding outside the ground truth that the rule excuses is rejected.
**Flag**: the rule makes something a real issue, and such a finding is never rejected automatically.
**Guide**: helps the model read the documents and decides nothing alone.

| ID | Type | Rule |
|---|---|---|
| C1 | Reject | Documented change. A value changed through a dated document that records the change. Old and new are not a discrepancy. |
| C2 | Flag | Stale value after a change. A later or current document still carries the old value. |
| C3 | Flag | Unexplained change. Two current values and no document recording a change. |
| C4 | Reject | Two forecasts. Estimates or targets that differ in documents of different dates. |
| C5 | Reject | Forecast against actual. A forecast that differs from a later actual value. |
| C6 | Flag | Two actuals. Two values stated as actual for the same event. |
| C7 | Flag | Unexplained delay that matters. A late actual date that moves the credit year, a maturity or an installment, with no explanation. |
| C8 | Reject | Signed against draft. The signed version governs. |
| C9 | Reject | Different basis. Units, scope, gross against net, or phase. |
| C10 | Guide | Authority. The more authoritative document is taken as correct when naming the stale one. |
| C11 | Reject | Same event. "Launched" is not "placed in service" unless the fact sheet says so. |
| C12 | Reject | Immaterial difference. Rounding, formatting, typing errors, or money within the larger of $1,000 and 0.5%. |
| C13 | Reject | Decided before. The evaluator already rejected this finding in an earlier check. |
| C14 | Reject | Evidence not found. No quote is in the documents and the judge found the claim is not in the pages. |
| C15 | Reject | Out of scope. Advice and general risks, not a conflict or missing evidence. |

C1 to C9, C11, C12 and C14 are critical. A critical rule cannot be switched off in the sheet without a
reason in its Notes.

**The rule gate.** Every finding that maps to no case goes through these checks in order:

1. A Flag rule applies: never rejected. A candidate if the judge found a real issue, otherwise Needs review.
2. It repeats a candidate rejected before: rejected (C13).
3. None of its quotes is in the documents and the judge says not in documents: rejected (C14).
4. The pre-check and the judge agree on a Reject rule: rejected under that rule.
5. They disagree: Needs review, with both shown.
6. A real issue below `EVAL_MIN_CANDIDATE_SEVERITY` (default Medium): rejected as not a major red flag (C12).
7. Otherwise a real issue is a candidate, "cannot decide" is Needs review, and the rest is rejected.

Every rejection names its rule and reason, and **Restore** on the screen moves it to Needs review.

**Example 1, the price.** A credit purchase closed at $25. Later the rate moved and the price was reset
to $20, recorded in a repricing letter. In the fact sheet, R-a is $25 (Signed) and R-b is $20 (Signed,
supersedes R-a, change reason "rate reset", change source the letter).

- A finding that compares the original agreement with the repricing letter is a known change (C1).
- A finding that a deck dated after the reset still shows $25 is a real discrepancy (C2).
- If the repricing letter is not in the data room, R-b has no change source, and the two prices are an
  unexplained change (C3).

**Example 2, the dates.** A legal document gives a placed in service date of 3 November 2024. Another
gives 4 June 2025 with no reason for the delay.

- Both are estimates or targets, in documents of different dates: two forecasts that moved (C4).
- Both are stated as actual dates for the same event: a contradiction (C6).
- The first is a forecast and the second is actual: not a contradiction (C5). But the event moved into
  another year, which can move the credit year, so with no explanation it is missing evidence (C7).
- The second document says "launched" and the fact sheet does not map that to placed in service: the
  dates are not compared (C11).

**Rules as test cases.** A case is a test case for a rule when its Scenario tags name the rule ID (for
example `C1`). The **Rules and facts** screen shows, per rule and data room, how many test cases exist
and where one is missing. Flagging a known change then counts against the run as Wrongly flagged.

**Changing rules and facts.** Edit the Context Rules and Fact Sheet tabs in the sheet and upload it.
Until a Context Rules tab is uploaded, the default rules above are used. The Fact Sheet columns are Fact
ID, Data room, Subject, Scope, Value, Unit or basis, Value status (Actual, Signed, Approved, Estimate,
Target, Projected, Draft, Superseded), As of, Source, Supersedes, Change reason, Change source and Notes.

## Data security and storage

**What leaves the machine.** A hosted model receives the page text sent to it over the internet. No
setting changes that. What the tool guarantees:

- The model gets no tools. No request carries tools, functions, MCP servers, web search, files or URLs.
  Every request body is checked just before it is sent.
- Requests go to one endpoint. The host is checked against `EVAL_ALLOWED_HOSTS`, which defaults to the
  configured provider's host. Anything else is refused.
- One task, one call. Each call holds the system prompt and one message with one case or one finding,
  its pages and its context. No history, nothing carried between calls, temperature 0.
- No made-up answers. Fixed answer formats, "cannot decide" always allowed, every case verdict must
  quote a passage that is checked against what was shown, and finding IDs and rule IDs are checked
  against the real lists. The model can never add a case or change a label.
- An audit. Each check stores which document pages were sent, to which provider and model.
- Page text, prompts and answers are never printed to the console or logs.

**The data policy.** `EVAL_DATA_POLICY` is `strict` by default. Strict allows a model on this machine or
a private network, and providers you name in `EVAL_TRUSTED_PROVIDERS`. A free tier, whose terms may keep
or train on inputs, is refused unless you allow it on purpose. `open` allows every preset and shows a
warning on every screen. To keep using GitHub Models, add one of these to `.env`:

```bash
EVAL_TRUSTED_PROVIDERS=github
```

```bash
EVAL_DATA_POLICY=open
```

**Using a local model.** For documents that must never leave your machines, run a model locally, for
example with Ollama, and set:

```bash
EVAL_JUDGE_PROVIDER=local
EVAL_JUDGE_MODEL=the-model-name-your-server-runs
```

The default address is `http://localhost:11434/v1`; set `EVAL_JUDGE_BASE_URL` for another one.

**Document storage in MongoDB.** The data room does not have to live in the repository. With `MONGO_URI`
set, the page text is kept in MongoDB, and the PDFs too if you ask. Without it, everything is read from
`data_room/` as before.

Set it up one of two ways:

- **The local container.** `docker-compose.yml` has a `mongodb` service with its own volume. Start it and
  point the tool at it:

  ```bash
  docker compose up -d mongodb
  ```

  ```bash
  MONGO_URI=mongodb://admin:secret@localhost:27017/?authSource=admin
  ```

  Change the password in `docker-compose.yml` before using it anywhere shared.
- **MongoDB Atlas.** A free cluster (M0, 512 MB) is enough: the two current data rooms are about 12 MB of
  PDFs and under 1 MB of text. Atlas keeps the text on MongoDB's cloud. Use the `mongodb+srv://` address,
  and under the strict policy add the cluster's host to `EVAL_ALLOWED_HOSTS`, next to the model's host.

`MONGO_DB` names the database (default `dataroom_eval`). A host that is not on this machine must use TLS.

Move the rooms that are already in `data_room/`:

```bash
python -m eval move-to-mongo --with-pdfs
```

Each room is written, read back and compared page by page (and PDF by PDF). Only when that passes is its
local folder deleted. Leave out `--with-pdfs` to store the text only, name rooms with `--rooms HTC01`, and
add `--keep-local` to keep the folder. A failed check keeps the folder and says what failed.

A new data room goes straight to MongoDB:

```bash
python -m eval add-data-room path/to/HTC03.zip
```

Set `EVAL_STORE_PDFS=1` to store its PDFs as well. `--keep-local` also writes the local copies.

When MongoDB cannot be reached, every screen says so. Scoring that does not need page text still works,
and quote checks show "Not checked" until it is back. The sidebar shows where the document text comes from.

## Folders

- `answer_key/` stays with the evaluator. It holds:
  - `library_v1.json`, `library_v2.json`, ... the frozen answer keys (development and withheld cases together);
  - `library_draft.json` the working draft;
  - `documents.json` the document list, with document date and authority when the sheet gives them;
  - `facts.json` the fact sheet and `context_rules.json` the rules, once uploaded;
  - `pending.json` accepted candidates and correction requests not yet in the sheet;
  - `rejected_candidates.json` findings the evaluator rejected;
  - `changelog.json` every change to the answer key.
- `reality_checks/` one file per Vericap run check, with every verdict and what was sent to the model.
- `submissions/system/` runs of our system. `submissions/baseline/` runs of the baseline models.
- `reviews/decisions.json` every manual decision: the case a finding belongs to, the evidence check,
  the reasoning score and the reason.
- `data_room/` is no longer kept in the repository once MongoDB is set up: the page text and PDFs live
  there (see "Data security and storage"). Without `MONGO_URI`, `data_room/<room>/` holds the PDFs and
  their text per page (`chunks.json`).
- `judge/verdicts.json` every judge verdict.
- `reports/` the written report and the score table.
- `eval/` the scripts. `app.py` the Streamlit app. `tests/` the checks on the scoring.

## How a finding is matched to a case

Rule-based, the same answer every time (`eval/matching.py`).

1. Location. A case is a candidate when the finding cites at least one of its documents.
2. Content. Each candidate pair gets a score from three parts: overlap of cited documents and pages
   (30%), share of the case's key values found in the finding (35%), and similarity of wording (35%).
   Values are compared in a standard form, so $24,600,000, $24.6M and "24,600 ($ in thousands)" are
   the same, and so are July 15, 2025 and 7/15/2025.
3. Review. A score of 0.50 or more is a match. Between 0.36 and 0.50 the finding goes to the review
   queue. Below that it is a false positive candidate. A manual decision always wins.

After matching: the best copy of a repeated finding counts and the rest are duplicates, not false
positives. A finding can be linked to two cases when it merges them. When a negative case and a
reportable case sit side by side (signed against draft is fine; the model relying on the draft is
not), the finding goes to the reportable one only if it cites a document that only that case involves.

The "Method check" screen runs the matcher with all manual decisions switched off and compares it
with them.

## Metrics

- Headline: severity-weighted recall on the withheld set (Critical 8, High 4, Medium 2, Low 1).
- Recall, Critical cases missed, the list of missed cases.
- Precision: valid findings over findings, duplicates left out. A finding waiting in the review
  queue counts as a finding but not as a valid one.
- False positives: findings with no case, plus negative cases reported under the wrong class. A
  negative case reported with its correct label is not a false positive.
- Class accuracy and severity accuracy over matched findings, and the expected-against-reported grid.
- Evidence: relevant (citations point at pages the answer key cites), sufficient (every document
  the case rests on is cited; a manual check replaces this rule), real (every fragment of the quote
  found on the cited page or one page either side, with a tolerance for scan errors). A quote found
  nowhere in its document is listed as "not found" and needs a look: it is either invented, or
  reworded by the model.
- Reasoning score 0 to 2, from manual review.
- Reliability across repeated runs: cases found in every run, some runs, no run, and the spread of
  weighted recall.
- Breakdown by class, severity, check type, scenario, set, document type and document format.
- Time, tokens and cost per run and per valid finding.
- Ambiguous cases are also scored apart from the rest.

A system is "better" than another only when weighted recall rises on the same answer key and no
Critical case found before is now missed.

## The LLM judge (approach B)

The judge and the run check use the same model. Two set-ups are built in:

- **A local model** (`EVAL_JUDGE_PROVIDER=local`), allowed under the strict data policy. See "Data
  security and storage".
- **GitHub Models**, free GPT models with a GitHub account. Put the token in `.env` as
  `GITHUB_MODELS_TOKEN`. It is a free tier, so it must be allowed on purpose with
  `EVAL_TRUSTED_PROVIDERS=github`. The default model is `openai/gpt-4.1-mini`; set `EVAL_JUDGE_MODEL`
  to one GitHub Models lists today if the default is gone.

```bash
python -m eval judge
```

Judges every stored finding that has no verdict yet. Name runs to judge only those:
`python -m eval judge HTC02-R1`. A run sent through `submit`, the app or the endpoint is judged
straight away when a key is present.

The free tier limits requests per minute and per day. The tool paces itself (`EVAL_JUDGE_RPM`), waits
out short limits, and when the daily allowance is used up it stops, keeps every verdict made so far
and tells you to run the same command again later. Each finding costs two requests (it is judged
twice); `EVAL_JUDGE_PASSES=1` halves that and gives up the stability check.

For each finding the judge sees the finding, the three closest answer-key cases and the text of the
cited pages (excerpts around the quoted words when a model's input limit is small). It returns the
columns that were filled in by hand for the baselines: the matched case, whether the class is right,
the evidence check, the reasoning score 0 to 2, the passage it relies on and one line of
explanation. Verdicts are stored in `judge/verdicts.json`.

Safeguards:

- The answer must follow the fixed format, and the quoted passage is checked by rule against what
  the judge was shown. A verdict that fails either check is asked once more, then sent to manual review.
- Every finding is judged twice, at temperature 0 where the provider accepts it. Two different
  verdicts mark it unstable.
- "Cannot decide", a disagreement with the answer key, and any run from the judge's own model
  family (the GPT judge on a ChatGPT baseline) go to manual review.
- The judge never changes the headline score. The "Judge versus rules" screen shows the scores
  three ways (rules plus manual, rules alone, judge alone) and lists every disagreement with the
  form to record your decision. "Method check" reports how often the judge agrees with you.

GitHub Models may keep what is sent to it. The judge sends answer-key cases and document pages.

## Working in VS Code

1. Unzip the project and open the folder: File > Open Folder > `dataroom-eval`.
2. Install the Python extension when VS Code offers it (Python 3.10 or newer must be installed).
3. Open a terminal (Terminal > New Terminal) and create the environment:

```bash
python -m venv .venv
```

4. Activate it. Windows: `.venv\Scripts\activate`. Mac or Linux: `source .venv/bin/activate`.
   Then pick it in VS Code: Ctrl+Shift+P > "Python: Select Interpreter" > `.venv`.
5. Install the packages:

```bash
pip install -r requirements.txt
```

6. Copy `.env.example` to `.env` and paste your judge key into it.
7. Run things from Terminal > Run Task: "Eval: open the app", "Eval: score all runs",
   "Eval: run the judge", "Eval: submit a run file", "Eval: start the endpoint", "Eval: run the tests".
   Ctrl+Shift+B opens the app directly.

Both data rooms are already read in, so nothing else is needed to score and judge. Reading a new
data room with scanned pages needs two extra programs on the machine: Tesseract (OCR) and Poppler
(`pdftotext`, `pdftoppm`). Without them, pages with a text layer are still read and scanned pages
are reported as unreadable.

## Adding a data room

1. Name the PDFs `DOC-01_...pdf`, `DOC-02_...pdf` and so on, in a folder or zip whose name starts
   with the data room ID, for example `HTC03_Project_Name.zip`.
2. Read the documents into the tool:

```bash
python -m eval add-data-room path/to/HTC03_Project_Name.zip
```

   Pages with a text layer are read directly, scanned pages by OCR. The command prints, per
   document, how many pages needed OCR and which could not be read.
3. In the sheet, add the documents to "Documents" and the cases to "Ground Truth", with the data
   room ID in the "Data room" column and case IDs that start with it (`HTC03-001`).
4. Download the sheet as .xlsx and upload it on the Upload evaluation sheet screen, or run `python -m eval import-sheet path/to/sheet.xlsx --yes`.
5. Run `python -m eval add-data-room` once more, or open "Method check": it lists every answer-key
   quote that is not found in the documents, which catches slips in the key before any run is scored.
6. Send runs with `"data_room": "HTC03"`.

Adding cases to an existing data room is steps 3 and 4 only. The cases go to the working draft; freeze it
on the Upload evaluation sheet screen (or `python -m eval freeze`) to write the next `library_vN.json`
and score every run against it.

## Putting it on a server

The tool keeps its data in files, so it needs a machine with a disk that survives restarts. A small
Linux server with Docker is enough.

1. Copy this folder to the server.
2. `cp .env.example .env` and fill in the app password, the endpoint key and the judge key.
3. Start it:

```bash
docker compose up -d --build
```

The app is on port 8501 and the endpoint for the discrepancy checker on port 8000. All data lives
in the `eval-data` volume. The container refuses to start without a password and an endpoint key,
because the app shows the withheld answer key.

Put a reverse proxy with HTTPS (Caddy or nginx) in front before sharing the address, and open the
two ports only to it.

To update the code later: copy the new folder over, run the same command again. The data volume is
kept. To back up: copy the volume, or the folders `answer_key`, `submissions`, `reviews`, `judge`
and `data_room`.

## Tests

```bash
python -m pytest -q
```
