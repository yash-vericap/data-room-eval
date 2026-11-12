# Data room evaluation report

Generated 2026-11-12 02:09. Answer key: Library v1, 81 cases. Runs scored: 11.

The headline number is severity-weighted recall on the withheld set. Every run is scored with the same matching, the same metrics and the same answer key.

## Scores per run

| Run | Source | Data room | Weighted recall | Recall | Found | Reportable | Critical missed | Precision | False positives | Class accuracy | Severity accuracy | Evidence sufficient | Reasoning (0-2) | Needs review | Minutes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Grok4.7 | Baseline model | HTC01 | 98.0% | 95.0% | 19 | 20 | 0 | 92.3% | 0 | 92.0% | 72.0% | 96.0% | 1.88 | 2 | 11.50 |
| CLAUDE SONNET 5.5 | Baseline model | HTC01 | 95.9% | 95.0% | 19 | 20 | 0 | 83.3% | 0 | 100.0% | 80.0% | 96.0% | 1.92 | 5 | 4.30 |
| Gemini 3.8 flash | Baseline model | HTC01 | 93.9% | 90.0% | 18 | 20 | 0 | 95.8% | 0 | 100.0% | 87.0% | 95.7% | 1.91 | 1 | 4.20 |
| Grok4.7-R2 | Baseline model | HTC01 | 93.9% | 90.0% | 18 | 20 | 0 | 92.3% | 0 | 95.8% | 79.2% | 95.8% | 1.88 | 2 | 12.50 |
| GEMINI_Flash2.5 | Baseline model | HTC01 | 83.7% | 75.0% | 15 | 20 | 0 | 90.9% | 1 | 95.0% | 75.0% | 95.0% | 1.85 | 1 | 6.00 |
| DEEPSEEK-R1 | Baseline model | HTC01 | 79.6% | 70.0% | 14 | 20 | 0 | 90.5% | 1 | 94.7% | 73.7% | 94.7% | 1.84 | 1 | 2.00 |
| Gemini-3.8 | Baseline model | HTC01 | 69.4% | 70.0% | 14 | 20 | 2 | 90.5% | 0 | 94.7% | 94.7% | 89.5% | 1.68 | 2 | 4.40 |
| CHATGPT-R1 | Baseline model | HTC01 | 63.3% | 55.0% | 11 | 20 | 1 | 93.8% | 0 | 100.0% | 66.7% | 100.0% | 1.87 | 1 | 15.00 |
| Gemini flash 3.8 | Baseline model | HTC01 | 61.2% | 50.0% | 10 | 20 | 1 | 93.3% | 0 | 100.0% | 92.9% | 100.0% | 1.93 | 1 | 4.40 |
| CHATGPT-HTC02-R1 | Baseline model | HTC02 | 73.5% | 63.6% | 14 | 22 | 0 | 100.0% | 0 | 95.0% | 60.0% | 100.0% | 1.95 | 0 | - |
| HTC02-R1 | Baseline model | HTC02 | 67.3% | 68.2% | 15 | 22 | 2 | 81.8% | 0 | 90.5% | 52.4% | 95.2% | 1.81 | 4 | - |

## Systems, averaged over repeated runs

