# Kasparro Multi-Agent Visibility Research & Verification Engine (v3.0)

A deterministic research pipeline and human-governed state machine for analyzing brand visibility across generative AI engines (Google AI Mode, ChatGPT, Gemini). 

Designed for high-stakes business intelligence, this system pairs AI drafting with zero-trust Python verification to eliminate entity confusion, fabricated citations, unsupported statistics, and indirect prompt injections.

---

## 1. System Architecture

```text
              ┌────────────────────────────────────────────────────────┐
              │                   cases/cases.jsonl                    │
              │   (User Question, Allowed Source IDs, Decision Date)   │
              └───────────────────────────┬────────────────────────────┘
                                          │
                                          ▼
              ┌────────────────────────────────────────────────────────┐
              │                     EvidenceAgent                      │
              │       Reads closed set of numbered source files        │
              └───────────────────────────┬────────────────────────────┘
                                          │
                                          ▼
              ┌────────────────────────────────────────────────────────┐
              │                    InjectionScanner                    │
              │    Catches instruction overrides & redacts for model   │
              └─────────────┬────────────────────────────┬─────────────┘
                            │                            │
            Clean / Redacted View                        │ Full Raw Evidence
                            │                            │
                            ▼                            │
              ┌───────────────────────────┐              │
              │     Analysis Agent        │              │
              │ (Extracts claims, quotes, │              │
              │   locators, gaps, recs)   │              │
              └─────────────┬─────────────┘              │
                            │                            │
                            └─────────────┬──────────────┘
                                          │
                                          ▼
              ┌────────────────────────────────────────────────────────┐
              │                   VerificationAgent                    │
              │    Deterministic Python checks (NO MODEL / NO GUESS):  │
              │  * Exact quote match         * Number verification     │
              │  * Line locator in-bounds    * Date & entity check     │
              └───────────────────────────┬────────────────────────────┘
                                          │
                 Routes: AUTO_COMPLETE_DRAFT | ROUTE_TO_HUMAN | SAFE_STOP
                                          │
                                          ▼
              ┌────────────────────────────────────────────────────────┐
              │                  PersistentStateStore                  │
              │               (SQLite: kasparro_state.db)              │
              │   Immutable audit trail, hash integrity, role policies │
              └───────────────────────────┬────────────────────────────┘
                                          │
                     ┌────────────────────┴────────────────────┐
                     ▼                                         ▼
     ┌───────────────────────────────┐         ┌───────────────────────────────┐
     │       eval_benchmark.py       │         │         dashboard.py          │
     │  15 Cases, Negative Controls, │         │   Human Review Portal (Web UI)│
     │  Mutations, SLA, Release Gates│         │  Inspect lines, approve/reject│
     └───────────────────────────────┘         └───────────────────────────────┘

```

---

## 2. Core Modules & Deliverables

* **`engine_pipeline.py`**: The deterministic validator and persistence engine.
  * `InjectionScanner`: Normalizes Unicode (`NFKC`), strips zero-width obfuscations, and catches instruction overrides across line breaks before the model reads evidence.
  * `EvidenceAgent`: Enforces closed-world document access with bounded retry logic.
  * `VerificationAgent`: Runs pure Python checks for character-for-character verbatim quotes, line locator boundaries, word overlap ratios, entity ambiguities, and numeric traceability.
  * `PersistentStateStore`: SQLite backend managing review tasks, deadlines, role-based approval permissions, and cryptographic SHA-256 tamper invalidation.
* **`replay_fixtures.py`**: Orchestrator, live adapter, and regression fixtures.
  * `KasparroPipelineOrchestrator`: Coordinates retrieval, pre-scanning, analysis, and verification.
  * `LiveModelAdapter`: Configurable execution modes (`replay` vs `live` Ollama/OpenAI endpoints).
  * `REPLAY_STAGE_OUTPUTS`: Source-verified regression fixtures for 12 core cases and 3 adversarial tests.
* **`eval_benchmark.py`**: Automated evaluation runner executing 7 stages across 15 cases, 6 negative controls, 9 quote mutations, 12 injection attacks, repeat stability checks, and 8 release gates.
* **`dashboard.py`**: Streamlit-based analyst review portal featuring side-by-side evidence inspection, decision forms, and dynamic capacity tracking.
* **`demo.py`**: Fast, self-contained terminal walkthrough demonstrating edge-case defenses.
* **`manual_grades.csv`**: Ground-truth human calibration grades across source text lines.

---

## 3. Installation & Setup

### Prerequisites
* Python 3.10+
* SQLite3 (built into Python standard library)

### Install Dependencies
```bash
pip install streamlit

```

---

## 4. How to Run

### A. Run the Full Evaluation Benchmark & Release Gates

```bash
py -3 eval_benchmark.py

```

*Outputs:* `labels.csv`, `rubric.json`, `evaluation_results.csv`, `negative_controls.csv`, and `evaluation_traces.json`.

### B. Run the CLI Walkthrough Demo

```bash
py -3 demo.py

```

Runs a rapid walkthrough showing injection stops, out-of-bounds locator halts, role enforcement, and cryptographic tamper invalidation.

### C. Launch the Interactive Analyst Portal

```bash
py -3 -m streamlit run dashboard.py

```

Opens the web dashboard in your browser (`http://localhost:8501`), allowing you to view briefs, cross-reference source line numbers, and commit decisions.

---

## 5. Release Gate Verification Results

The evaluation benchmark enforces 8 release gates:

| Release Gate | Observed | Threshold | Status |
| --- | --- | --- | --- |
| `route_status_match_all_15` | **1.0** (100%) | $\ge 1.0$ | **PASS** |
| `unexpected_critical_flags` | **0** | $\le 0$ | **PASS** |
| `negative_controls_not_missed` | **1.0** (100%) | $\ge 1.0$ | **PASS** |
| `injection_variants_detected` | **1.0** (100%) | $\ge 0.75$ | **PASS** |
| `injection_false_positives` | **0** | $\le 0$ | **PASS** |
| `mutation_checks_passed` | **1.0** (100%) | $\ge 1.0$ | **PASS** |
| `manual_graded_outputs_min` | **5** | $\ge 5$ | **PASS** |
| `unresolved_disagreements` | **0** | $\le 0$ | **PASS** |

**Recommendation:** Mechanics gates pass: a **LIMITED PILOT** of the review workflow only (analyst-only, $\le 10$ briefs/day, every brief human-reviewed, no unvalidated current-decision/pricing briefs) is defensible.
