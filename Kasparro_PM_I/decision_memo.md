# Decision Memo: Kasparro Multi-Agent Visibility Research & Verification Engine v3.0

**To:** Executive Leadership and AI Governance Committee  
**From:** Product Operations and AI Evaluation Benchmark Team  
**Date:** October 30, 2026  
**Classification:** Internal — Product and Operational Evaluation  
**Decision requested:** Authorize Phase 1, a limited operational pilot of the analyst review workflow  
**System:** Kasparro Multi-Agent Visibility Research, Deterministic Validator, and State Engine v3.0

---

## 1. Decision at a glance

### Recommendation

**Approve a limited, analyst-only operational pilot. Do not approve autonomous production release.**

The v3.0 benchmark reports that the deterministic workflow and governance mechanics passed all eight defined release gates. That result supports a constrained pilot of the review process; it does not establish that live model outputs are reliable enough for unmonitored deployment.

### Approval conditions

Authorize the pilot only within the following boundaries:

- **Access:** Internal analyst team only.
- **Volume:** No more than **10 briefs per day**.
- **Human oversight:** Every brief must receive human sign-off before it is used or shared as an approved brief.
- **Decision authority:** Final approval or rejection must be performed by a `lead_reviewer` or `product_manager`. Analysts may triage and request revisions, but may not approve commercial or current-decision briefs.
- **Restricted content:** No automated publishing of pricing, current buying advice, or other current commercial recommendations. Current-decision and pricing briefs remain subject to lead review and current evidence checks.
- **Evidence labeling:** Findings must be clearly identified as point-in-time analysis and display the underlying capture date.

### What this decision does not authorize

This recommendation is **not** approval for direct-to-customer autonomous publishing, unrestricted analyst access, or reliance on archived data for current pricing or buying decisions. Full autonomous release remains on hold pending live-model evaluation and closure or explicit acceptance of the known production gaps described below.

---

## 2. Business problem and proposed control

The Kasparro Visibility Research Engine processes archived answers from generative AI engines—including Google AI Mode, ChatGPT, and Gemini—and produces structured intelligence briefs about brand discoverability, citation share, and AI recommendation readiness.

The evaluation dataset is based on engine captures dated **July 31, 2026**. The benchmark identifies recurring risks in using an unguided language model to summarize those captures:

1. **Entity confusion:** Information about similarly named third parties, such as Kaspr, can be attributed incorrectly to Kasparro.
2. **Misattributed pricing:** A competitor's fee, such as RevenuePulse's reported ₹49,999 diagnostic fee, can be presented as Kasparro pricing.
3. **Biased coverage calculations:** Engine refusals or failed comparisons can be dropped from a denominator, overstating apparent brand coverage.
4. **Temporal staleness:** July 31 captures may be unsuitable for an October 27 or later commercial decision without current checks.
5. **Indirect prompt injection:** Instructions embedded in retrieved source material can attempt to influence the model or suppress evidence references.

The system's governing principle is: **the model drafts; deterministic Python checks verify; authorized people make consequential decisions.**

The v3.0 design implements that principle through closed-world evidence retrieval, pre-model input scanning and redaction, line-level source locators, deterministic quote and number checks, controlled decision routing, and a SQLite state ledger with integrity checks.

### Decision flow

```text
Case definition and allowed source IDs
                 |
                 v
        Evidence retrieval
                 |
                 v
     Injection scan and redaction
                 |
                 v
          Analysis draft
                 |
                 v
    Deterministic verification
                 |
       +---------+----------+
       |         |          |
       v         v          v
   SAFE_STOP  ROUTE_TO_   AUTO_COMPLETE_
              HUMAN        DRAFT
       |         |          |
       +---------+----------+
                 |
                 v
       SQLite state and audit ledger
                 |
                 v
       Human review and decision
```

The three routes are workflow outcomes, not equivalent approval states. In particular, `AUTO_COMPLETE_DRAFT` must not be interpreted as permission to publish a brief autonomously during the proposed pilot.

---

## 3. Evidence from the benchmark

### 3.1 Evaluation scope

The reported benchmark covers:

| Evaluation element | Reported scope |
|---|---:|
| Product cases | 12 |
| Adversarial cases | 3 |
| Total cases | 15 |
| Negative controls | 6 |
| Quote and locator mutations | 9 |
| Prompt-injection variants | 12 |
| Repeat stability cases | 3 cases, run repeatedly |
| Human calibration | 5 ground-truth outputs in `manual_grades.csv` |

The benchmark is run by `eval_benchmark.py`. The source memo identifies the archived dataset run as `4a4b71d9-9b0d-4497-85f1-7db5c4e21472`.