| System | Source | Runs | Weighted recall | Lowest | Highest | Found in every run | Some runs | No run | Precision | Class accuracy | Minutes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Grok Build, April 2026 BP-v1 · HTC01 | Baseline model | 1 | 98.0% | 98.0% | 98.0% | 19 | 0 | 1 | 92.3% | 92.0% | 11.50 |
| Claude Sonnet 5.5 BP-v2 · HTC01 | Baseline model | 1 | 95.9% | 95.9% | 95.9% | 19 | 0 | 1 | 83.3% | 100.0% | 4.30 |
| Grok 4.7 BP-v2 · HTC01 | Baseline model | 1 | 93.9% | 93.9% | 93.9% | 18 | 0 | 2 | 92.3% | 95.8% | 12.50 |
| Gemini 2.5 Flash BP-v1 · HTC01 | Baseline model | 1 | 83.7% | 83.7% | 83.7% | 15 | 0 | 5 | 90.9% | 95.0% | 6.00 |
| DeepSeek-V3.2 BP-v2 · HTC01 | Baseline model | 1 | 79.6% | 79.6% | 79.6% | 14 | 0 | 6 | 90.5% | 94.7% | 2.00 |
| Gemini 3.8 Flash BP-v2 · HTC01 | Baseline model | 2 | 77.6% | 61.2% | 93.9% | 10 | 8 | 2 | 94.6% | 100.0% | 4.30 |
| Gemini 3.8 Flash BP-v1 · HTC01 | Baseline model | 1 | 69.4% | 69.4% | 69.4% | 14 | 0 | 6 | 90.5% | 94.7% | 4.40 |
| OpenAI ChatGPT BP-v2 · HTC01 | Baseline model | 1 | 63.3% | 63.3% | 63.3% | 11 | 0 | 9 | 93.8% | 100.0% | 15.00 |
| ChatGPT (GPT-5) BP-v3 · HTC02 | Baseline model | 1 | 73.5% | 73.5% | 73.5% | 14 | 0 | 8 | 100.0% | 95.0% | - |
| Gemini 3.8 Flash BP-v3 · HTC02 | Baseline model | 1 | 67.3% | 67.3% | 67.3% | 15 | 0 | 7 | 81.8% | 90.5% | - |

Reliability needs at least two runs of the same system, version and data room. With one run, "found in every run" only repeats that run.

## Our system against the others

No run from our system has been submitted yet. Only baseline models are scored below.

## Each run in detail

### CHATGPT-R1 (OpenAI ChatGPT, HTC01)

Weighted recall 63.3% (62 of 98 points), recall 55.0% (11 of 20 withheld cases), precision 93.8%, 0 false positives, 1 findings waiting for a manual decision.
Development set: weighted recall 85.7% (4 of 6 cases). Withheld set without the ambiguous cases: 66.0%.

Missed cases:

- HTC01-002 (Critical, Withheld): Budget counts non-qualifying costs as QRE
- HTC01-003 (High, Withheld): Cost certification leaves out the change orders
- HTC01-006 (High, Withheld): Memo says the project is fully funded, but the budget shows a gap
- HTC01-014 (High, Withheld): Equity installments do not add up to the equity amount
- HTC01-035 (High, Withheld): Financial model puts the whole federal credit in 2025
- HTC01-037 (High, Withheld): Equity bridge loan matures before the installment meant to repay it
- HTC01-038 (High, Withheld): Model expects state credit proceeds after the buyer can walk away
- HTC01-026 (Medium, Withheld): Deposit payment is backed only by an email
- HTC01-027 (Medium, Withheld): Adjusted basis in the substantial rehabilitation test has no readable source
- HTC01-028 (Medium, Development): Model assumes faster lease-up than the market study supports
- HTC01-018 (Low, Development): Owner name is misspelled on the architect's documents

Findings with no confirmed case:

- CHATGPT-R1-F14 (Needs review): The GC agreement is dated June 5, 2023 but includes drawings dated July 20, 2023 and the Part 2 approval dated August 22, 2023.

Recall by severity:

| severity | reportable | found | recall |
|---|---|---|---|
| Critical | 7 | 6 | 85.7% |
| High | 13 | 7 | 53.8% |
| Low | 1 | 0 | 0.0% |
| Medium | 5 | 2 | 40.0% |

Recall by class:

| class | cases | reportable | found | recall | negative | false_alarms | class_accuracy |
|---|---|---|---|---|---|---|---|
| Consistent | 8 | 0 | 0 | - | 8 | 0 | - |
| Contextual difference | 5 | 0 | 0 | - | 5 | 0 | - |
| Contradiction | 21 | 21 | 12 | 57.1% | 0 | 0 | 100.0% |
| Insufficient evidence | 5 | 5 | 3 | 60.0% | 0 | 0 | 100.0% |

### CLAUDE SONNET 5.5 (Claude Sonnet 5.5, HTC01)

