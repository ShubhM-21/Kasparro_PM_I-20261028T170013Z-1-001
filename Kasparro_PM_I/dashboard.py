"""
Kasparro AI Visibility & Analyst Review Dashboard (v3.0)
Connects directly to SQLite state store (kasparro_state.db), displays
side-by-side cited evidence lines, and records human review decisions.
Run with: py -3 -m streamlit run dashboard.py
"""

import os
import json
import time
import sqlite3
import streamlit as st

from engine_pipeline import PersistentStateStore, BriefReport

st.set_page_config(page_title="Kasparro Review Portal", layout="wide", initial_sidebar_state="expanded")

# Initialize SQLite Store
DB_PATH = "kasparro_state.db"
if not os.path.exists(DB_PATH):
    st.error(f"Database '{DB_PATH}' not found. Please run eval_benchmark.py first to populate reports.")
    st.stop()

store = PersistentStateStore(db_path=DB_PATH)

# Header & Disclaimer
st.title("🛡️ Kasparro AI Visibility & Human Review Portal")
st.caption("Pack v1.0 | Real July 31, 2026 Archive Run | Deterministic Multi-Agent Verification & SQLite State Engine")
st.info("ℹ️ **Reviewer Authority Disclosure:** Identity check in this environment is a simulated role parameter (`internal_analyst`, `lead_reviewer`, `product_manager`). Full cryptographic signature and enterprise SSO enforcement remain production handoff items.")

# Helper to read evidence from disk or sources.jsonl fallback
def load_source_content(source_id: str) -> str:
    text_file_path = os.path.join("evidence", "text", f"{source_id}.txt")
    if os.path.exists(text_file_path):
        with open(text_file_path, "r", encoding="utf-8") as tf:
            return tf.read()
    for p in (os.path.join("evidence", "sources.jsonl"), "sources.jsonl"):
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        obj = json.loads(line)
                        if obj.get("source_id") == source_id:
                            body = obj.get("body", "")
                            raw_lines = body.splitlines()
                            if raw_lines and not raw_lines[0].startswith("L1:"):
                                return "\n".join(f"L{i}: {txt}" for i, txt in enumerate(raw_lines, start=1))
                            return body
    return f"Source text file not found at {text_file_path} or in sources.jsonl."

# 1. Fetch Latest Reports from SQLite
def load_all_reports() -> list:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT report_json FROM reports ORDER BY request_id ASC, version DESC").fetchall()
        reports = []
        seen = set()
        fields = BriefReport.__dataclass_fields__
        for r in rows:
            rep_dict = json.loads(r[0])
            req_id = rep_dict["request_id"]
            if req_id not in seen:
                clean_dict = {k: v for k, v in rep_dict.items() if k in fields}
                reports.append(BriefReport(**clean_dict))
                seen.add(req_id)
        return reports

reports = load_all_reports()
if not reports:
    st.warning("No reports found in kasparro_state.db. Run eval_benchmark.py first.")
    st.stop()

# 2. Executive Capacity & Metrics Bar
col_m1, col_m2, col_m3, col_m4 = st.columns(4)
total_count = len(reports)
needs_review_count = sum(1 for r in reports if r.review_route == "ROUTE_TO_HUMAN")
auto_draft_count = sum(1 for r in reports if r.review_route == "AUTO_COMPLETE_DRAFT")
stopped_count = sum(1 for r in reports if r.review_route == "SAFE_STOP")

with col_m1:
    st.metric("Total Briefs in Store", total_count)
with col_m2:
    st.metric("Auto-Completed (Low Risk)", auto_draft_count)
with col_m3:
    st.metric("Quarantined for Analyst", needs_review_count)