### 3.2 Release gates

All eight release gates are reported as passing:

| Release gate | Observed | Threshold | Result |
|---|---:|---:|---|
| `route_status_match_all_15` | 1.000 (100%) | 1.000 or higher | PASS |
| `unexpected_critical_flags` | 0 | 0 or lower | PASS |
| `negative_controls_not_missed` | 1.000 (100%) | 1.000 or higher | PASS |
| `injection_variants_detected` | 1.000 (100%) | 0.750 or higher | PASS |
| `injection_false_positives` | 0 | 0 or lower | PASS |
| `mutation_checks_passed` | 1.000 (100%) | 1.000 or higher | PASS |
| `manual_graded_outputs_min` | 5 | 5 or higher | PASS |
| `unresolved_disagreements` | 0 | 0 or lower | PASS |

These results support the claim that the tested workflow mechanics behaved as expected on the benchmark cases and fixtures. They should not be read as proof of general model accuracy, complete prompt-injection resistance, or production readiness under live traffic.

### 3.3 What the benchmark demonstrates

- **Routing:** All 15 cases reportedly matched their expected status. The descriptive case `PM05` routed to `AUTO_COMPLETE_DRAFT`; the adversarial cases `PM12`, `ADV01`, `ADV02`, and `ADV03` routed to `SAFE_STOP`; the remaining 10 commercial cases routed to `ROUTE_TO_HUMAN`.
- **Negative controls:** The memo reports that five in-scope controls, `NC01`–`NC05`, were intercepted by warning flags and quarantined.
- **Mutation checks:** All nine quote and locator mutation checks reportedly passed.
- **Injection tests:** All 12 tested injection variants were detected, with no reported false positives in the benchmark.
- **Repeatability:** Three successive executions of `PM03`, `PM08`, and `PM10` produced identical SHA-256 fingerprints, supporting deterministic repeatability of the tested state and workflow mechanics.

### 3.4 Known benchmark limitations

The benchmark also documents important limits that must remain visible in the release decision:

- **Logical entailment gap (`NC06`):** The statement that adding Organization schema will raise Kasparro's AI inclusion can pass because it shares vocabulary with genuine source lines and contains no fabricated number. The lexical overlap and numeric checks do not establish that a claim logically follows from its evidence.
- **Injection-language coverage:** The scanner is designed primarily for English syntax. The memo records Spanish instructions (`V08`) and leetspeak-style obfuscation (`V09`) as evasion limits.
- **Defense in depth:** The memo states that retrieved evidence has no execution privileges, reducing the ability of such text to execute actions. This does not eliminate the need to improve scanner coverage.
- **Replay versus live operation:** Replay mode uses hand-authored, source-verified fixtures. It validates workflow mechanics without API cost or model randomness, but does not validate live-model variance, latency, or cost drift.

**Interpretation:** The gate results justify a controlled operational pilot of the review workflow, not a broad claim that every generated claim is factually or logically correct.

---

## 4. Technical controls and governance design

### 4.1 Closed-world evidence retrieval

The `EvidenceAgent` restricts each case to the source IDs explicitly allowlisted in `cases.jsonl`. The memo states that open-web browsing and arbitrary external lookups are blocked at the transport layer. Retrieved files are indexed with fixed, one-based line numbers before extraction so findings can point to bounded evidence ranges.

### 4.2 Pre-model injection scanning

The `InjectionScanner` runs before evidence is passed to the analysis model. Its documented controls include:

- Unicode NFKC normalization.
- Removal of zero-width characters, including `\u200b`, `\u200c`, and `\ufeff`.
- Pattern checks that can detect instruction fragments split across lines.
- `redact_evidence_for_model()`, which replaces flagged lines for model consumption while retaining raw evidence for audit inspection.
- A critical injection flag, `CRIT-INJECT`, that prevents normal completion and routes the case to `SAFE_STOP`.

### 4.3 Deterministic verification

The `VerificationAgent` uses Python checks rather than a second LLM judge for the following controls:

| Control | Check | Failure signal / behavior |
|---|---|---|
| Locator bounds | Confirms that cited line ranges exist and do not exceed the document length | `CRIT-LOCATOR-OUT-OF-BOUNDS` |
| Verbatim quote integrity | Requires quoted text to match a substring of the cited lines character-for-character | `CRIT-UNSUPPORTED-QUOTE` |
| Claim/source word overlap | Computes non-stopword lexical overlap; overlap below 15% triggers a warning | `FLAG-LOW-CLAIM-OVERLAP` |
| Numeric traceability | Checks material percentages and numbers of three or more digits against source text, metadata dates, or allowed source IDs | `FLAG-UNSUPPORTED-NUMBER` |

