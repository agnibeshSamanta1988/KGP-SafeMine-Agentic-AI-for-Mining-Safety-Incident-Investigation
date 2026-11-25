# Data cleaning & chunking decisions (Week 2)

All numbers below were measured by the pipeline in this repo. Section 1 and the chunk statistics are for the cleaned
team dataset (`KGP-SafeMine-Data/`, built 15 Nov 2026 from the 2026-10-30 MSHA snapshot).

## 1. Source data: the cleaned team dataset (since 15 Nov 2026)

We now build from `KGP-SafeMine-Data/` in the team GitHub repo, which our teammate de-duplicated and partly redacted
(see its `README.md` and `processing_reports/`). The old raw HTML/zip layout is no
longer used (`clean_reports.py` stays only as the legacy HTML reader).

| Folder | Used for | Reader |
|---|---|---|
| `fatality_investigations/<year>/*.pdf` (655 dossiers) + `events_index.csv` | **RAG corpus** | `safemine/ingest/clean_pdfs.py` |
| `structured_data/*.parquet` (Accidents, Mines, Inspections, MinesProdYearly, Violations, OrdersIssued) | DuckDB, `accident_stats` | `build_duckdb.py` |
| `regulations/cfr_history/cfr_section_versions.jsonl` | DuckDB law store, `cfr_lookup` (law as of a date) | `build_duckdb.py` |
| `regulations/federal_register/federal_register_rules_index.csv` | DuckDB `fr_rules` (in force / proposed) | `build_duckdb.py` |
| `major_disaster_investigations/`, `policy_and_guidance/`, `regulations/cfr_current/`, `mine_act/`, `reference_statistics/` | **not indexed yet** (candidates for Week 3) | - |

Models are not in the dataset: `make models` puts bge-small (tokenizer/local embeddings) and the MiniLM reranker in
`models/`; without it they are fetched from Hugging Face on first use.

### One PDF per event -> documents
Each dossier = front-page metadata table, *1. Event summary* (preliminary), *2. Final investigation report*,
*3. Fatality alert*, and for 88 events *4. Supplementary document* (text a source PDF had that the HTML lacked).

- Text is read per PDF block (= paragraph); the per-page footer is dropped; paragraphs split by a page break are re-joined;
  "Sub-heading + paragraph" blocks are split so DISCUSSION sub-headings survive.
- Section headings come from the PDF bookmarks (exact titles), plus upper-case headings the bookmarks miss
  ("ROOT CAUSE", "CONCLUSION"); appendix headings are dropped.
- **39 older reports (mostly 2008-2010) lost all their headings in the conversion.** Fallback: root-cause pairs and
  citations are found by their wording ("1. Root Cause: …", "A 104(a) Citation …"); first paragraph = summary, rest = narrative.
  Flagged `no_headings_fallback`.
- Older reports cite standards without "30 CFR" ("77.1605(l)"): bare section numbers in Enforcement Actions are kept when
  they exist in the CFR version store.
- Final report -> `final_report` doc; alert -> `fatality_alert` doc; event summary -> `preliminary_report` doc **only** when
  there is no final report (51 events); supplement -> a `SUPPLEMENT` section of the final report.

| | old HTML pipeline | cleaned PDF dataset |
|---|---|---|
| final reports | 604 | 604 |
| fatality alerts | 607 | 588 |
| preliminary-only events | 21 | 51 |
| root-cause / corrective-action pairs | 1,079 | 1,084 |
| reports with no root cause found | 20 | 25 |
| reports with no enforcement found | 13 | 21 |

### Privacy: a second redaction pass is still needed
The dataset replaces the victim with "the miner" and titled staff with "[name withheld]" (16,799 replacements). Our
name harvester still finds **2,9xx distinct real names** in the PDFs (witnesses and co-workers named without a title,
"Name — Plant Manager" lists, investigator blocks and an appendix participant list in some 2008 reports). They are
replaced by `[PERSON-n]` / `[VICTIM]` (7,523 + 1,170 mentions) and stored in `data_processed/_restricted/names.json`
for the Output Filter. Lines of dot leaders (tables of contents, participant lists) are dropped after harvesting.

### Data problems in the cleaned dataset (tell the data owner)
1. **Fatality-alert *Best Practices* are missing.** Every dossier's alert section holds only the one-paragraph summary
   (median 322 characters); the "Best Practices" bullet lists were lost in the HTML→PDF conversion. The old pipeline had a
   `BEST_PRACTICES` chunk per alert, the main evidence for prevention questions. Fix at source if possible.