Weighted recall 95.9% (94 of 98 points), recall 95.0% (19 of 20 withheld cases), precision 83.3%, 0 false positives, 5 findings waiting for a manual decision.
Development set: weighted recall 100.0% (6 of 6 cases). Withheld set without the ambiguous cases: 95.7%.

Missed cases:

- HTC01-035 (High, Withheld): Financial model puts the whole federal credit in 2025

Findings with no confirmed case:

- CLAUDE SONNET 5.5-F16 (Needs review): The cost certification is marked as a draft not for reliance, yet the memo says it shows $24.6 million, and the schedule records cost certification as an actual completed milestone.
- CLAUDE SONNET 5.5-F17 (Needs review): The cost certification notes on developer fee, indirect costs and related-party costs contain only generic text, so the $640,000 qualified developer fee and any related-party costs cannot be verified.
- CLAUDE SONNET 5.5-F23 (Needs review): The financial model is dated March 1, 2025 but reports events that had not yet happened and refers to a price first reported on March 4, 2025.
- CLAUDE SONNET 5.5-F25 (Needs review): The schedule is stated to be updated July 20, 2025 and to show actual dates through milestone 16, but milestones 15 and 16 are dated September 2025.
- CLAUDE SONNET 5.5-F30 (Needs review): The memo says NPS approved the Part 2 application, but the NPS letter is a conditional approval with three conditions and says it does not mean the project will be certified.

Recall by severity:

| severity | reportable | found | recall |
|---|---|---|---|
| Critical | 7 | 7 | 100.0% |
| High | 13 | 12 | 92.3% |
| Low | 1 | 1 | 100.0% |
| Medium | 5 | 5 | 100.0% |

Recall by class:

| class | cases | reportable | found | recall | negative | false_alarms | class_accuracy |
|---|---|---|---|---|---|---|---|
| Consistent | 8 | 0 | 0 | - | 8 | 0 | - |
| Contextual difference | 5 | 0 | 0 | - | 5 | 0 | - |
| Contradiction | 21 | 21 | 20 | 95.2% | 0 | 0 | 100.0% |
| Insufficient evidence | 5 | 5 | 5 | 100.0% | 0 | 0 | 100.0% |

### DEEPSEEK-R1 (DeepSeek-V3.2, HTC01)

Weighted recall 79.6% (78 of 98 points), recall 70.0% (14 of 20 withheld cases), precision 90.5%, 1 false positives, 1 findings waiting for a manual decision.
Development set: weighted recall 95.2% (5 of 6 cases). Withheld set without the ambiguous cases: 78.7%.

Missed cases:

- HTC01-003 (High, Withheld): Cost certification leaves out the change orders
- HTC01-025 (High, Withheld): Hard cost line items do not add up to the subtotal
- HTC01-032 (High, Withheld): Memo claims the state credit certification has been issued
- HTC01-035 (High, Withheld): Financial model puts the whole federal credit in 2025
- HTC01-026 (Medium, Withheld): Deposit payment is backed only by an email
- HTC01-027 (Medium, Withheld): Adjusted basis in the substantial rehabilitation test has no readable source
- HTC01-018 (Low, Development): Owner name is misspelled on the architect's documents

Findings with no confirmed case:

- DEEPSEEK-R1-F14 (Needs review): GC agreement dated June 5, 2023 incorporates drawings dated July 20, 2023 and the Part 2 approval dated August 22, 2023.
- DEEPSEEK-R1-F21 (False positive candidate): Market study spells the county name as Pittsburgh in one place and Pittsylvania in another.

Wrong class:

- DEEPSEEK-R1-F20 on HTC01-002: expected Contradiction, reported Contextual difference

Recall by severity:

| severity | reportable | found | recall |
|---|---|---|---|
| Critical | 7 | 7 | 100.0% |
| High | 13 | 9 | 69.2% |
| Low | 1 | 0 | 0.0% |
| Medium | 5 | 3 | 60.0% |

Recall by class:

| class | cases | reportable | found | recall | negative | false_alarms | class_accuracy |
|---|---|---|---|---|---|---|---|
| Consistent | 8 | 0 | 0 | - | 8 | 0 | - |
| Contextual difference | 5 | 0 | 0 | - | 5 | 0 | - |
| Contradiction | 21 | 21 | 17 | 81.0% | 0 | 0 | 94.1% |
| Insufficient evidence | 5 | 5 | 2 | 40.0% | 0 | 0 | 100.0% |

