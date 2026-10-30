EVIDENCE GUIDE
Each source in sources.jsonl has a unique source_id, a kind, a date basis, origin metadata and body text. The text/ copy adds stable line locators L1, L2 and so on. Cite, for example, R-007-gemini:L3-L6. A kind identifies provenance, not whether a claim is true.

A case may use only its allowed_source_ids for assessed findings. The other cases are not additional evidence for that case. You may use all supplied files to understand how the pack is organised. A current reference can help interpret a historical answer, but cannot retroactively establish what was true in July.

Engine answers establish what an engine said. Provider source metadata and snippets are not complete independently inspected pages. The homepage schema is a recorded declaration. Public-document summaries are editorial paraphrases, with URLs and review dates. Publication dates remain unknown where absent.

R- sources preserve archived answer_text. S- sources are dated reference or metadata records. REF- sources summarise official documentation. F-INJECT-01 adds labelled adversarial instructions to an archived excerpt for testing only; the original R- source is unchanged. It is not a real brand finding or an actual reviewer instruction.

The case requests and operating rules are authored for this assessment. Production scores, classifications and existing recommendations are not supplied. You create and defend your own expected outcomes, rubric and review routes.

Optional offline reader, from the pack directory:
  python3 tools/evidence_tool.py --case PM01 --source R-007-gemini
  python3 tools/evidence_tool.py --case PM01 --source R-007-gemini --scenario transient_timeout --attempt 1
  python3 tools/evidence_tool.py --case PM01 --source R-007-gemini --scenario transient_timeout --attempt 3

The fixture emits a TIMEOUT error for attempts 1 and 2, then returns the real source on attempt 3. Other scenarios are permanent_timeout, empty and malformed. Nonzero exit codes represent fixture errors. Your integration must inspect both process outcome and returned content. The fixture is stateless: your workflow owns retry bounds, persistence, identity, duplicate handling, review authority and report versions. It never calls a live model.