with col_m4:
    stats = store.review_time_stats()
    routed_rate = needs_review_count / total_count if total_count else 0.83
    if stats.get("n", 0) > 0 and stats.get("median_s") is not None:
        med_s = float(stats["median_s"])
        est_analyst_mins = round(20 * routed_rate * (med_s / 60), 1)
        st.metric("Daily Load (Measured)", f"{est_analyst_mins} / 30 mins", delta=f"{round(30 - est_analyst_mins, 1)}m headroom (med {med_s:.1f}s)")
    else:
        est_analyst_mins = round(20 * routed_rate * (70 / 60), 1)
        st.metric("Daily Load (Assumed)", f"{est_analyst_mins} / 30 mins", delta=f"{round(30 - est_analyst_mins, 1)}m headroom (assumed 70s)")

st.divider()

# 3. Sidebar Queue & Filters
st.sidebar.header("📋 Analyst Queue")
filter_status = st.sidebar.selectbox("Filter by Route:", ["All", "ROUTE_TO_HUMAN (Quarantined)", "AUTO_COMPLETE_DRAFT", "SAFE_STOP"])

filtered = reports
if filter_status == "ROUTE_TO_HUMAN (Quarantined)":
    filtered = [r for r in reports if r.review_route == "ROUTE_TO_HUMAN"]
elif filter_status == "AUTO_COMPLETE_DRAFT":
    filtered = [r for r in reports if r.review_route == "AUTO_COMPLETE_DRAFT"]
elif filter_status == "SAFE_STOP":
    filtered = [r for r in reports if r.review_route == "SAFE_STOP"]

case_dict = {f"{r.case_id} — {r.request_id} (v{r.version}) [{r.review_status}]": r for r in filtered}
if not case_dict:
    st.sidebar.info("No briefs match selected filter.")
    st.stop()

selected_label = st.sidebar.selectbox("Select Brief to Inspect:", list(case_dict.keys()))
rep: BriefReport = case_dict[selected_label]

# Mark review task opened in SQLite to record real review duration
store.mark_review_opened(rep.request_id, rep.version)

st.sidebar.markdown("---")
st.sidebar.subheader("⏱️ SLA & Deadlines")
if st.sidebar.button("Sweep Overdue Deadlines"):
    expired = store.expire_overdue()
    if expired:
        st.sidebar.warning(f"Expired {len(expired)} overdue task(s).")
        st.rerun()
    else:
        st.sidebar.success("No overdue tasks found.")

# 4. Main Inspection Panel
col_left, col_right = st.columns([1.6, 1.4])