### GEMINI_Flash2.5 (Gemini 2.5 Flash, HTC01)

Weighted recall 83.7% (82 of 98 points), recall 75.0% (15 of 20 withheld cases), precision 90.9%, 1 false positives, 1 findings waiting for a manual decision.
Development set: weighted recall 81.0% (5 of 6 cases). Withheld set without the ambiguous cases: 83.0%.

Missed cases:

- HTC01-008 (High, Development): Two different construction start dates, one before Part 2 approval
- HTC01-010 (High, Withheld): No evidence NPS approved the window shop drawings before installation
- HTC01-025 (High, Withheld): Hard cost line items do not add up to the subtotal
- HTC01-035 (High, Withheld): Financial model puts the whole federal credit in 2025
- HTC01-026 (Medium, Withheld): Deposit payment is backed only by an email
- HTC01-027 (Medium, Withheld): Adjusted basis in the substantial rehabilitation test has no readable source

Findings with no confirmed case:

- GEMINI_Flash2.5-F17 (False positive candidate): Project stabilization date in schedule conflicts with market study absorption timeline
- GEMINI_Flash2.5-F19 (Needs review): General contractor agreement execution date predates architect drawing issuance date cited therein

Wrong class:

- GEMINI_Flash2.5-F13 on HTC01-032: expected Insufficient evidence, reported Contradiction

Recall by severity:

| severity | reportable | found | recall |
|---|---|---|---|
| Critical | 7 | 7 | 100.0% |
| High | 13 | 9 | 69.2% |
| Low | 1 | 1 | 100.0% |
| Medium | 5 | 3 | 60.0% |

Recall by class:

| class | cases | reportable | found | recall | negative | false_alarms | class_accuracy |
|---|---|---|---|---|---|---|---|
| Consistent | 8 | 0 | 0 | - | 8 | 0 | - |
| Contextual difference | 5 | 0 | 0 | - | 5 | 0 | - |
| Contradiction | 21 | 21 | 18 | 85.7% | 0 | 0 | 100.0% |
| Insufficient evidence | 5 | 5 | 2 | 40.0% | 0 | 0 | 50.0% |

### Gemini 3.8 flash (Gemini 3.8 Flash, HTC01)

Weighted recall 93.9% (92 of 98 points), recall 90.0% (18 of 20 withheld cases), precision 95.8%, 0 false positives, 1 findings waiting for a manual decision.
Development set: weighted recall 81.0% (5 of 6 cases). Withheld set without the ambiguous cases: 93.6%.

Missed cases:

- HTC01-008 (High, Development): Two different construction start dates, one before Part 2 approval
- HTC01-025 (High, Withheld): Hard cost line items do not add up to the subtotal
- HTC01-026 (Medium, Withheld): Deposit payment is backed only by an email

Findings with no confirmed case:

- Gemini 3.8 flash-F15 (Needs review): The construction agreement execution date predates the architectural specifications and Part 2 approval it incorporates.

Recall by severity:

| severity | reportable | found | recall |
|---|---|---|---|
| Critical | 7 | 7 | 100.0% |
| High | 13 | 11 | 84.6% |
| Low | 1 | 1 | 100.0% |
| Medium | 5 | 4 | 80.0% |

Recall by class:

| class | cases | reportable | found | recall | negative | false_alarms | class_accuracy |
|---|---|---|---|---|---|---|---|
| Consistent | 8 | 0 | 0 | - | 8 | 0 | - |
| Contextual difference | 5 | 0 | 0 | - | 5 | 0 | - |
| Contradiction | 21 | 21 | 19 | 90.5% | 0 | 0 | 100.0% |
| Insufficient evidence | 5 | 5 | 4 | 80.0% | 0 | 0 | 100.0% |

### Gemini flash 3.8 (Gemini 3.8 Flash, HTC01)

