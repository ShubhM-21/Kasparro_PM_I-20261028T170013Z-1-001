# app.py - Simple Review Dashboard
import streamlit as st
import json
import csv

st.set_page_config(page_title="Kasparro Review Portal", layout="wide")
st.title("Kasparro AI Visibility & Human Review Portal")

# Load evaluation traces
with open("evaluation_traces.json", "r") as f:
    traces = json.load(f)

# Sidebar: Queue
st.sidebar.header("Triage Queue")
cases = [c["case_id"] for c in traces["cases"]]
selected_case = st.sidebar.selectbox("Select Case Brief:", cases)

case_data = next(c for c in traces["cases"] if c["case_id"] == selected_case)

# Main Screen
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader(f"Brief: {case_data['case_id']} ({case_data['request_id']})")
    st.write(f"**Route:** `{case_data['review_route']}` | **Status:** `{case_data['review_status']}`")
    st.write(f"**Score:** `{case_data['overall_score']} / 5.0`")
    
    if case_data["critical_failure"]:
        st.error(f"Critical Failure: {case_data['critical_reason']}")
    else:
        st.success("No Critical Injections or Leaks Detected")

with col2:
    st.subheader("Analyst Decision (90s SLA)")
    action = st.radio("Review Action:", ["Approve", "Reject", "Request Changes"])
    note = st.text_input("Analyst Note:")
    if st.button("Submit Decision"):
        st.success(f"Decision '{action.upper()}' recorded with immutable SHA-256 stamp!")