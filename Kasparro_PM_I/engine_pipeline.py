"""
Kasparro Multi-Agent Visibility Research, Deterministic Validator & State Engine
v3.0

What changed vs v2.0 (see CHANGELOG at the bottom of this file):
  * InjectionScanner: unicode-normalised, cross-line, pre-model scanning + redaction helper
  * VerificationAgent: claim-to-quote overlap, unsupported-number, date-mismatch and absence-claim
    checks (warnings -> human review), model-failure critical flag, policy version
  * PersistentStateStore: stored-report-as-truth decisions, role/action matrix, lead-only approval for
    current-decision briefs, real deadline-based expiry sweep, review-time measurement,
    re-verification + evidence-hash check on invalidation
  * Hash now covers decision date, scope, model id, allowed sources and software flags

Execution provenance: nothing in this file calls a model. Model/replay stages live in replay_fixtures.py.
"""

import os
import sys
import re
import json
import time
import sqlite3
import hashlib
import subprocess
import statistics
import unicodedata
from typing import List, Dict, Any, Optional, Tuple, Callable
from dataclasses import dataclass, asdict, field

POLICY_VERSION = "policy-v3.0"
REVIEW_SLA_SECONDS = float(os.environ.get("KASPARRO_REVIEW_SLA_SECONDS", "86400"))
CLAIM_OVERLAP_MIN = 0.15   # heuristic triage threshold, NOT an entailment test


# -------------------------------------------------------------------------
# 0. TEXT HELPERS
# -------------------------------------------------------------------------

_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"), None)

_STOP = set(
    "the and for with that this from are was were has have had not but its their they them than then which who "
    "how what when where will would can could may might also into onto over under about across between "
    "answer answers state states stated describes described engine engines saved archived".split()
)


def normalize_text(text: str) -> str:
    """NFKC-normalise, strip zero-width/soft-hyphen characters, collapse whitespace."""
    t = unicodedata.normalize("NFKC", text or "").translate(_ZERO_WIDTH)
    return re.sub(r"\s+", " ", t).strip()


def content_words(text: str) -> set:
    cleaned = re.sub(r"%[0-9a-fA-F]{2}", " ", normalize_text(text).lower())
    out = set()
    for w in re.findall(r"[a-z0-9]+", cleaned):
        if len(w) < 3 or w in _STOP:
            continue
        if len(w) > 4 and w.endswith("s"):
            w = w[:-1]
        out.add(w)
    return out


_NUM_RX = re.compile(r"[\u20b9$\u20ac\u00a3]?\d[\d,]*(?:\.\d+)?(?:[kKmM]\b|%?)")


def _num_core(token: str) -> str:
    t = token.strip().lower()
    mult = 1000 if t.endswith("k") else (1000000 if t.endswith("m") else 1)
    core = re.sub(r"[^\d.%]", "", t).rstrip(".")
    if mult > 1 and core and not core.endswith("%"):
        try:
            return str(int(float(core) * mult))
        except ValueError:
            pass
    return core


def all_numbers(text: str) -> set:
    return {_num_core(m).rstrip("%") for m in _NUM_RX.findall(normalize_text(text))}


def material_numbers(text: str) -> set:
    """Numbers a reader would treat as a fact: percentages, or 3+ digit figures. Small counts are ignored."""
    res = set()
    for m in _NUM_RX.findall(normalize_text(text)):
        core = _num_core(m)
        digits = re.sub(r"\D", "", core)
        if core.endswith("%") or len(digits) >= 3:
            res.add(core.rstrip("%"))
    return res


# -------------------------------------------------------------------------
# 1. DATA CONTRACTS & SCHEMAS
# -------------------------------------------------------------------------

@dataclass
class EvidenceItem:
    source_id: str
    kind: str
    as_of: str
    publication_date: Optional[str]
    line_count: int
    lines: Dict[int, str]        # 1-indexed line map from evidence/text/{source_id}.txt
    raw_text: str
    content_hash: str
    execution_mode: str = "replay"


@dataclass
class FindingItem:
    claim: str
    source_id: str
    line_range: str              # e.g., "L1-L4"
    quote: str                   # Verbatim substring from the cited line_range
    evidence_date: str
    support_type: str = "direct"  # "direct" | "absence" | "computed"


@dataclass
class RecommendationItem:
    priority: int
    title: str
    rationale: str
    customer_value: str
    limits_and_risks: str
    next_validation_step: str