Weighted recall 61.2% (60 of 98 points), recall 50.0% (10 of 20 withheld cases), precision 93.3%, 0 false positives, 1 findings waiting for a manual decision.
Development set: weighted recall 76.2% (4 of 6 cases). Withheld set without the ambiguous cases: 63.8%.

Missed cases:

- HTC01-017 (Critical, Withheld): Cost certification names the developer as taxpayer, not the building owner
- HTC01-006 (High, Withheld): Memo says the project is fully funded, but the budget shows a gap
- HTC01-008 (High, Development): Two different construction start dates, one before Part 2 approval
- HTC01-010 (High, Withheld): No evidence NPS approved the window shop drawings before installation
- HTC01-014 (High, Withheld): Equity installments do not add up to the equity amount
- HTC01-025 (High, Withheld): Hard cost line items do not add up to the subtotal
- HTC01-035 (High, Withheld): Financial model puts the whole federal credit in 2025
- HTC01-037 (High, Withheld): Equity bridge loan matures before the installment meant to repay it
- HTC01-026 (Medium, Withheld): Deposit payment is backed only by an email
- HTC01-027 (Medium, Withheld): Adjusted basis in the substantial rehabilitation test has no readable source
- HTC01-033 (Medium, Withheld): Update treats the Phase 1 temporary occupancy date as the placed-in-service date
- HTC01-018 (Low, Development): Owner name is misspelled on the architect's documents

Findings with no confirmed case:

- Gemini flash 3.8-F13 (Needs review): Contract execution date in GC Agreement precedes date of contract documents incorporated by reference.

Recall by severity:

| severity | reportable | found | recall |
|---|---|---|---|
| Critical | 7 | 6 | 85.7% |
| High | 13 | 6 | 46.2% |
| Low | 1 | 0 | 0.0% |
| Medium | 5 | 2 | 40.0% |

Recall by class:

| class | cases | reportable | found | recall | negative | false_alarms | class_accuracy |
|---|---|---|---|---|---|---|---|
| Consistent | 8 | 0 | 0 | - | 8 | 0 | - |
| Contextual difference | 5 | 0 | 0 | - | 5 | 0 | - |
| Contradiction | 21 | 21 | 12 | 57.1% | 0 | 0 | 100.0% |
| Insufficient evidence | 5 | 5 | 2 | 40.0% | 0 | 0 | 100.0% |

### Gemini-3.8 (Gemini 3.8 Flash, HTC01)

Weighted recall 69.4% (68 of 98 points), recall 70.0% (14 of 20 withheld cases), precision 90.5%, 0 false positives, 2 findings waiting for a manual decision.
Development set: weighted recall 81.0% (5 of 6 cases). Withheld set without the ambiguous cases: 68.1%.

Contract problems (4):

- Gemini-3.8-F02: citation without a document ID: "[text lost in copy] in thousands)'".
- Gemini-3.8-F03: citation without a document ID: "[text lost in copy] in thousands)'".
- Gemini-3.8-F09: classification None is not one of ['Contradiction', 'Contextual difference', 'Insufficient evidence', 'Consistent'].
- Gemini-3.8-F09: severity None is not one of ['Critical', 'High', 'Medium', 'Low'].

Missed cases:

- HTC01-007 (Critical, Withheld): Memo puts the federal credits in the wrong tax year
- HTC01-017 (Critical, Withheld): Cost certification names the developer as taxpayer, not the building owner
- HTC01-008 (High, Development): Two different construction start dates, one before Part 2 approval
- HTC01-010 (High, Withheld): No evidence NPS approved the window shop drawings before installation
- HTC01-025 (High, Withheld): Hard cost line items do not add up to the subtotal
- HTC01-035 (High, Withheld): Financial model puts the whole federal credit in 2025
- HTC01-026 (Medium, Withheld): Deposit payment is backed only by an email

Findings with no confirmed case:

- Gemini-3.8-F09 (Needs review): [ID, class, severity and summary lost in copy]
- Gemini-3.8-F15 (Needs review): The general construction agreement is dated June 5, 2023, but purports to incorporate architectural specifications dated July 20, 2023 and the Part 2 approval dated August 22, 2023.