2. **39 reports without section headings** (above) - recovered heuristically, but section filters are less precise there.
3. **Names remain** (above) - the README's "pattern-based" warning is real.
4. Three files are Git-LFS (`Violations.parquet`, Sago and UBB PDFs): without `git lfs pull` there is no `violations` table.
5. `2024/april-13-2024` was merged into `2024/april-13-2024-fatality`; `eval/retrieval_eval.py` maps the old gold id.

## 2. Chunking recommendation

**Use section-aware chunking with a ~450-token ceiling (`--strategy section --size 450`)**, i.e. *structure first, size second*:

| Report part | Chunk unit | Reason |
|---|---|---|
| OVERVIEW + CONCLUSION | 1 `SUMMARY` chunk (conclusion dropped if ≥70% duplicate) | Best "what happened" match; avoids duplicate hits |
| ROOT CAUSE ANALYSIS | **1 chunk per Root Cause / Corrective Action pair** (1,084 pairs) | Atomic, maps 1:1 to gold answers and to the "root cause patterns" intent |
| ENFORCEMENT ACTIONS | **1 chunk per citation/order** | Each carries its 30 CFR section id → exact BM25 hits; links incident ↔ standard |
| DISCUSSION | split on sub-headings (*Equipment*, *Training and Experience*, *Examinations* …); tiny ones (<60 tok, e.g. *Weather*) merged into the next | Sub-headings are the natural topical boundaries |
| DESCRIPTION / INVESTIGATION / GENERAL INFO | paragraph packing ≤450 tokens, 1-sentence overlap | Narrative; keeps timeline continuity |
| Alert | `ALERT_SUMMARY` (+ `BEST_PRACTICES` when present: missing in the cleaned PDFs) | Prevention evidence |
| Supplementary document (88 events) | `SUPPLEMENT`, paragraph packing | Extra text from source PDFs |

Every chunk is stored with metadata (`event_id, date, year, section, subheading, classification, mine_type, material,
state, mine_id, cfr_ids, source_path`) and a **contextual header** (date, date in words, mine name, accident type,
mine type / material, state, document type, section) prepended only for indexing, e.g.

```
2024-04-15 | April 15, 2024 | Riverbend Sand and Gravel | Powered Haulage | Surface Construction Sand and Gravel | Colorado | final report | Root Cause
Root Cause: The mine operator did not secure a raised component to prevent accidental lowering. Corrective Action: …
```

The header lets a 384-dim model and BM25 match "surface sand & gravel conveyor 2024" queries the chunk body never states,
while the citable `text` stays verbatim for `verify_claims`. Result on the cleaned dataset: 10,990 chunks, median 194 tokens, p95 436 (old HTML pipeline: 11,258, median 174, p95 427).
The bge-small limit is 512 tokens; fixed 450-token windows give p95 523, i.e. silent truncation; the embedding call cuts every
text at 510 tokens with the model's tokenizer (the hosted API rejects longer inputs).

### Storage
- **Canonical chunk store:** `data_processed/chunks.jsonl` (swap to Parquet/SQLite if you like) — the single source of truth
  for citations and quote checks.
- **BM25:** `rank_bm25` pickle with a tokenizer that keeps `56.14211(c)` and `103(k)` as tokens.
- **Dense:** a plain normalised NumPy matrix (11k × 384 = 17 MB) — exact cosine search is milliseconds; a vector DB
  adds nothing at this size. Use Chroma/FAISS only if the corpus grows 10×.
- **Structured + law:** one DuckDB file (`safemine.duckdb`).

### Evidence: team benchmark v2.0 (15 Nov)
Benchmark v2.0 (`eval/golden/KGP_SafeMine_100_Golden_Evaluation_Queries.csv`, 100 queries, DEV 14 / TEST 86; replaces
the old `goldset_all.csv`). Retrieval is scored on the 53 rows whose gold evidence is an MSHA fatality report
(`eval/retrieval_results_v2.json`, DEV+TEST). Event level: R@k / MRR. **Ev@8 section** = the 8 evidence chunks the agent
actually reads contain the gold report's gold section (37 rows name a section: root cause 22, enforcement 11, overview 4).

