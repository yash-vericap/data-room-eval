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

## Keeping the answer key and baselines current

The answer key and the baseline runs come from the evaluation sheet. After the sheet changes,
download it as .xlsx and run:

```bash
python -m eval import-sheet path/to/sheet.xlsx
```

This rewrites `answer_key/`, `submissions/baseline/` and the sheet's manual decisions in
`reviews/decisions.json`. The import reads the sheets "Ground Truth", "Documents", "Baseline Runs"
and "Baseline Findings".

## Folders

- `answer_key/` the answer key (`library_v1.json`, development and withheld cases together) and the
  document list. Stays with the evaluator.
- `submissions/system/` runs of our system. `submissions/baseline/` runs of the baseline models.
- `reviews/decisions.json` every manual decision: the case a finding belongs to, the evidence check,
  the reasoning score and the reason.
- `data_room/<room>/` the PDFs and their text per page (`chunks.json`), used for the quote check
  and shown to the judge.
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

The judge runs on GitHub Models: free GPT models with a GitHub account. Put the token in `.env`
(copy `.env.example`) as `GITHUB_MODELS_TOKEN`. The default model is `openai/gpt-4.1-mini`; model
names change, so set `EVAL_JUDGE_MODEL` to one GitHub Models lists today if the default is gone.
No other provider is built in.

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
4. Download the sheet as .xlsx and run `python -m eval import-sheet path/to/sheet.xlsx`.
5. Run `python -m eval add-data-room` once more, or open "Method check": it lists every answer-key
   quote that is not found in the documents, which catches slips in the key before any run is scored.
6. Send runs with `"data_room": "HTC03"`.

Adding cases to an existing data room is steps 3 and 4 only. Freeze a new snapshot by changing the
"Snapshot" column (for example "Library v2"); the tool then writes `answer_key/library_v2.json`
and scores against the newest one.

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