Wrong class:

- Gemini-3.8-F24 on HTC01-018: expected Contradiction, reported Contextual difference

Recall by severity:

| severity | reportable | found | recall |
|---|---|---|---|
| Critical | 7 | 5 | 71.4% |
| High | 13 | 9 | 69.2% |
| Low | 1 | 1 | 100.0% |
| Medium | 5 | 4 | 80.0% |

Recall by class:

| class | cases | reportable | found | recall | negative | false_alarms | class_accuracy |
|---|---|---|---|---|---|---|---|
| Consistent | 8 | 0 | 0 | - | 8 | 0 | - |
| Contextual difference | 5 | 0 | 0 | - | 5 | 0 | - |
| Contradiction | 21 | 21 | 16 | 76.2% | 0 | 0 | 93.8% |
| Insufficient evidence | 5 | 5 | 3 | 60.0% | 0 | 0 | 100.0% |

### Grok4.7 (Grok Build, April 2026, HTC01)

Weighted recall 98.0% (96 of 98 points), recall 95.0% (19 of 20 withheld cases), precision 92.3%, 0 false positives, 2 findings waiting for a manual decision.
Development set: weighted recall 100.0% (6 of 6 cases). Withheld set without the ambiguous cases: 97.9%.

Missed cases:

- HTC01-026 (Medium, Withheld): Deposit payment is backed only by an email

Findings with no confirmed case:

- Grok4.7-F18 (Needs review): The investor memo treats the cost certification as established, but the only CPA report is a draft marked not for reliance.
- Grok4.7-F23 (Needs review): The completion and recapture guarantor is never named.

Wrong class:

- Grok4.7-F01 on HTC01-010: expected Insufficient evidence, reported Contradiction
- Grok4.7-F25 on HTC01-002: expected Contradiction, reported Contextual difference

Recall by severity:

| severity | reportable | found | recall |
|---|---|---|---|
| Critical | 7 | 7 | 100.0% |
| High | 13 | 13 | 100.0% |
| Low | 1 | 1 | 100.0% |
| Medium | 5 | 4 | 80.0% |

Recall by class:

| class | cases | reportable | found | recall | negative | false_alarms | class_accuracy |
|---|---|---|---|---|---|---|---|
| Consistent | 8 | 0 | 0 | - | 8 | 0 | - |
| Contextual difference | 5 | 0 | 0 | - | 5 | 0 | - |
| Contradiction | 21 | 21 | 21 | 100.0% | 0 | 0 | 95.2% |
| Insufficient evidence | 5 | 5 | 4 | 80.0% | 0 | 0 | 75.0% |

### Grok4.7-R2 (Grok 4.7, HTC01)

Weighted recall 93.9% (92 of 98 points), recall 90.0% (18 of 20 withheld cases), precision 92.3%, 0 false positives, 2 findings waiting for a manual decision.
Development set: weighted recall 100.0% (6 of 6 cases). Withheld set without the ambiguous cases: 93.6%.

Missed cases:

- HTC01-035 (High, Withheld): Financial model puts the whole federal credit in 2025
- HTC01-026 (Medium, Withheld): Deposit payment is backed only by an email

Findings with no confirmed case:

- Grok4.7-R2-F16 (Needs review): The construction schedule is updated July 20, 2025 but says September 2025 milestones, including Part 3 submission, are already actual.
- Grok4.7-R2-F24 (Needs review): The only cost certification in the data room is a draft marked not for reliance, while the investor memo presents it as the cost certification.

Wrong class:

- Grok4.7-R2-F20 on HTC01-028: expected Contradiction, reported Contextual difference

Recall by severity:

| severity | reportable | found | recall |
|---|---|---|---|
| Critical | 7 | 7 | 100.0% |
| High | 13 | 12 | 92.3% |
| Low | 1 | 1 | 100.0% |
| Medium | 5 | 4 | 80.0% |

Recall by class:

