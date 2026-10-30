"""
Kasparro Human Audit Sheet & Claim Support Evaluator (v3.0)

Generates a side-by-side audit workbook (audit_sheet.csv) comparing every material finding
against its exact source text lines on disk. Verifies locators, verbatim quotes, word overlap,
and numeric traceability, providing analysts with a structured template for manual grading.

Usage:
    py -3 audit_sheet.py
    py -3 audit_sheet.py --export-csv audit_sheet.csv
    py -3 audit_sheet.py --case PM01
"""

import os
import re
import csv
import json
import argparse
from typing import Dict, Any, List, Optional

from engine_pipeline import (
    EvidenceAgent,
    VerificationAgent,
    content_words,
    material_numbers,
    all_numbers,
    normalize_text,
    CLAIM_OVERLAP_MIN,
    PACK_TUNED_ENTITY_COLLISIONS
)
from replay_fixtures import REPLAY_STAGE_OUTPUTS

AUDIT_FIELDS = [
    "case_id",
    "finding_num",
    "source_id",
    "line_range",
    "support_type",
    "evidence_date",
    "claim",
    "quote",
    "actual_source_lines",
    "verbatim_quote_match",
    "locator_in_bounds",
    "word_overlap_ratio",
    "unsupported_numbers",
    "triage_flags",
    "manual_fc_1_to_5",
    "manual_claim_supported",
    "analyst_notes"
]


def load_cases(pack_dir: str = ".") -> List[Dict[str, Any]]:
    for p in (os.path.join(pack_dir, "cases", "cases.jsonl"), os.path.join(pack_dir, "cases.jsonl")):
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return [json.loads(line) for line in f if line.strip()]
    return []


def generate_audit_rows(pack_dir: str = ".", target_case: Optional[str] = None) -> List[Dict[str, Any]]:
    ev_agent = EvidenceAgent(pack_dir=pack_dir)
    cases = load_cases(pack_dir)
    case_map = {c["case_id"]: c for c in cases}
    
    rows = []
    case_ids = [target_case] if target_case else sorted(REPLAY_STAGE_OUTPUTS.keys())
    
    for cid in case_ids:
        if cid not in REPLAY_STAGE_OUTPUTS:
            continue
        case_meta = case_map.get(cid, {})
        allowed_sources = case_meta.get("allowed_source_ids", [])
        
        # Retrieve source map for this case
        ev_map, _, _ = ev_agent.retrieve_closed_set(cid, allowed_sources)
        stage_data = REPLAY_STAGE_OUTPUTS[cid]
        findings = stage_data.get("findings", [])
        
        for idx, f in enumerate(findings, start=1):
            sid = f.get("source_id", "")
            l_range = f.get("line_range", "")
            quote = f.get("quote", "")
            claim = f.get("claim", "")
            stype = f.get("support_type", "direct")
            edate = f.get("evidence_date", "")
            
            ev_item = ev_map.get(sid)
            source_lines_str = "SOURCE_NOT_RETRIEVED"
            locator_ok = False
            quote_ok = False
            overlap = 1.0
            unsupported_nums = []
            flags = []
            
            if ev_item:
                m = re.match(r"^L(\d+)(?:-L?(\d+))?$", l_range.strip())
                if m:
                    start_ln = int(m.group(1))
                    end_ln = int(m.group(2)) if m.group(2) else start_ln
                    if 1 <= start_ln <= end_ln <= ev_item.line_count:
                        locator_ok = True
                        actual_lines = [f"L{ln}: {ev_item.lines.get(ln, '')}" for ln in range(start_ln, end_ln + 1)]
                        source_lines_str = "\n".join(actual_lines)
                        
                        # Verbatim quote test
                        cited_seg = "\n".join(ev_item.lines.get(ln, "") for ln in range(start_ln, end_ln + 1))
                        norm_seg = normalize_text(cited_seg)
                        norm_q = normalize_text(quote)
                        quote_variants = {norm_q, norm_q.strip("| ").strip()}
                        quote_ok = bool(norm_q and any(qv and qv in norm_seg for qv in quote_variants))
                        
                        # Word overlap & numbers (for direct claims)
                        if stype == "direct":
                            cw = content_words(claim)
                            date_pfx = str(ev_item.as_of)[:10] if ev_item.as_of else ""
                            sw_ = content_words(f"{cited_seg} {quote} {date_pfx}")
                            overlap = round(len(cw & sw_) / len(cw), 2) if cw else 1.0
                            if overlap < CLAIM_OVERLAP_MIN:
                                flags.append("FLAG-LOW-CLAIM-OVERLAP")
                            
                            src_nums = all_numbers(f"{' '.join(allowed_sources)} {ev_item.source_id} {date_pfx} {ev_item.raw_text}")
                            unsupported_nums = sorted(x for x in material_numbers(claim) if x not in src_nums)
                            if unsupported_nums:
                                flags.append("FLAG-UNSUPPORTED-NUMBER")
                        elif stype == "absence":
                            flags.append("FLAG-ABSENCE-CLAIM")
                    else:
                        flags.append("CRIT-LOCATOR-OUT-OF-BOUNDS")
                else:
                    flags.append("CRIT-BAD-LOCATOR")
                
                if not quote_ok and locator_ok:
                    flags.append("CRIT-UNSUPPORTED-QUOTE")
            else:
                flags.append("CRIT-MISSING-SOURCE")
            
            # Entity and temporal triage
            claim_lower = (claim + " " + quote).lower()
            if any(k in claim_lower for k in PACK_TUNED_ENTITY_COLLISIONS):
                flags.append("FLAG-ENTITY-AMBIGUITY")
            if case_meta.get("claim_time_scope") == "current_decision":
                flags.append("FLAG-TEMPORAL-GAP")
            
            rows.append({
                "case_id": cid,
                "finding_num": idx,
                "source_id": sid,
                "line_range": l_range,
                "support_type": stype,
                "evidence_date": edate,
                "claim": claim,
                "quote": quote,
                "actual_source_lines": source_lines_str,
                "verbatim_quote_match": "PASS" if quote_ok else "FAIL",
                "locator_in_bounds": "PASS" if locator_ok else "FAIL",
                "word_overlap_ratio": f"{overlap:.0%}",
                "unsupported_numbers": "; ".join(unsupported_nums) or "none",
                "triage_flags": "; ".join(sorted(set(flags))) or "none",
                "manual_fc_1_to_5": "",
                "manual_claim_supported": "",
                "analyst_notes": ""
            })
            
    return rows