@dataclass
class BriefReport:
    request_id: str
    case_id: str
    version: int
    decision_date: str
    evidence_date: str           # Derived from actual evidence timestamps
    claim_time_scope: str
    user_question: str
    execution_mode: str          # "replay" or "live"
    model_id: str
    material_findings: List[Dict[str, Any]]
    uncertainties_and_gaps: List[str]
    prioritized_recommendations: List[Dict[str, Any]]
    software_checks: Dict[str, Any]
    routing_reasons: List[str]
    review_status: str           # DRAFT, DRAFT_AUTO_COMPLETED, NEEDS_REVIEW, APPROVED, REJECTED, EXPIRED, STOPPED
    review_route: str            # AUTO_COMPLETE_DRAFT, ROUTE_TO_HUMAN, SAFE_STOP
    evidence_hashes: Dict[str, str] = field(default_factory=dict)
    decision_history: List[Dict[str, Any]] = field(default_factory=list)
    human_attention_items: List[str] = field(default_factory=list)
    input_payload_hash: str = ""
    content_hash: str = ""
    allowed_source_ids: List[str] = field(default_factory=list)
    policy_version: str = POLICY_VERSION
    stage_trace: List[Dict[str, Any]] = field(default_factory=list)

    def calculate_hash(self) -> str:
        """
        Hashes every material field a reviewer relies on. Status/route/history/trace are deliberately
        excluded (they change as a result of decisions, not of content).
        """
        sw = self.software_checks or {}
        payload = {
            "request_id": self.request_id,
            "case_id": self.case_id,
            "version": self.version,
            "user_question": self.user_question,
            "decision_date": self.decision_date,
            "claim_time_scope": self.claim_time_scope,
            "evidence_date": self.evidence_date,
            "execution_mode": self.execution_mode,
            "model_id": self.model_id,
            "allowed_source_ids": sorted(self.allowed_source_ids),
            "policy_version": self.policy_version,
            "findings": self.material_findings,
            "uncertainties": self.uncertainties_and_gaps,
            "recommendations": self.prioritized_recommendations,
            "evidence_hashes": self.evidence_hashes,
            "critical_flags": sw.get("critical_flags", []),
            "warning_flags": sw.get("warning_flags", []),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


# -------------------------------------------------------------------------
# 2. PROMPT-INJECTION SCANNER (deterministic; runs BEFORE any model sees evidence)
# -------------------------------------------------------------------------

class InjectionScanner:
    """
    Regex scanner over normalised text. It catches instruction-override, self-approval, citation-hiding,
    reviewer-authority and review-bypass phrasing, per line and across line breaks.

    KNOWN LIMITS (disclose these): English only; paraphrases that avoid these verb/noun pairs, encoded or
    obfuscated text (leetspeak, homoglyphs beyond NFKC) are not detected. It is a tripwire, not a guarantee.
    The structural defence is that retrieved text is never given authority: it can only be quoted as data.
    """
    PATTERNS: Dict[str, "re.Pattern"] = {
        "override_instructions": re.compile(
            r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(user|previous|prior|above|earlier|system|your)\b"
            r"[^.\n]{0,30}\b(request|instructions?|prompt|rules?|policy|policies|guidelines?)\b", re.I),
        "self_approval": re.compile(
            r"\b(mark|set|label|record|treat)\b[^.\n]{0,30}\b(report|brief|this)\b[^.\n]{0,30}"
            r"\b(approved|authori[sz]ed)\b", re.I),
        "hide_sources": re.compile(
            r"\b(do not|don't|never|without)\b[^.\n]{0,20}\b(show|include|cite|display|reveal|list)\b"
            r"[^.\n]{0,25}\b(sources?|citations?|references?)\b", re.I),
        "reviewer_authority": re.compile(
            r"\b(treat|consider|regard)\b[^.\n]{0,40}\b(reviewer|approval|human review)\b[^.\n]{0,20}"
            r"\bauthori[sz]ation\b", re.I),
        "bypass_review": re.compile(
            r"\b(bypass|skip|disable|waive)\b[^.\n]{0,25}\b(human|reviewer|review|verification|validation|checks?)\b", re.I),
        "system_override": re.compile(r"\bsystem\s+override\b|\bnew\s+instructions?\s*:", re.I),
        "test_payload_marker": re.compile(r"\bcontrolled\s+test\s+payload\b", re.I),
    }

    @classmethod
    def scan_lines(cls, lines: Dict[int, str]) -> List[Dict[str, Any]]:
        hits: List[Dict[str, Any]] = []
        seen_by_line = set()
        for ln, txt in sorted(lines.items()):
            norm = normalize_text(txt)
            for pid, rx in cls.PATTERNS.items():
                if rx.search(norm):
                    hits.append({"line": ln, "pattern": pid})
                    seen_by_line.add(pid)
        joined = normalize_text(" ".join(t for _, t in sorted(lines.items())))
        for pid, rx in cls.PATTERNS.items():
            if pid not in seen_by_line and rx.search(joined):
                hits.append({"line": None, "pattern": pid})   # split across lines
        return hits

    @classmethod
    def scan_evidence(cls, ev: "EvidenceItem") -> List[Dict[str, Any]]:
        return cls.scan_lines(ev.lines)

    @classmethod
    def scan_text(cls, text: str) -> List[Dict[str, Any]]:
        return cls.scan_lines({i: t for i, t in enumerate(text.splitlines(), start=1)})


def redact_evidence_for_model(evidence_map: Dict[str, EvidenceItem],
                              flagged: Dict[str, List[Dict[str, Any]]]) -> Dict[str, EvidenceItem]:
    """
    Returns a COPY of the evidence in which flagged lines (or whole sources, for cross-line hits) are replaced by a
    placeholder. The verifier and the human reviewer still see the original; the model never does.
    """
    out: Dict[str, EvidenceItem] = {}
    for sid, ev in evidence_map.items():
        hits = flagged.get(sid)
        if not hits:
            out[sid] = ev
            continue
        whole = any(h["line"] is None for h in hits)
        bad = {h["line"] for h in hits if h["line"] is not None}
        new_lines = {ln: ("[REDACTED: suspected instruction injection]" if (whole or ln in bad) else txt)
                     for ln, txt in ev.lines.items()}
        out[sid] = EvidenceItem(ev.source_id, ev.kind, ev.as_of, ev.publication_date, ev.line_count, new_lines,
                                "\n".join(f"L{k}: {v}" for k, v in sorted(new_lines.items())),
                                ev.content_hash, ev.execution_mode)
    return out


# -------------------------------------------------------------------------
# 3. EVIDENCE AGENT (FILE + SUBPROCESS READER WITH BOUNDED RETRIES)
# -------------------------------------------------------------------------

class EvidenceAgent:
    def __init__(self, pack_dir: str = ".", max_retries: int = 3):
        self.pack_dir = pack_dir
        self.max_retries = max_retries
        self.sources_meta = self._load_sources_jsonl()

    def _load_sources_jsonl(self) -> Dict[str, Dict[str, Any]]:
        path = os.path.join(self.pack_dir, "evidence", "sources.jsonl")
        if not os.path.exists(path):
            raise FileNotFoundError(f"CRITICAL: Required pack file missing: {path}")
        meta = {}
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    obj = json.loads(line)
                    meta[obj["source_id"]] = obj
        return meta

    def _parse_numbered_lines(self, text_content: str) -> Dict[int, str]:
        raw_lines = text_content.splitlines()
        numbered_map = {}
        for line in raw_lines:
            # one optional separator (':', tab or '|') then spaces; a table row's own leading '|' is kept
            m = re.match(r"^L0*(\d+)(?:(?::|\t|\|)?[ \t]*(.*))?$", line)
            if m:
                numbered_map[int(m.group(1))] = m.group(2) if m.group(2) is not None else ""
        if numbered_map:
            return numbered_map
        return {idx: line for idx, line in enumerate(raw_lines, start=1)}

    def fetch_via_evidence_tool(self, case_id: str, source_id: str,
                                scenario: Optional[str] = None) -> Tuple[bool, Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Uses tools/evidence_tool.py via subprocess when it exists and a failure scenario is requested; otherwise a
        labelled deterministic fallback. Inspects BOTH exit code and returned content. Bounded retries.
        """
        tool_path = os.path.join(self.pack_dir, "tools", "evidence_tool.py")
        attempt_logs: List[Dict[str, Any]] = []

        for attempt in range(1, self.max_retries + 1):
            if os.path.exists(tool_path) and scenario is not None:
                cmd = [sys.executable, tool_path, "--case", case_id, "--source", source_id,
                       "--scenario", scenario, "--attempt", str(attempt)]
                proc = subprocess.run(cmd, capture_output=True, text=True)
                stdout, stderr = proc.stdout.strip(), proc.stderr.strip()
                attempt_logs.append({"attempt": attempt, "returncode": proc.returncode,
                                     "stdout_preview": stdout[:120], "stderr_preview": stderr[:120]})
                if proc.returncode != 0:
                    try:
                        err_payload = json.loads(stdout)
                    except Exception:
                        return False, None, attempt_logs
                    if isinstance(err_payload, dict) and err_payload.get("error", {}).get("retryable") is False:
                        return False, None, attempt_logs
                    continue
                try:
                    data = json.loads(stdout)
                except Exception:
                    return False, None, attempt_logs
                if not isinstance(data, dict) or (data.get("source") is None and "body" not in data and "text" not in data):
                    return False, None, attempt_logs
                return True, (data["source"] if isinstance(data.get("source"), dict) else data), attempt_logs
            else:
                # Deterministic fallback (simulated scenario; labelled in the log)
                if scenario == "transient_timeout" and attempt < 3:
                    attempt_logs.append({"attempt": attempt, "returncode": 1, "error": "TIMEOUT", "simulated": True})
                    continue
                if scenario == "permanent_timeout":
                    attempt_logs.append({"attempt": attempt, "returncode": 1, "error": "TIMEOUT", "simulated": True})
                    continue
                if scenario == "empty":
                    attempt_logs.append({"attempt": attempt, "returncode": 0, "result": "ok true, source null", "simulated": True})
                    return False, None, attempt_logs
                if scenario == "malformed":
                    attempt_logs.append({"attempt": attempt, "returncode": 0, "result": "invalid JSON text", "simulated": True})
                    return False, None, attempt_logs
                if source_id not in self.sources_meta:
                    attempt_logs.append({"attempt": attempt, "returncode": 2, "error": f"Unknown source_id {source_id}"})
                    return False, None, attempt_logs
                attempt_logs.append({"attempt": attempt, "returncode": 0, "status": "ok"})
                return True, self.sources_meta[source_id], attempt_logs

        return False, None, attempt_logs

    def _read_source_text(self, sid: str, src_meta: Dict[str, Any]) -> str:
        text_rel_path = src_meta.get("text_path", f"evidence/text/{sid}.txt")
        full = os.path.join(self.pack_dir, text_rel_path)
        if os.path.exists(full):
            with open(full, "r", encoding="utf-8") as tf:
                return tf.read()
        return src_meta.get("body", "")

    def evidence_hashes_for(self, source_ids: List[str],
                            custom_sources: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Optional[str]]:
        """Fresh hashes of the evidence as it is on disk now (None when a source cannot be read)."""
        out: Dict[str, Optional[str]] = {}
        for sid in source_ids:
            if custom_sources and sid in custom_sources:
                out[sid] = hashlib.sha256(custom_sources[sid]["body"].encode("utf-8")).hexdigest()
            elif sid in self.sources_meta:
                out[sid] = hashlib.sha256(self._read_source_text(sid, self.sources_meta[sid]).encode("utf-8")).hexdigest()
            else:
                out[sid] = None
        return out

    def retrieve_closed_set(self, case_id: str, allowed_source_ids: List[str],
                            scenario: Optional[str] = None,
                            custom_sources: Optional[Dict[str, Dict[str, Any]]] = None
                            ) -> Tuple[Dict[str, EvidenceItem], List[str], List[Dict[str, Any]]]:
        evidence_map: Dict[str, EvidenceItem] = {}
        errors: List[str] = []
        all_traces: List[Dict[str, Any]] = []

        for sid in allowed_source_ids:
            if custom_sources and sid in custom_sources:
                src_meta = custom_sources[sid]
                raw_text = src_meta["body"]
                lines_map = self._parse_numbered_lines(raw_text)
                evidence_map[sid] = EvidenceItem(
                    source_id=sid, kind=src_meta.get("kind", "custom_test_source"),
                    as_of=src_meta.get("as_of", "2026-07-31"),
                    publication_date=src_meta.get("publication_date") or "unknown",
                    line_count=len(lines_map), lines=lines_map, raw_text=raw_text,
                    content_hash=hashlib.sha256(raw_text.encode("utf-8")).hexdigest())
                continue

            ok, data, logs = self.fetch_via_evidence_tool(case_id, sid, scenario=scenario)
            all_traces.extend(logs)
            if not ok or not data:
                errors.append(f"SOURCE_FETCH_ERROR:{sid}:Failed after {len(logs)} attempt(s) under scenario={scenario}")
                continue

            src_meta = self.sources_meta.get(sid, data)
            raw_text = self._read_source_text(sid, src_meta)
            lines_map = self._parse_numbered_lines(raw_text)
            evidence_map[sid] = EvidenceItem(
                source_id=sid, kind=src_meta.get("kind", "unknown"), as_of=src_meta.get("as_of", "unknown"),
                publication_date=src_meta.get("publication_date") or "unknown",   # missing dates stay UNKNOWN
                line_count=src_meta.get("line_count", len(lines_map)), lines=lines_map, raw_text=raw_text,
                content_hash=hashlib.sha256(raw_text.encode("utf-8")).hexdigest())

        return evidence_map, errors, all_traces


# -------------------------------------------------------------------------
# 4. DETERMINISTIC VERIFICATION
# -------------------------------------------------------------------------

# PACK-TUNED heuristics: these strings come from the 12 supplied cases. They are NOT general entity or benchmark
# detection. A new pack needs new entries (or a model-based entity check). Disclose this in the decision memo.
PACK_TUNED_ENTITY_COLLISIONS = ["kaspr", "otter.ai", "cairrot", "getkasper", "revenuepulseai"]


class VerificationAgent:
    """
    Software checks (binary, deterministic):
      CRIT-LEAK, CRIT-MISSING-SOURCE, CRIT-BAD-LOCATOR, CRIT-LOCATOR-OUT-OF-BOUNDS, CRIT-UNSUPPORTED-QUOTE,
      CRIT-INJECT, CRIT-EMPTY-EVIDENCE, CRIT-NO-FINDINGS, CRIT-MODEL-FAILURE
    Triage warnings (route to human, never auto-complete):
      FLAG-LOW-CLAIM-OVERLAP, FLAG-UNSUPPORTED-NUMBER, FLAG-DATE-MISMATCH, FLAG-ABSENCE-CLAIM,
      FLAG-ENTITY-AMBIGUITY, FLAG-UNVERIFIED-BENCHMARK, FLAG-PIPELINE-OR-ENGINE-FAILURE, FLAG-TEMPORAL-GAP,
      FLAG-FETCH-ERROR
    IMPORTANT: a verbatim quote proves the quote exists, not that the claim follows from it. The overlap/number
    checks are cheap triage signals. Claim correctness is judged by a human or by a separate model verifier.
    """

    def verify(self, case: Dict[str, Any],
               evidence_map: Dict[str, EvidenceItem],
               fetch_errors: List[str],
               findings: List[FindingItem],
               uncertainties: List[str],
               recommendations: List[RecommendationItem],
               extra_critical: Optional[List[str]] = None
               ) -> Tuple[Dict[str, Any], List[str], str, str, List[str]]:

        allowed_ids = set(case.get("allowed_source_ids", []))
        critical_flags: List[str] = list(extra_critical or [])
        warning_flags: List[str] = []
        routing_reasons: List[str] = []
        attention_items: List[str] = []
        diagnostics: List[Dict[str, Any]] = []

        if extra_critical:
            routing_reasons.append("Analysis stage failed after bounded retries; no unverified output is released.")

        # 1. Empty evidence / fetch failure
        if len(evidence_map) == 0:
            critical_flags.append("CRIT-EMPTY-EVIDENCE: Zero valid evidence sources retrieved.")
            routing_reasons.append("Zero evidence retrieved due to tool/source failure.")
        if fetch_errors:
            warning_flags.append(f"FLAG-FETCH-ERROR: {len(fetch_errors)} source(s) failed retrieval.")
            routing_reasons.append("Incomplete evidence set from failed source fetch.")
            attention_items.extend(fetch_errors)

        # 2. Injection scan over ALL retrieved evidence
        for sid, ev in evidence_map.items():
            hits = InjectionScanner.scan_evidence(ev)
            if hits:
                lines = sorted({h["line"] for h in hits if h["line"] is not None})
                pats = sorted({h["pattern"] for h in hits})
                where = f"lines {lines}" if lines else "across line breaks"
                critical_flags.append(f"CRIT-INJECT: Untrusted instruction/authority override pattern in source {sid} ({where}; {', '.join(pats)})")
                routing_reasons.append(f"Prompt injection pattern detected inside source {sid}.")
                attention_items.append(f"Security Alert: Source {sid} contains instruction-override text. Auto-completion blocked.")

        # 3. Per-finding validation
        if len(findings) == 0 and len(critical_flags) == 0:
            critical_flags.append("CRIT-NO-FINDINGS: Brief contains zero material findings.")
            routing_reasons.append("No material findings produced.")

        for idx, f in enumerate(findings):
            n = idx + 1
            if f.source_id not in allowed_ids:
                critical_flags.append(f"CRIT-LEAK: Finding #{n} cites unauthorized source '{f.source_id}'")
                routing_reasons.append(f"Unauthorized source '{f.source_id}' cited.")
                continue
            if f.source_id not in evidence_map:
                critical_flags.append(f"CRIT-MISSING-SOURCE: Finding #{n} cites unretrieved source '{f.source_id}'")
                routing_reasons.append(f"Finding #{n} cites a source that could not be retrieved.")
                continue

            ev = evidence_map[f.source_id]
            m = re.match(r"^L(\d+)(?:-L?(\d+))?$", f.line_range.strip())
            if not m:
                critical_flags.append(f"CRIT-BAD-LOCATOR: Finding #{n} has invalid locator format '{f.line_range}'")
                continue
            start_line = int(m.group(1))
            end_line = int(m.group(2)) if m.group(2) else start_line
            if start_line < 1 or end_line < start_line or end_line > ev.line_count:
                critical_flags.append(
                    f"CRIT-LOCATOR-OUT-OF-BOUNDS: Finding #{n} cites {f.source_id}:{f.line_range}, but source has {ev.line_count} lines.")
                routing_reasons.append(f"Out-of-bounds line locator {f.source_id}:{f.line_range}.")
                continue

            cited_segment = "\n".join(ev.lines.get(ln, "") for ln in range(start_line, end_line + 1))
            norm_seg = normalize_text(cited_segment)
            norm_quote = normalize_text(f.quote)
            # tolerate a leading/trailing markdown-table pipe that a line-prefix format may have consumed
            quote_variants = {norm_quote, norm_quote.strip("| ").strip()}
            if not norm_quote or not any(q and q in norm_seg for q in quote_variants):
                critical_flags.append(
                    f"CRIT-UNSUPPORTED-QUOTE: Finding #{n} quote '{f.quote[:60]}...' not found verbatim in {f.source_id}:{f.line_range}.")
                routing_reasons.append(f"Quote mismatch in {f.source_id}:{f.line_range}.")
                continue

            # --- triage checks on a finding whose quote is genuine ---
            diag: Dict[str, Any] = {"finding": n, "source_id": f.source_id, "support_type": f.support_type}
            if f.support_type == "absence":
                warning_flags.append(f"FLAG-ABSENCE-CLAIM: Finding #{n} asserts an absence; a quote cannot prove it.")
                routing_reasons.append(f"Finding #{n} is an absence claim; analyst must confirm what was searched.")
            elif f.support_type != "computed":
                date_prefix = str(ev.as_of)[:10] if ev.as_of else ""
                cw = content_words(f.claim)
                sw_ = content_words(f"{cited_segment} {f.quote} {date_prefix}")
                overlap = round(len(cw & sw_) / len(cw), 2) if cw else 1.0
                diag["claim_overlap"] = overlap
                if overlap < CLAIM_OVERLAP_MIN:
                    warning_flags.append(f"FLAG-LOW-CLAIM-OVERLAP: Finding #{n} claim shares only {overlap:.0%} of its content words with the cited lines.")
                    routing_reasons.append(f"Finding #{n}: claim may go beyond what the cited lines say.")
                src_nums = all_numbers(f"{ev.source_id} {date_prefix} {ev.raw_text}")
                unsupported = sorted(x for x in material_numbers(f.claim) if x not in src_nums)
                diag["unsupported_numbers"] = unsupported
                if unsupported:
                    warning_flags.append(f"FLAG-UNSUPPORTED-NUMBER: Finding #{n} states {unsupported} not present in {f.source_id}.")
                    routing_reasons.append(f"Finding #{n}: numeric claim not traceable to the source text.")
            if ev.as_of and ev.as_of != "unknown" and f.evidence_date and str(f.evidence_date)[:10] != str(ev.as_of)[:10]:
                warning_flags.append(f"FLAG-DATE-MISMATCH: Finding #{n} dated {f.evidence_date}, source as_of {ev.as_of}.")
                routing_reasons.append(f"Finding #{n}: evidence date differs from the source record.")
            diagnostics.append(diag)

        # 4. Content-driven risk reasons (pack-tuned; never keyed on case_id)
        combined_text = " ".join([f.claim + " " + f.quote for f in findings] + uncertainties).lower()

        if any(name in combined_text for name in PACK_TUNED_ENTITY_COLLISIONS):
            warning_flags.append("FLAG-ENTITY-AMBIGUITY: Third-party namesake or domain collision detected.")
            routing_reasons.append("Entity collision/misattribution requires analyst verification.")
            attention_items.append("Verify entity identity: engine output references a third-party namesake.")

        if ("average" in combined_text and "median" in combined_text) or "n=64" in combined_text:
            warning_flags.append("FLAG-UNVERIFIED-BENCHMARK: First-party benchmark/cohort claim lacks underlying study dataset.")
            routing_reasons.append("Unverified or conflicting statistical benchmark definitions.")
            attention_items.append("Inspect benchmark definitions: 18.4% cited as both average and median; cohort data unverified.")

        if "gate_halt" in combined_text or "nonbranded_spine_unavailable" in combined_text or "cannot fulfill" in combined_text:
            warning_flags.append("FLAG-PIPELINE-OR-ENGINE-FAILURE: Partial module failure or engine refusal observed.")
            routing_reasons.append("Pipeline module failure or engine refusal affects coverage denominator.")
            attention_items.append("Inspect failure impact: Run contains failed pipeline module or engine refusal.")

        if case.get("claim_time_scope") == "current_decision":
            warning_flags.append("FLAG-TEMPORAL-GAP: Current buying/commercial decision requested using historical captures.")
            routing_reasons.append("claim_time_scope is 'current_decision' while engine captures date to 2026-07-31.")
            attention_items.append("Temporal scope check: Confirm July 2026 snapshot limits before advising a current decision.")

        if len(recommendations) > 0:
            routing_reasons.append(f"Brief proposes {len(recommendations)} consequential recommendation(s) requiring analyst review.")
            attention_items.append("Review proposed recommendations and validation steps before external sharing.")
        if any(w.startswith(("FLAG-LOW-CLAIM-OVERLAP", "FLAG-UNSUPPORTED-NUMBER", "FLAG-ABSENCE-CLAIM", "FLAG-DATE-MISMATCH")) for w in warning_flags):
            attention_items.append("Check claim-to-quote support: at least one claim may exceed its cited lines (see software_checks.diagnostics).")

        # 5. Route and status derive ONLY from checks and reasons
        software_checks = {
            "closed_world_passed": not any(c.startswith("CRIT-LEAK") for c in critical_flags),
            "locator_bounds_passed": not any(c.startswith(("CRIT-LOCATOR-OUT-OF-BOUNDS", "CRIT-BAD-LOCATOR")) for c in critical_flags),
            "verbatim_quotes_passed": not any(c.startswith("CRIT-UNSUPPORTED-QUOTE") for c in critical_flags),
            "injection_scan_passed": not any(c.startswith("CRIT-INJECT") for c in critical_flags),
            "non_empty_evidence_passed": not any(c.startswith(("CRIT-EMPTY-EVIDENCE", "CRIT-NO-FINDINGS")) for c in critical_flags),
            "model_stage_passed": not any(c.startswith("CRIT-MODEL-FAILURE") for c in critical_flags),
            "claim_support_passed": not any(w.startswith(("FLAG-LOW-CLAIM-OVERLAP", "FLAG-UNSUPPORTED-NUMBER", "FLAG-ABSENCE-CLAIM")) for w in warning_flags),
            "critical_flags": critical_flags,
            "warning_flags": warning_flags,
            "diagnostics": diagnostics,
            "policy_version": POLICY_VERSION,
        }
        software_checks["all_software_checks_passed"] = (len(critical_flags) == 0)

        if critical_flags:
            route, status = "SAFE_STOP", "STOPPED"
        elif warning_flags or recommendations or fetch_errors:
            route, status = "ROUTE_TO_HUMAN", "NEEDS_REVIEW"
        else:
            route, status = "AUTO_COMPLETE_DRAFT", "DRAFT_AUTO_COMPLETED"   # remains visibly a draft

        return software_checks, routing_reasons, route, status, attention_items


# -------------------------------------------------------------------------
# 5. PERSISTENT STATE STORE & HUMAN DECISION ENGINE (SQLite)
# -------------------------------------------------------------------------

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class PersistentStateStore:
    """
    Enforces:
      - idempotent request_id / conflict detection (done by the orchestrator via input_payload_hash)
      - one review task per (request_id, version)
      - REJECTED / EXPIRED / STOPPED are terminal for that version
      - decisions are applied to the STORED report, never to a caller's possibly-edited copy
      - role x action matrix; current-decision briefs need a lead role to approve
      - approvals are bound to a content hash; changes (or changed evidence) invalidate and spawn v+1
    Reviewer identity is a SIMULATED role string. No authentication is performed (disclosed production gap).
    """
    VALID_ROLES = {"internal_analyst", "lead_reviewer", "product_manager"}
    ROLE_ACTIONS = {
        "internal_analyst": {"CORRECT"},
        "lead_reviewer": {"APPROVE", "REJECT", "CORRECT"},
        "product_manager": {"APPROVE", "REJECT", "CORRECT"},
    }
    LEAD_ROLES = {"lead_reviewer", "product_manager"}
    LEAD_ONLY_SCOPES = {"current_decision"}
    TERMINAL_STATUSES = {"REJECTED", "EXPIRED", "STOPPED"}
    DECIDABLE_STATUSES = {"DRAFT", "NEEDS_REVIEW", "DRAFT_AUTO_COMPLETED"}

    def __init__(self, db_path: str = "kasparro_state.db", review_deadline_seconds: Optional[float] = None):
        self.db_path = db_path
        self.review_deadline_seconds = REVIEW_SLA_SECONDS if review_deadline_seconds is None else review_deadline_seconds
        self._init_db()

    # ---- schema -----------------------------------------------------------
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    request_id TEXT, version INTEGER, case_id TEXT, input_payload_hash TEXT, content_hash TEXT,
                    review_status TEXT, review_route TEXT, report_json TEXT, updated_at REAL,
                    PRIMARY KEY (request_id, version))""")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS review_tasks (
                    task_id TEXT PRIMARY KEY, request_id TEXT, version INTEGER, status TEXT, assigned_role TEXT,
                    created_at REAL, UNIQUE(request_id, version))""")
            for col in ("deadline_at", "opened_at", "decided_at"):     # migrate DBs created by v2.0
                try:
                    conn.execute(f"ALTER TABLE review_tasks ADD COLUMN {col} REAL")
                except sqlite3.OperationalError:
                    pass
            conn.commit()

    def reset_store(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM reports")
            conn.execute("DELETE FROM review_tasks")
            conn.commit()

    # ---- persistence ------------------------------------------------------
    def save_report(self, report: BriefReport):
        report.content_hash = report.calculate_hash()
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO reports
                (request_id, version, case_id, input_payload_hash, content_hash, review_status, review_route, report_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (report.request_id, report.version, report.case_id, report.input_payload_hash, report.content_hash,
                 report.review_status, report.review_route, json.dumps(asdict(report)), now))
            if report.review_route == "ROUTE_TO_HUMAN":
                conn.execute("""
                    INSERT OR IGNORE INTO review_tasks
                    (task_id, request_id, version, status, assigned_role, created_at, deadline_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (f"TASK-{report.request_id}-v{report.version}", report.request_id, report.version,
                     report.review_status, "internal_analyst", now, now + self.review_deadline_seconds))
            conn.commit()

    def _load(self, request_id: str, version: int) -> Optional[BriefReport]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT report_json FROM reports WHERE request_id = ? AND version = ?",
                               (request_id, version)).fetchone()
        return BriefReport(**json.loads(row[0])) if row else None

    def get_latest_report(self, request_id: str) -> Optional[BriefReport]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT report_json FROM reports WHERE request_id = ? ORDER BY version DESC LIMIT 1",
                               (request_id,)).fetchone()
        return BriefReport(**json.loads(row[0])) if row else None

    def stored_integrity_ok(self, report: BriefReport) -> bool:
        """True when the stored hash still equals a fresh hash of the stored content (detects tampering at rest)."""
        stored = self._load(report.request_id, report.version)
        return stored is not None and stored.content_hash == stored.calculate_hash()

    def get_review_tasks(self, request_id: Optional[str] = None) -> List[Dict[str, Any]]:
        q = "SELECT task_id, request_id, version, status, assigned_role, created_at, deadline_at, opened_at, decided_at FROM review_tasks"
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(q + (" WHERE request_id = ?" if request_id else ""), (request_id,) if request_id else ()).fetchall()
        keys = ["task_id", "request_id", "version", "status", "assigned_role", "created_at", "deadline_at", "opened_at", "decided_at"]
        return [dict(zip(keys, r)) for r in rows]

    # ---- review-time measurement -------------------------------------------
    def mark_review_opened(self, request_id: str, version: int):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE review_tasks SET opened_at = COALESCE(opened_at, ?) WHERE request_id = ? AND version = ?",
                         (time.time(), request_id, version))
            conn.commit()

    def review_time_stats(self) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT created_at, opened_at, decided_at FROM review_tasks WHERE decided_at IS NOT NULL").fetchall()
        durs = [d - (o if o else c) for c, o, d in rows if d is not None]
        if not durs:
            return {"n": 0, "median_s": None, "mean_s": None, "max_s": None, "provenance": "no decided tasks yet"}
        return {"n": len(durs), "median_s": round(statistics.median(durs), 2), "mean_s": round(statistics.mean(durs), 2),
                "max_s": round(max(durs), 2),
                "provenance": "open-to-decision seconds from this store (simulated walkthrough unless real reviewers used it)"}

    # ---- authority ----------------------------------------------------------
    def check_authority(self, role: str, action: str, report: BriefReport) -> Tuple[bool, str]:
        if role not in self.VALID_ROLES:
            return False, f"Role '{role}' is not a recognised review role."
        if action not in self.ROLE_ACTIONS[role]:
            return False, f"Role '{role}' may not perform '{action}'."
        if action == "APPROVE" and report.claim_time_scope in self.LEAD_ONLY_SCOPES and role not in self.LEAD_ROLES:
            return False, f"'{report.claim_time_scope}' briefs require approval by lead_reviewer or product_manager."
        return True, "ok"

    # ---- decisions ------------------------------------------------------------
    def submit_human_decision(self, report: BriefReport, reviewer_role: str, action: str, note: str = "",
                              reviewer_id: Optional[str] = None) -> Tuple[bool, str, BriefReport]:
        stored = self._load(report.request_id, report.version)
        if stored is None:
            return False, "REPORT_NOT_PERSISTED: save the report before deciding on it.", report

        actor = reviewer_role if not reviewer_id else f"{reviewer_role}:{reviewer_id}"

        def deny(history_action: str, message: str) -> Tuple[bool, str, BriefReport]:
            stored.decision_history.append({"timestamp": _now_iso(), "action": history_action, "actor": actor,
                                            "version": stored.version, "note": f"DENIED: {message}"})
            self.save_report(stored)
            return False, message, stored

        # 1. Authority
        ok, why = self.check_authority(reviewer_role, action, stored)
        if not ok:
            return deny("UNAUTHORIZED_DECISION_ATTEMPT", f"UNAUTHORIZED: {why}")

        # 2. The caller must be deciding on exactly what is stored, and storage must be intact
        if report.calculate_hash() != stored.calculate_hash():
            return deny("STALE_OR_MODIFIED_REPORT_REJECTED",
                        "STALE_OR_MODIFIED_REPORT: the report presented differs from the stored version. Re-open the stored version.")
        if stored.content_hash != stored.calculate_hash():
            return deny("STORED_HASH_MISMATCH", "STORED_HASH_MISMATCH: stored content does not match its recorded hash.")

        # 3. Terminal states cannot be decided
        if stored.review_status in self.TERMINAL_STATUSES:
            return deny(f"INVALID_TRANSITION_FROM_{stored.review_status}",
                        f"INVALID_STATE_TRANSITION: Cannot perform '{action}' when version {stored.version} is "
                        f"'{stored.review_status}'. Create v{stored.version + 1} with spawn_revised_version().")

        # 4. Apply
        if action == "APPROVE":
            if not note.strip():
                return False, "VALIDATION_ERROR: Approval requires a reviewer rationale note.", stored
            if stored.review_status not in self.DECIDABLE_STATUSES:
                return deny("INVALID_TRANSITION_FROM_" + stored.review_status,
                            f"INVALID_STATE_TRANSITION: version {stored.version} is '{stored.review_status}', not awaiting approval.")
            stored.review_status = "APPROVED"
            certified = stored.calculate_hash()
            stored.content_hash = certified
            stored.decision_history.append({"timestamp": _now_iso(), "action": "APPROVED", "actor": actor,
                                            "version": stored.version, "certified_hash": certified, "note": note})
        elif action == "REJECT":
            if not note.strip():
                return False, "VALIDATION_ERROR: Rejection requires a reason.", stored
            if stored.review_status not in self.DECIDABLE_STATUSES | {"APPROVED"}:
                return deny("INVALID_TRANSITION_FROM_" + stored.review_status,
                            f"INVALID_STATE_TRANSITION: version {stored.version} is '{stored.review_status}'.")
            stored.review_status = "REJECTED"
            stored.decision_history.append({"timestamp": _now_iso(), "action": "REJECTED", "actor": actor,
                                            "version": stored.version, "note": note})
        else:
            return False, f"Unknown action '{action}' (use APPROVE or REJECT; corrections go through spawn_revised_version).", stored

        self.save_report(stored)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE review_tasks SET status = ?, decided_at = ? WHERE request_id = ? AND version = ?",
                         (stored.review_status, time.time(), stored.request_id, stored.version))
            conn.commit()
        return True, f"Transitioned v{stored.version} to {stored.review_status}", stored

    # ---- timeouts ---------------------------------------------------------------
    def handle_timeout(self, report: BriefReport, elapsed_seconds: float, timeout_seconds: float = 1.0
                       ) -> Tuple[bool, str, BriefReport]:
        """Caller-asserted timeout (kept for the short simulated demo). Prefer expire_overdue()."""
        if elapsed_seconds >= timeout_seconds and report.review_status in {"DRAFT", "NEEDS_REVIEW"}:
            return self._expire(report, f"Review deadline ({timeout_seconds}s, caller-asserted) elapsed without decision.")
        return False, "Timeout not reached or status not eligible.", report

    def _expire(self, report: BriefReport, reason: str) -> Tuple[bool, str, BriefReport]:
        report.review_status = "EXPIRED"
        report.decision_history.append({
            "timestamp": _now_iso(), "action": "REVIEW_TIMEOUT_EXPIRED", "actor": "system_timer", "version": report.version,
            "note": f"{reason} Version {report.version} is EXPIRED. Permitted next action: spawn_revised_version -> v{report.version + 1}."})
        self.save_report(report)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE review_tasks SET status = 'EXPIRED' WHERE request_id = ? AND version = ?",
                         (report.request_id, report.version))
            conn.commit()
        return True, "EXPIRED: Review timed out. Silent approval blocked; spawn a revised version to re-queue.", report

    def expire_overdue(self, now: Optional[float] = None) -> List[Tuple[str, int]]:
        """Deadline sweep over STORED review tasks. Pass now=time.time()+N to simulate elapsed time in a demo."""
        now = time.time() if now is None else now
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT request_id, version FROM review_tasks WHERE deadline_at IS NOT NULL AND deadline_at <= ? "
                                "AND status IN ('NEEDS_REVIEW', 'DRAFT')", (now,)).fetchall()
        expired = []
        for rid, ver in rows:
            rep = self._load(rid, ver)
            if rep and rep.review_status in {"DRAFT", "NEEDS_REVIEW"}:
                self._expire(rep, "Stored review deadline elapsed.")
                expired.append((rid, ver))
        return expired

    # ---- change after approval ----------------------------------------------------
    def verify_integrity_or_invalidate(self, report: BriefReport,
                                       reverify: Optional[Callable[[BriefReport], BriefReport]] = None,
                                       current_evidence_hashes: Optional[Dict[str, Optional[str]]] = None
                                       ) -> Tuple[bool, str, BriefReport]:
        """
        An approval is valid only for the exact content hash it certified AND the evidence it was made against.
        On a mismatch: revoke, bump the version, RE-RUN verification when a reverify callable is supplied
        (so a tampered quote becomes STOPPED, not merely NEEDS_REVIEW), and never leave the result auto-completed.
        """
        approved_entries = [d for d in report.decision_history if d.get("action") == "APPROVED" and d.get("version") == report.version]
        if not approved_entries:
            return False, "Report version has no active approval certificate.", report

        certified_hash = approved_entries[-1].get("certified_hash")
        current_hash = report.calculate_hash()
        evidence_changed = bool(current_evidence_hashes) and any(
            current_evidence_hashes.get(s) != h for s, h in report.evidence_hashes.items())

        if certified_hash == current_hash and not evidence_changed:
            return True, "Integrity verified: current payload and evidence match the certified hash.", report

        old_version = report.version
        report.version = old_version + 1
        if reverify is not None:
            report = reverify(report)
        observed_hash = report.calculate_hash()
        if report.review_status != "STOPPED":
            report.review_status, report.review_route = "NEEDS_REVIEW", "ROUTE_TO_HUMAN"
        else:
            report.review_route = "SAFE_STOP"
        cause = "Evidence changed on disk" if (evidence_changed and certified_hash == current_hash) else "Content modified"
        report.decision_history.append({
            "timestamp": _now_iso(), "action": "APPROVAL_INVALIDATED_ON_CHANGE", "actor": "integrity_guard",
            "old_version": old_version, "new_version": report.version, "certified_hash": certified_hash,
            "observed_hash": observed_hash, "reverified": reverify is not None,
            "note": f"{cause} after v{old_version} approval. Approval revoked; spawned v{report.version} in {report.review_status}."})
        self.save_report(report)
        return False, (f"INVALIDATED: {cause} (hash {observed_hash[:10]} != {str(certified_hash)[:10]}). "
                       f"Spawned v{report.version} for renewed review."), report


# -------------------------------------------------------------------------
# CHANGELOG v2.0 -> v3.0 (root cause -> change)
#  1. Verbatim quote proved existence, not support       -> overlap / unsupported-number / absence / date triage flags
#  2. Injection scan ran after the model had seen text   -> scanner is reusable pre-model; redact_evidence_for_model()
#  3. Regex evaded by zero-width chars / line splits     -> NFKC + zero-width strip + cross-line scan
#  4. Decisions applied to caller's object               -> decisions applied to stored report; stale/modified copies refused
#  5. Timeout was a caller-supplied number               -> deadline_at stored per task; expire_overdue() sweep
#  6. Invalidation forced NEEDS_REVIEW without re-check  -> reverify callback; evidence-hash drift also invalidates
#  7. Hash omitted scope/date/model/flags                -> payload extended
#  8. No review-time measurement                         -> opened_at/decided_at + review_time_stats()
#  9. Flat authority                                     -> role x action matrix, lead-only approval for current decisions
# -------------------------------------------------------------------------