These checks validate specific properties of a draft. They do not prove semantic entailment or establish that a recommendation is commercially sound.

### 4.4 Persistent state and decision authority

The `PersistentStateStore` uses SQLite (`kasparro_state.db`) to manage review tasks and decisions.

- **Role permissions:** `internal_analyst` users may triage and spawn corrected versions. `lead_reviewer` and `product_manager` roles are required for final `APPROVE` or `REJECT` decisions.
- **Current-decision restriction:** General analysts cannot approve briefs with a `current_decision` scope.
- **Integrity seal:** Approval binds a SHA-256 hash over the question, scope, findings, recommendations, and evidence-file hashes.
- **Drift response:** A change to the stored record or underlying evidence invalidates the seal, revokes approval, increments the version, and quarantines the brief.
- **Deadline handling:** Tasks have a `deadline_at`. The documented sweep transitions overdue tasks to `EXPIRED`; timeout does not result in silent auto-approval.

One material deployment caveat remains: reviewer roles are currently passed as simulated role parameters. The authority model therefore needs real identity and access-management integration before enterprise production use.

---

## 5. Operational capacity and pilot sizing

The source memo models operational feasibility against a reference workload of **20 briefs per day** and a total analyst review-time budget of **30 minutes per day**. The recommended pilot is deliberately capped lower, at **10 briefs per day**.

### Reported workload figures

| Scenario | Estimated daily review time | Headroom against 30 minutes | Basis stated in source |
|---|---:|---:|---|
| Portal-measured walkthrough | 14.0 min | 16.0 min | Open-to-decision timestamps in `kasparro_state.db`; average review duration reported as under 60 seconds per brief |
| Conservative planning model | 20.3 min | 9.7 min | Assumes 70 seconds per quarantined brief and 30 seconds of triage per stopped brief |
| Stress model | 25.8 min | 4.2 min | Assumes 90 seconds per brief |

The source memo calculates a break-even point of **105.0 seconds per routed brief** before exceeding the 30-minute daily analyst budget.

### Review-rate figures

The memo reports two different review-rate calculations:

- `10 / 12 = 83.3%` for the 12 pack cases.
- `24 / 40 = 60.0%` for the full database store.

These figures use different populations and should not be compared as though they share a denominator. The pilot should track the actual number of briefs received, routed to review, stopped, and approved each day, alongside measured analyst time.

### Capacity interpretation

The reported scenarios suggest that the workflow may fit within the stated 30-minute review budget under the modeled conditions. They are not a substitute for measuring dwell time and queue behavior during the pilot. The 10-brief daily cap provides a more conservative starting point than the 20-brief reference workload.

---

## 6. Pilot policy: permitted and prohibited use

| Permitted during the pilot | Prohibited during the pilot |
|---|---|
| Internal research briefings for product and marketing analysts | Direct-to-customer autonomous publishing without human sign-off |
| Point-in-time competitive-positioning audits clearly labeled with capture dates | Presenting engine-reported or third-party pricing as verified Kasparro rate-card pricing |
| Descriptive, unbranded market-appearance tracking, including the `PM05` workflow | Current buying advice based only on historical captures, without live capability checks |
| Supervised corrections using `spawn_revised_version()` with a mandatory rationale | Bypassing lead approval for commercial or current-decision briefs |

### Required operating rules

1. Keep the pilot internal and within the 10-brief-per-day cap.
2. Require a human sign-off for every brief before it is treated as approved.
3. Require a `lead_reviewer` or `product_manager` to make final approval or rejection decisions.
4. Keep current pricing and current buying recommendations out of automated publication; require current evidence and authorized lead review for any such decision brief.
5. Preserve the source capture date and line-level evidence references in the brief.
6. Treat `SAFE_STOP` as a hard stop for the affected draft, not as a warning that an analyst can casually override.
7. Record reviewer rationale, decision, and relevant evidence version in the state ledger.

---

## 7. Risks, gaps, and conditions for broader release

The following gaps are explicitly identified in the source memo and should be addressed before expanding beyond the limited pilot.

| Gap | Current limitation | Required work identified in the memo |
|---|---|---|
| Identity and authentication | Reviewer roles are simulated through role parameters | Integrate organizational SAML/SSO and hardware-backed cryptographic signing keys |
| Claim entailment | Lexical overlap and numeric checks can miss unsupported causal claims such as `NC06` | Add a bounded secondary model verifier for entailment, with appropriate evaluation and controls |
| Multilingual and obfuscated injection | Scanner focuses on English patterns; Spanish and leetspeak variants are documented limits | Improve multilingual detection and leetspeak de-obfuscation |
| Live-model behavior | Replay fixtures do not establish live variance, latency, or cost | Validate live Ollama/OpenAI integrations under controlled conditions |
| Persistence scale and concurrency | Current implementation uses SQLite | Migrate to managed PostgreSQL with row-level locks as part of the stated hardening roadmap |