| Chunks | Retriever | R@1 | R@5 | R@10 | MRR | Ev@8 section | before fix: R@1 / Ev@8 |
|---|---|---|---|---|---|---|---|
| section 450 | bm25 | **0.962** | 0.962 | 0.981 | 0.965 | 0.757 | 0.887 / 0.514 |
| section 450 | bm25+rerank | **0.962** | 0.981 | 0.981 | 0.966 | **0.811** | 0.868 / 0.568 |
| section 450 | hybrid | 0.943 | 0.981 | **1.000** | 0.961 | 0.595 | 0.811 / 0.405 |
| section 450 | **hybrid+rerank (default)** | **0.962** | **1.000** | **1.000** | **0.975** | 0.757 | 0.774 / 0.514 |
| fixed 450 | bm25 | 0.925 | 0.962 | 0.962 | 0.939 | - | 0.906 / - |
| fixed 450 | bm25+rerank | **0.962** | 0.962 | 0.981 | 0.965 | - | 0.925 / - |
| fixed 450 | hybrid | 0.906 | 0.981 | 0.981 | 0.937 | - | 0.774 / - |
| fixed 450 | hybrid+rerank | 0.943 | 0.981 | 0.981 | 0.958 | - | 0.849 / - |

- **Header fix (16 Nov):** every chunk's indexing header now carries the **mine name and the date in words**
  ("2019-09-17 | September 17, 2019 | American Eagle Mine | Electrical | …"). The questions name the incident that
  way; before, short Root Cause / citation chunks could not match it. Result for the default (section 450, hybrid +
  rerank): R@1 0.774 → 0.962, R@10 0.962 → 1.000, Ev@8 section 0.514 → 0.757.
- **Section-level evidence is still the weaker number** (Ev@8 0.76-0.81): about 1 in 5 section questions gets the right
  report but not its gold section in the 8 chunks. bm25+rerank does best here (0.811) while hybrid+rerank is best at
  finding the report (R@10 1.000). Decide between them on DEV only; the planner can also request
  `sections=["ROOT_CAUSE"]`.
- Q095 (a contradicted claim quoting another report's wording) is the only report missed by most setups.
- `cfr_lookup` passes all 16 regulation rows (exact text, section-by-title, 2008 vs current version):
  `eval/cfr_results_v2.json`.
- Abstention, refusal, statistics and claim-verification rows (Families C/D, Q053-Q064) need the end-to-end agent run.
- The benchmark is frozen (`eval/golden/benchmark_freeze.txt`, sha256 checked). These numbers are on DEV+TEST; tune
  only on the 14 DEV rows (`--split DEV`), TEST is for the final report.
- Chunking call: section 450 stays the default (atomic root-cause / citation chunks are what the verifier and the
  section metric need; fixed windows cannot be scored by section).

### Earlier synthetic check (proxy retrieval eval)
120 proxy queries (fatality-alert summary → same event's final report, dates stripped), event-level, BM25 only
(dense blocked by the LFS stub), on the old HTML data; result files retired.

| Chunks | # chunks | p95 tok | Retriever | R@1 | R@5 | R@10 | MRR |
|---|---|---|---|---|---|---|---|
| fixed 450 | 6,357 | 567 | BM25 | **0.908** | 0.975 | 0.983 | **0.939** |
| section 350 | 12,468 | 338 | BM25 | 0.858 | 0.975 | 0.983 | 0.914 |
| **section 450** | 11,258 | 427 | BM25 | 0.875 | 0.975 | 0.975 | 0.921 |
| section 600 | 10,382 | 551 | BM25 | 0.867 | 0.983 | 0.983 | 0.919 |
| section 450 | | | BM25 + MiniLM rerank (*replace*) | 0.717 | 0.908 | 0.967 | 0.801 |
| section 450 | | | BM25 + MiniLM rerank (*fuse*, default) | 0.850 | 0.958 | 0.983 | 0.892 |

How to read this honestly:
- **The proxy saturates** (R@5 ≈ 0.98 everywhere): alert summaries share most of their words with the report, so
  BM25 wins easily and chunk size barely matters. Fixed windows edge R@1 because one big window holds more of the
  same words. It does *not* measure what the golden set asks (root causes, standards, patterns across incidents).
- Section-aware is still the recommendation because of what the proxy can't see: atomic root-cause / citation
  chunks (precise evidence for the verifier and the 8B model's small context), section filters
  (`sections=["ROOT_CAUSE"]`), no >512-token truncation, and cleaner citations. Confirm on the golden set — report
  recall@k for `fixed450` vs `section450` there; that comparison is a graded "chunking experiment".
- **The MS-MARCO reranker hurt when used to re-sort** (R@1 −16 pts). It was trained on short web questions; the proxy
  queries are long narratives. Fusing its rank with the retrieval rank (RRF) recovers most of it, so `fuse` is the
  default (`RERANK_MODE=replace|fuse`, or `use_rerank=False`). Your golden questions are short, so the reranker may
  help there — measure it rather than assume.

Re-run with your golden set to make the final call — the proxy is a sanity check, not the benchmark.
