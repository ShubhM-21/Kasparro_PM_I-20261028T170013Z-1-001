"""
Kasparro Mandatory Failure & Recovery Demonstrations (v2.0)
Executes against real pack sources and tools/evidence_tool.py, computes
pass/fail from assertions, and saves full demonstration evidence to JSON.
"""

import os
import json
from replay_fixtures import KasparroPipelineOrchestrator

def run_failure_demonstrations():
    db_file = "demo_state.db"
    if os.path.exists(db_file):
        os.remove(db_file)

    orch = KasparroPipelineOrchestrator(pack_dir=".", db_path=db_file)
    orch.state_store.reset_store()
    demos = {}

    print("\n=======================================================")
    print("  RUNNING 5 MANDATORY FAILURE & RECOVERY DEMONSTRATIONS")
    print("=======================================================\n")

    # 1. Missing or Contradictory Evidence (Real PM10 + PM03)
    case_pm10 = {
        "case_id": "PM10",
        "request_id": "DEMO-1-PM10",
        "question": "A stakeholder proposes citing the website benchmark and cohort figures as proof of customer impact.",
        "allowed_source_ids": ["R-014-chatgpt", "S-WEBSITE-CLAIMS", "S-TRACK-RECORD"],
        "decision_as_of": "2026-10-27",
        "claim_time_scope": "current_decision"
    }
    rep1 = orch.run_case(case_pm10)
    demo1_passed = (
        rep1.review_route == "ROUTE_TO_HUMAN"
        and rep1.review_status == "NEEDS_REVIEW"
        and any("FLAG-UNVERIFIED-BENCHMARK" in w for w in rep1.software_checks["warning_flags"])
    )
    assert demo1_passed, "Demo 1 assertion failed"
    demos["1_missing_or_contradictory_evidence"] = {
        "input": case_pm10,
        "expected_behaviour": "Expose 18.4% mean-vs-median contradiction and missing cohort dataset; route to human review as NEEDS_REVIEW.",
        "observed_state": {
            "review_route": rep1.review_route,
            "review_status": rep1.review_status,
            "warning_flags": rep1.software_checks["warning_flags"],
            "uncertainties": rep1.uncertainties_and_gaps
        },
        "passed": demo1_passed
    }
    print(f"[DEMO 1] Contradictory/Missing Evidence (PM10): route={rep1.review_route}, status={rep1.review_status}, passed={demo1_passed}")

    # 2. Failed Tool / Model Call (Bounded Retry via tools/evidence_tool.py)
    # 2a: transient_timeout (fails attempts 1 & 2, succeeds on attempt 3)
    ok_trans, data_trans, logs_trans = orch.evidence_agent.fetch_via_evidence_tool("PM01", "R-007-gemini", scenario="transient_timeout")
    # 2b: permanent_timeout (fails all 3 attempts -> safe stop)
    case_perm = {
        "case_id": "PM01",
        "request_id": "DEMO-2-PERM-TIMEOUT",
        "question": "Explain the four-module audit.",
        "allowed_source_ids": ["R-007-gemini"],
        "decision_as_of": "2026-10-27",
        "claim_time_scope": "historical_answers_with_current_reference"
    }
    rep2_perm = orch.run_case(case_perm, scenario="permanent_timeout")
    demo2_passed = (
        ok_trans is True and len(logs_trans) == 3
        and rep2_perm.review_route == "SAFE_STOP"
        and rep2_perm.review_status == "STOPPED"
        and len(rep2_perm.material_findings) == 0
    )
    assert demo2_passed, "Demo 2 assertion failed"
    demos["2_failed_tool_bounded_retry_and_safe_stop"] = {
        "input": {"case": "PM01", "source": "R-007-gemini", "scenarios_tested": ["transient_timeout", "permanent_timeout"]},
        "expected_behaviour": "Transient timeout recovers on attempt 3; permanent timeout stops at retry bound (3) and halts report in SAFE_STOP/STOPPED.",
        "observed_state": {
            "transient_attempts": logs_trans,
            "permanent_timeout_route": rep2_perm.review_route,
            "permanent_timeout_status": rep2_perm.review_status,
            "permanent_timeout_critical_flags": rep2_perm.software_checks["critical_flags"]
        },
        "passed": demo2_passed
    }
    print(f"[DEMO 2] Bounded Retry & Safe Stop: transient_recovered={ok_trans} (3 attempts), permanent_status={rep2_perm.review_status}, passed={demo2_passed}")

    # 3. Duplicate Request Idempotency & Conflict Detection
    case_dup = {
        "case_id": "PM04",
        "request_id": "DEMO-3-DUP",
        "question": "Review the three saved answers comparing Kasparro with Otterly AI.",
        "allowed_source_ids": ["R-008-aimode", "R-008-chatgpt", "R-008-gemini", "S-BRAND-SCHEMA"],
        "decision_as_of": "2026-10-27",
        "claim_time_scope": "historical_snapshot"
    }
    rep3_first = orch.run_case(case_dup)
    rep3_second = orch.run_case(case_dup)
    tasks_for_dup = orch.state_store.get_review_tasks("DEMO-3-DUP")
    conflict_caught = False
    try:
        mutated_case = dict(case_dup)
        mutated_case["question"] = "Different question using same request_id"
        orch.run_case(mutated_case)
    except ValueError as e:
        conflict_caught = ("CONFLICT_ERROR" in str(e))

    demo3_passed = (
        rep3_first.content_hash == rep3_second.content_hash
        and len(tasks_for_dup) == 1
        and conflict_caught
    )
    assert demo3_passed, "Demo 3 assertion failed"
    demos["3_duplicate_request_and_conflict_guard"] = {
        "input": {"request_id": "DEMO-3-DUP", "identical_retries": 2, "conflicting_payload_test": True},
        "expected_behaviour": "Identical retry returns existing version and keeps exactly 1 review task in SQLite; mutated payload with same request_id raises CONFLICT_ERROR.",
        "observed_state": {
            "review_tasks_count": len(tasks_for_dup),
            "review_tasks": tasks_for_dup,
            "conflict_on_mutated_payload_caught": conflict_caught
        },
        "passed": demo3_passed
    }
    print(f"[DEMO 3] Duplicate Request & Conflict Check: review_tasks={len(tasks_for_dup)}, conflict_caught={conflict_caught}, passed={demo3_passed}")

    # 4. Human Rejection, Unauthorized Role Check, and Review Timeout
    case_rev = {
        "case_id": "PM03",
        "request_id": "DEMO-4-REJECT",
        "question": "Explain how a Kasparro customer can cancel.",
        "allowed_source_ids": ["R-022-chatgpt", "R-022-gemini", "S-BRAND-SCHEMA"],
        "decision_as_of": "2026-10-27",
        "claim_time_scope": "historical_snapshot"
    }
    rep4_rej = orch.run_case(case_rev)
    ok_unauth, msg_unauth, rep4_rej = orch.state_store.submit_human_decision(rep4_rej, "marketing_intern", "APPROVE", "Looks fine")
    ok_rej, msg_rej, rep4_rej = orch.state_store.submit_human_decision(rep4_rej, "internal_analyst", "REJECT", "R-022 is about Kaspr, not Kasparro.")
    ok_reapprove, msg_reapprove, rep4_rej = orch.state_store.submit_human_decision(rep4_rej, "lead_reviewer", "APPROVE", "Try approving rejected version")

    case_to = {
        "case_id": "PM06",
        "request_id": "DEMO-4-TIMEOUT",
        "question": "Today is 27 October 2026. Is Kasparro better than Profound for Claude?",
        "allowed_source_ids": ["R-003-aimode", "R-003-chatgpt", "R-003-gemini", "S-BRAND-SCHEMA"],
        "decision_as_of": "2026-10-27",
        "claim_time_scope": "current_decision"
    }
    rep4_to = orch.run_case(case_to)
    ok_to, msg_to, rep4_to = orch.state_store.handle_timeout(rep4_to, elapsed_seconds=2.5, timeout_seconds=1.0)

    demo4_passed = (
        not ok_unauth
        and ok_rej and rep4_rej.review_status == "REJECTED"
        and not ok_reapprove and rep4_rej.review_status == "REJECTED"
        and ok_to and rep4_to.review_status == "EXPIRED"
    )
    assert demo4_passed, "Demo 4 assertion failed"
    demos["4_human_rejection_role_authority_and_timeout"] = {
        "input": {"rejection_request": "DEMO-4-REJECT", "timeout_request": "DEMO-4-TIMEOUT"},
        "expected_behaviour": "Unauthorized role denied; rejected version stays terminal REJECTED; timed-out version transitions to terminal EXPIRED without silent approval.",
        "observed_state": {
            "unauthorized_attempt_denied": not ok_unauth,
            "rejected_status": rep4_rej.review_status,
            "reapprove_after_reject_denied": not ok_reapprove,
            "timeout_status": rep4_to.review_status,
            "timeout_message": msg_to
        },
        "passed": demo4_passed
    }
    print(f"[DEMO 4] Rejection & Timeout: rejected={rep4_rej.review_status}, reapprove_blocked={not ok_reapprove}, timeout={rep4_to.review_status}, passed={demo4_passed}")

    # 5. Inputs / Content Change After Approval -> Old Approval Invalidated, Version Incremented
    case_chg = {
        "case_id": "PM01",
        "request_id": "DEMO-5-CHANGE",
        "question": "Explain the four-module audit to a marketing lead.",
        "allowed_source_ids": ["R-007-aimode", "R-007-chatgpt", "R-007-gemini", "S-BRAND-SCHEMA", "S-BRAND-CONTEXT"],
        "decision_as_of": "2026-10-27",
        "claim_time_scope": "historical_answers_with_current_reference"
    }
    rep5 = orch.run_case(case_chg)
    ok_app5, _, rep5 = orch.state_store.submit_human_decision(rep5, "internal_analyst", "APPROVE", "Verified against R-007 and S-BRAND-CONTEXT.")
    old_hash = rep5.content_hash
    # Mutate uncertainties after approval
    rep5.uncertainties_and_gaps.append("Added post-approval uncertainty note.")
    is_valid5, msg5, rep5 = orch.state_store.verify_integrity_or_invalidate(rep5)

    demo5_passed = (
        ok_app5
        and not is_valid5
        and rep5.version == 2
        and rep5.review_status == "NEEDS_REVIEW"
        and rep5.content_hash != old_hash
    )
    assert demo5_passed, "Demo 5 assertion failed"
    demos["5_change_after_approval_invalidation"] = {
        "input": {"request_id": "DEMO-5-CHANGE", "mutation": "Modified uncertainties_and_gaps after v1 approval"},
        "expected_behaviour": "Full-payload SHA-256 mismatch revokes v1 approval and spawns v2 in NEEDS_REVIEW.",
        "observed_state": {
            "v1_certified_hash": old_hash,
            "v2_new_hash": rep5.content_hash,
            "new_version": rep5.version,
            "new_status": rep5.review_status,
            "invalidation_message": msg5
        },
        "passed": demo5_passed
    }
    print(f"[DEMO 5] Change After Approval: v1_revoked={not is_valid5}, spawned_version=v{rep5.version}, status={rep5.review_status}, passed={demo5_passed}")

    with open("failure_demonstrations_output.json", "w", encoding="utf-8") as f:
        json.dump(demos, f, indent=2)
    print("\n[+] Saved verified demonstration evidence to failure_demonstrations_output.json")

if __name__ == "__main__":
    run_failure_demonstrations()