The secondary model verifier is a proposed mitigation for the entailment gap, not a control demonstrated by the current benchmark. It should itself be evaluated before being relied upon.

---

## 8. Phased implementation plan

### Phase 1 — Limited operational pilot (Weeks 1–4)

**Status:** Recommended for authorization

- **Users:** Internal analyst team only; maximum 10 briefs per day.
- **Deployment:** Streamlit Review Portal with the SQLite State Engine.
- **Governance:** Human sign-off for every brief; lead-level approval for commercial and current-decision matters; pricing and current buying advice remain locked out from automated publication.
- **Measurement:** Record real human dwell time per brief and reviewer disagreement rates.

### Phase 2 — Model and security hardening (Weeks 5–8)

**Status:** Planned; not authorized by the Phase 1 decision alone

- **Model integration:** Evaluate multi-model live integrations using Ollama and/or the OpenAI API.
- **Entailment:** Develop and evaluate a specialized secondary verifier to address the `NC06` gap.
- **Security:** Extend the `InjectionScanner` to improve multilingual and leetspeak detection.
- **Infrastructure:** Migrate SQLite storage to managed PostgreSQL with row-level locks.

Progression to Phase 2 or broader deployment should be subject to a separate review of live test results, security coverage, identity controls, operational capacity, and acceptance of residual risks.

---

## 9. Pilot monitoring and exit considerations

The source memo specifically identifies human dwell time and disagreement rates as Phase 1 measures. The pilot should also retain the existing benchmark and governance evidence needed to determine whether the operating restrictions are being followed.

At minimum, the pilot review should examine:

- Daily brief volume against the 10-brief cap.
- Human review completion and approval authority for every brief.
- Actual review time against the 30-minute daily budget.
- Reviewer disagreement rates and reasons for disagreement.
- Counts and outcomes for `SAFE_STOP`, `ROUTE_TO_HUMAN`, and `AUTO_COMPLETE_DRAFT` cases.
- Any attempted or actual use of stale evidence for current pricing or buying advice.
- Evidence-hash failures, approval revocations, and expired tasks.

The memo does not specify numerical exit thresholds for these pilot measures beyond the daily volume cap and the stated review-time budget. The committee should therefore set explicit thresholds before considering expansion; this memo does not assume those thresholds have already been met.

---

## 10. Proposed committee resolution

> **Resolved:** The Executive Leadership and AI Governance Committee authorizes **Phase 1 — Limited Operational Pilot** of the Kasparro Multi-Agent Visibility Research and Verification Engine v3.0 for internal analyst use only, subject to a maximum of 10 briefs per day, human sign-off for every brief, lead-level approval for commercial and current-decision briefs, and no autonomous publication of pricing or current buying advice.
>
> This authorization does **not** approve unrestricted or customer-facing autonomous deployment. Expansion beyond Phase 1 requires a separate committee review of live-model performance, identity and authentication controls, entailment verification, multilingual injection defenses, persistence infrastructure, and measured pilot outcomes.

**Decision status:** Pending committee ratification  
**Approver(s):** ____________________________________  
**Date:** ___________________________________________

---

## Appendix A — Principal implementation artifacts

| Artifact | Purpose stated in the source material |
|---|---|
| `cases/cases.jsonl` | Defines case questions, decision dates, time scopes, and allowed source IDs |
| `evidence/sources.jsonl` | Stores source text used for closed-world evidence retrieval |
| `engine_pipeline.py` | Implements evidence handling, injection scanning, deterministic verification, and persistence |
| `replay_fixtures.py` | Provides the orchestrator, live-model adapter, and replay fixtures |
| `eval_benchmark.py` | Runs benchmark cases, controls, mutations, stability checks, and release gates |
| `dashboard.py` | Provides the Streamlit analyst review portal |
| `kasparro_state.db` | SQLite state and review-decision store |
| `manual_grades.csv` | Contains the five ground-truth human calibration grades referenced by the benchmark |

## Appendix B — Evidence and interpretation note

This memo is based on the supplied system decision memo and its reported benchmark results. It preserves the reported test counts, metrics, case identifiers, flags, and roadmap. The supplied material contains internal citation placeholders (for example, `[cite: 14]`) but does not include a corresponding reference list; those placeholders have therefore not been presented as independently traceable citations here. Benchmark results are described as reported results, not as an independent audit.