| class | cases | reportable | found | recall | negative | false_alarms | class_accuracy |
|---|---|---|---|---|---|---|---|
| Consistent | 8 | 0 | 0 | - | 8 | 0 | - |
| Contextual difference | 5 | 0 | 0 | - | 5 | 0 | - |
| Contradiction | 21 | 21 | 20 | 95.2% | 0 | 0 | 95.0% |
| Insufficient evidence | 5 | 5 | 4 | 80.0% | 0 | 0 | 100.0% |

### CHATGPT-HTC02-R1 (ChatGPT (GPT-5), HTC02)

Weighted recall 73.5% (72 of 98 points), recall 63.6% (14 of 22 withheld cases), precision 100.0%, 0 false positives, 0 findings waiting for a manual decision.
Development set: weighted recall 95.7% (6 of 7 cases). Withheld set without the ambiguous cases: 80.0%.

Contract problems (9):

- CHATGPT-HTC02-R1-F01: citation DOC-06 has no quoted text.
- CHATGPT-HTC02-R1-F01: citation DOC-16 has no quoted text.
- CHATGPT-HTC02-R1-F05: citation DOC-06 has no quoted text.
- CHATGPT-HTC02-R1-F06: citation DOC-06 has no quoted text.
- CHATGPT-HTC02-R1-F08: citation DOC-09 has no quoted text.
- CHATGPT-HTC02-R1-F09: citation DOC-05 has no quoted text.
- CHATGPT-HTC02-R1-F09: citation DOC-13 has no quoted text.
- CHATGPT-HTC02-R1-F09: citation DOC-10 has no quoted text.
- CHATGPT-HTC02-R1-F09: citation DOC-06 has no quoted text.

Missed cases:

- HTC02-010 (High, Withheld): Sponsor told the investor every comment was carried through all documents, but several were not
- HTC02-016 (High, Withheld): Model delivers the whole federal credit in 2025
- HTC02-039 (High, Withheld): The stale Exhibit B would trigger a $576,200 downward adjuster even though the price already reflects the corrected credits
- HTC02-040 (High, Withheld): Building B's delay triggers a two-cent price step-down that no document reflects
- HTC02-041 (High, Withheld): The Virginia buyer can walk away unless both buildings are finally certified by June 30, 2026, which the schedule makes unlikely
- HTC02-011 (Medium, Withheld): Closing checklist marks the Exhibit B update as done in handwriting, but the signed exhibit is unchanged
- HTC02-020 (Medium, Withheld): Management agreement is signed by the owner, although the master lease makes the master tenant the operator
- HTC02-025 (Medium, Withheld): No Section 50(d) election statement for Building A is in the data room
- HTC02-022 (Low, Development): Loan amendment signature block misnames the borrower

Wrong class:

- CHATGPT-HTC02-R1-F11 on HTC02-014: expected Insufficient evidence, reported Contradiction

Recall by severity:

| severity | reportable | found | recall |
|---|---|---|---|
| Critical | 5 | 5 | 100.0% |
| High | 17 | 12 | 70.6% |
| Low | 1 | 0 | 0.0% |
| Medium | 6 | 3 | 50.0% |

Recall by class:

| class | cases | reportable | found | recall | negative | false_alarms | class_accuracy |
|---|---|---|---|---|---|---|---|
| Consistent | 7 | 0 | 0 | - | 7 | 0 | - |
| Contextual difference | 6 | 0 | 0 | - | 6 | 0 | - |
| Contradiction | 26 | 26 | 18 | 69.2% | 0 | 0 | 100.0% |
| Insufficient evidence | 3 | 3 | 2 | 66.7% | 0 | 0 | 50.0% |

### HTC02-R1 (Gemini 3.8 Flash, HTC02)

Weighted recall 67.3% (66 of 98 points), recall 68.2% (15 of 22 withheld cases), precision 81.8%, 0 false positives, 4 findings waiting for a manual decision.
Development set: weighted recall 82.6% (6 of 7 cases). Withheld set without the ambiguous cases: 70.0%.

Contract problems (9):