with col_left:
    st.subheader(f"Case Brief: {rep.case_id} ({rep.request_id})")
    st.markdown(f"**User Question:** *\"{rep.user_question}\"*")
    
    # Metadata badges
    b1, b2, b3, b4 = st.columns(4)
    b1.markdown(f"**Version:** `v{rep.version}`")
    b2.markdown(f"**Decision As Of:** `{rep.decision_date}`")
    b3.markdown(f"**Evidence Date:** `{rep.evidence_date}`")
    b4.markdown(f"**Execution Mode:** `{rep.execution_mode}`")

    # Software Checks Banner
    st.markdown("#### ⚙️ Deterministic Software Checks")
    sw = rep.software_checks
    c_sw1, c_sw2, c_sw3 = st.columns(3)
    c_sw1.write(f"Closed-World: {'✅ PASS' if sw.get('closed_world_passed') else '❌ FAIL'}")
    c_sw2.write(f"Locators: {'✅ PASS' if sw.get('locator_bounds_passed') else '❌ FAIL'}")
    c_sw3.write(f"Quotes: {'✅ PASS' if sw.get('verbatim_quotes_passed') else '❌ FAIL'}")

    c_sw4, c_sw5, c_sw6 = st.columns(3)
    c_sw4.write(f"Injection: {'✅ PASS' if sw.get('injection_scan_passed') else '❌ FAIL'}")
    c_sw5.write(f"Claim Support: {'✅ PASS' if sw.get('claim_support_passed', True) else '⚠️ WARNING'}")
    c_sw6.write(f"Model Stage: {'✅ PASS' if sw.get('model_stage_passed', True) else '❌ FAIL'}")

    if sw.get("critical_flags"):
        for cf in sw["critical_flags"]:
            st.error(f"🚨 {cf}")

    if sw.get("warning_flags"):
        for wf in sw["warning_flags"]:
            st.warning(f"⚠️ {wf}")

    # Routing Reasons & Attention Items
    st.markdown("#### ⚠️ Routing Reasons & Attention Flags")
    if rep.routing_reasons:
        for r_reason in rep.routing_reasons:
            st.info(f"• {r_reason}")
    else:
        st.success("No anomalies detected. Routine descriptive brief.")

    if rep.human_attention_items:
        st.markdown("#### 🚨 Attention Items for Analyst")
        for item in rep.human_attention_items:
            st.warning(f"• {item}")

    # Material Findings
    st.markdown("#### 📌 Material Findings")
    for idx, f in enumerate(rep.material_findings, start=1):
        with st.expander(f"Finding #{idx}: {f['claim'][:80]}...", expanded=True):
            st.write(f"**Statement:** {f['claim']}")
            st.write(f"**Source Locator:** `{f['source_id']}:{f['line_range']}` (Dated: {f.get('evidence_date')}, Type: `{f.get('support_type', 'direct')}`)")
            st.markdown(f"> *\"{f['quote']}\"*")

    # Uncertainties & Gaps
    st.markdown("#### ❓ Uncertainties & Gaps")
    for u in rep.uncertainties_and_gaps:
        st.write(f"• {u}")

    # Prioritized Recommendations
    if rep.prioritized_recommendations:
        st.markdown("#### 🎯 Prioritized Recommendations")
        for rec in rep.prioritized_recommendations:
            st.markdown(f"**P{rec['priority']}: {rec['title']}**")
            st.write(f"• **Rationale:** {rec['rationale']}")
            st.write(f"• **Customer Value:** {rec['customer_value']}")
            st.write(f"• **Limits & Risks:** {rec['limits_and_risks']}")
            st.write(f"• **Next Validation Step:** `{rec['next_validation_step']}`")

with col_right:
    st.subheader("🔍 Side-by-Side Evidence Inspector")
    st.caption("Opens actual numbered lines from evidence files for direct analyst verification.")

    cited_sources = list({f["source_id"] for f in rep.material_findings})
    if cited_sources:
        selected_source = st.selectbox("Select Source to Inspect:", cited_sources)
        raw_source_content = load_source_content(selected_source)
        st.text_area(f"Raw Source Text: {selected_source}", value=raw_source_content, height=280)

    st.markdown("---")
    st.subheader("✍️ Human Decision Desk (90s SLA)")
    st.markdown(f"**Current Status:** `{rep.review_status}` | **Current Route:** `{rep.review_route}`")
    st.markdown(f"**Content SHA-256 Hash:**")
    st.code(rep.content_hash, language="text")

    # Form to Submit Decision directly into SQLite
    with st.form("decision_form"):
        reviewer_role = st.selectbox("Reviewer Role (Authority Check):", ["lead_reviewer", "product_manager", "internal_analyst", "unauthorized_role"])
        decision_action = st.radio("Decision Action:", ["APPROVE", "REJECT"])
        decision_note = st.text_area("Reviewer Rationale Note (Mandatory):", placeholder="e.g., Verified against R-022. Entity collision confirmed with Kaspr.")
        submitted = st.form_submit_button("Commit Decision to SQLite", type="primary")

        if submitted:
            ok, msg, updated_rep = store.submit_human_decision(rep, reviewer_role, decision_action, decision_note)
            if ok:
                st.success(f"✅ Decision committed: {msg}")
                st.rerun()
            else:
                st.error(f"❌ Decision rejected by state machine: {msg}")

    # Decision History
    st.markdown("#### 📜 Immutable Decision Audit Trail")
    for d in reversed(rep.decision_history):
        st.write(f"• **{d.get('timestamp')}** [{d.get('actor')}]: `{d.get('action')}` — {d.get('note', '')}")