def print_summary_table(rows: List[Dict[str, Any]]):
    print("\n" + "=" * 90)
    print(f"{'Case':<6} {'#':<3} {'Source':<16} {'Loc':<9} {'Type':<8} {'Quote':<6} {'Overlap':<8} {'Flags':<25}")
    print("=" * 90)
    for r in rows:
        flags_short = r["triage_flags"][:24] + ".." if len(r["triage_flags"]) > 25 else r["triage_flags"]
        print(f"{r['case_id']:<6} {r['finding_num']:<3} {r['source_id']:<16} {r['line_range']:<9} "
              f"{r['support_type']:<8} {r['verbatim_quote_match']:<6} {r['word_overlap_ratio']:<8} {flags_short:<25}")
    print("=" * 90)
    total = len(rows)
    pass_quotes = sum(1 for r in rows if r["verbatim_quote_match"] == "PASS")
    pass_locs = sum(1 for r in rows if r["locator_in_bounds"] == "PASS")
    print(f"Total findings audited: {total} | Quotes matching: {pass_quotes}/{total} | Locators valid: {pass_locs}/{total}\n")


def export_to_csv(rows: List[Dict[str, Any]], filepath: str):
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=AUDIT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[+] Wrote audit sheet to {filepath} ({len(rows)} rows).")


def main():
    parser = argparse.ArgumentParser(description="Kasparro Human Audit Sheet Generator")
    parser.add_argument("--pack-dir", default=".", help="Root directory of the assignment pack")
    parser.add_argument("--export-csv", default="audit_sheet.csv", help="Output CSV filepath")
    parser.add_argument("--case", default=None, help="Specific case ID to audit (e.g. PM08)")
    args = parser.parse_args()

    print("\n[+] Generating Kasparro Claim Audit Sheet...")
    rows = generate_audit_rows(pack_dir=args.pack_dir, target_case=args.case)
    if not rows:
        print("[-] No findings found to audit.")
        return
        
    print_summary_table(rows)
    export_to_csv(rows, args.export_csv)


if __name__ == "__main__":
    main()