- HTC02-R1-F06: citation DOC-06 has no quoted text.
- HTC02-R1-F09: citation DOC-06 has no quoted text.
- HTC02-R1-F10: citation DOC-06 has no quoted text.
- HTC02-R1-F12: citation DOC-08 has no quoted text.
- HTC02-R1-F17: citation DOC-02 has no quoted text.
- HTC02-R1-F18: citation DOC-14 has no quoted text.
- HTC02-R1-F22: citation DOC-06 has no quoted text.
- HTC02-R1-F22: citation DOC-06 has no quoted text.
- HTC02-R1-F22: citation DOC-06 has no quoted text.

Missed cases:

- HTC02-001 (Critical, Withheld): Pre-review QRE of $39.8M survives in the revised deck and the snapshot after it was corrected to $36.45M
- HTC02-002 (Critical, Withheld): Federal credit stated as $7.96M to the state buyer and in the revised deck, against $7.29M in the model
- HTC02-005 (High, Development): Building C is described as a certified historic building, but Part 1 says it is not
- HTC02-010 (High, Withheld): Sponsor told the investor every comment was carried through all documents, but several were not
- HTC02-039 (High, Withheld): The stale Exhibit B would trigger a $576,200 downward adjuster even though the price already reflects the corrected credits
- HTC02-041 (High, Withheld): The Virginia buyer can walk away unless both buildings are finally certified by June 30, 2026, which the schedule makes unlikely
- HTC02-023 (Medium, Withheld): Revised deck shows total development cost of $49.8M; the revised budget says $48.6M
- HTC02-025 (Medium, Withheld): No Section 50(d) election statement for Building A is in the data room

Findings with no confirmed case:

- HTC02-R1-F11 (Needs review): Financial Model v7 Sources & Uses tab fails to balance and misclassifies developer fee as a source.
- HTC02-R1-F20 (Needs review): Tax Counsel Memorandum cites future budget revision date.
- HTC02-R1-F22 (Needs review): Critical environmental, title, and guarantor financial diligence items omitted from the data room.
- HTC02-R1-F23 (Needs review): Absence of Virginia Department of Historic Resources state rehabilitation approval in data room.

Wrong class:

- HTC02-R1-F01 on HTC02-014: expected Insufficient evidence, reported Contradiction
- HTC02-R1-F19 on HTC02-024: expected Insufficient evidence, reported Contradiction

Recall by severity:

| severity | reportable | found | recall |
|---|---|---|---|
| Critical | 5 | 3 | 60.0% |
| High | 17 | 13 | 76.5% |
| Low | 1 | 1 | 100.0% |
| Medium | 6 | 4 | 66.7% |

Recall by class:

| class | cases | reportable | found | recall | negative | false_alarms | class_accuracy |
|---|---|---|---|---|---|---|---|
| Consistent | 7 | 0 | 0 | - | 7 | 0 | - |
| Contextual difference | 6 | 0 | 0 | - | 6 | 0 | - |
| Contradiction | 26 | 26 | 19 | 73.1% | 0 | 0 | 100.0% |
| Insufficient evidence | 3 | 3 | 2 | 66.7% | 0 | 0 | 0.0% |

## How far the automatic matching can be trusted

223 findings have a case chosen by hand. Run with no manual decisions, the rule-based matcher lands on the same case for 217 of them (97.3%).

| Outcome | Findings |
|---|---|
| Different case | 3 |
| Manual 'False positive candidate', rules 'Duplicate' | 1 |
| Manual 'False positive candidate', rules 'False positive candidate' | 1 |
| Manual 'Needs review', rules 'Duplicate' | 3 |
| Manual 'Needs review', rules 'False positive candidate' | 3 |
| Manual 'Needs review', rules 'Match' | 9 |
| Manual 'Needs review', rules 'Needs review' | 5 |
| Same case | 217 |
| Sent to review | 3 |

The thresholds were set on these same findings, so this is agreement on known data, not a forecast for a new data room. Scores above use the manual decision wherever one exists.

## Rules against the LLM judge

The judge has not been run yet. Run: python -m eval judge

## What is not measured here

- Quotes are checked against the documents only for data rooms whose text is stored in data_room/. A quote marked not found is either invented or reworded, and needs a look.
- Reasoning scores in the headline come from manual review. The judge's scores are shown beside them.
