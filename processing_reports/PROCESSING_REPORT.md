# KGP-SafeMine RAG data preparation: final processing report

Destination: `Capstone Project/KGP-SafeMine-Data/` | Source (read-only, untouched): `Capstone Project/KGP-SafeMine/KGP-SafeMine_Data/` | Source snapshot: MSHA files dated 30 Oct 2026, eCFR as of 2026-10-30.

## 1. Summary of the requested numbers

| # | Item | Result |
|---|---|---|
| 1 | Source files and folders inspected | **6,887 files** in **1,395 folders** (every file hashed with SHA-256) |
| 2 | Relevant files identified (contribute content to the dataset) | **2,247** of 6,887 source files |
| 3 | HTML files cleaned and converted into PDFs | **1,869** source HTML pages -> **655** event dossier PDFs + 6 other HTML-based PDFs (disaster overview, UBB corrective actions, silica page, Policy Manual notices, dataset description, dataset catalog) |
| 4 | ZIP archives extracted and inspected | **21** (20 MSHA data-set archives + the U.S. Code Title 30 archive); no nested archives found |
| 5 | PDFs cleaned or merged | **235** source PDFs used; **11** multi-source merged PDFs built from **75** source files (UBB appendices package, UBB reviews package, five disaster pairs, Policy Manual, silica set, rule + correction); the rest copied with descriptive names |
| 6 | Other formats processed | 101 XML, 16 JSON, 13 XLSX, 6 TXT (XML law text -> PDF + version store; XLSX/JSON -> CSV; TXT dictionaries; core data sets -> Parquet) |
| 7 | Duplicate and irrelevant files excluded | **4,640** source files (breakdown in section 4) |
| 8 | Final dataset | **813** files, 0.67 GB (section 3) |
| 9 | Unreadable / unprocessed | **0** outputs unreadable; **68** source PDFs need OCR (not available here); **10** event pages had no narrative; pre-2008 layer (1,864 files) not processed |
| 10 | Gaps and recommendations | Section 7 and `knowledge_gaps.csv` |

## 2. What was done

- **HTML (fatality investigations):** each of the 665 event records (666 source folders; the folder `2024/april-13-2024` holds the final report of the Morgan County Quarry event and was merged into it) was turned into one cleaned, bookmarked PDF containing the MSHA event summary, the final investigation report (headings, lists and tables preserved) and the fatality alert, in that order. Navigation, scripts, styles, forms and images were removed; clickable links were kept. Appendices (people lists and images), the investigator block and the approval signatures were left out. Page types that only repeat other pages were not used (preliminary-report pages repeat the event summary; public notices are boilerplate with investigator phone numbers).
- **Privacy:** the deceased miner's name is replaced by 'the miner' and staff names introduced with a job title by '[name withheld]'. This is pattern-based. A scan of 655 dossiers found **0** victim-name leaks; co-workers or witnesses named without a title can remain (see gaps).
- **PDFs in the fatality folder (1,820):** each was compared with the HTML text of the same event after removing doubled text layers. 1666 were excluded as duplicates, translations, preliminary forms (they print the victim's full name) or scans; the 92 that carry at least 15% and 400 characters of new text were added to their event dossier as supplementary sections. The 62 Upper Big Branch files were handled as a package (below).
- **Major disasters (merged PDFs with bookmarks):** Sago, Aracoma Alma No. 1, Darby No. 1, Jim Walter No. 5 and Crandall Canyon (accident investigation + MSHA review in one PDF each), Quecreek, and three Upper Big Branch PDFs (investigation summary + technical appendices; reviews, assessments and corrective actions; the 1,097-page technical report). People lists, raw handwritten logbooks, a photo-copying procedure and scanned appendices without text were excluded.
- **Regulations:** 42 current 30 CFR parts as structured PDFs (one per Part); a de-duplicated version store of every section across 18 annual editions, 41 exact-date snapshots and the current text (`cfr_section_versions.jsonl`); amendment history as CSV; the Mine Act (30 U.S.C. ch. 22) as a PDF; 69 Federal Register rule PDFs with descriptive names (correction merged into its rule, one byte-identical copy dropped) and an index of 173 final and 227 proposed rules.
- **Policy and guidance:** Program Policy Manual Volumes I-V in one PDF (HTML copies of Volumes I and II excluded because the PDFs already contain them), the investigation handbook PH20-I-4, Part 50 report, Form 7000-1, FY2025 At a Glance, silica rule overview + fact sheet + PSA; BLS fatality statistics (2 PDFs + 12 CSV sheets).
- **Structured data:** the five core MSHA data sets and the 107(a) orders were extracted from their ZIP archives and written as Parquet (all columns as text; whitespace trimmed; the placeholders '?' and 'No Value Found' and empty values set to null; no rows removed). Row counts match the source files and the project README. A fatal-accident extract with mine attributes (`accidents_fatal_2000-2026.csv`) and a combined data dictionary (PDF + CSV) were added.

## 3. Final folder structure

```text
KGP-SafeMine-Data/
  DATA_GUIDE_AND_RAG_BUILD.md/    1 files, 0.0 MB
  README.md/    1 files, 0.0 MB
  fatality_investigations/    656 files, 71.9 MB
  major_disaster_investigations/    10 files, 349.9 MB
  policy_and_guidance/    6 files, 7.8 MB
  reference_statistics/    14 files, 1.3 MB
  regulations/    115 files, 52.8 MB
  structured_data/    10 files, 184.9 MB
```

| Folder | Content |
|---|---|
| `fatality_investigations/<year>/` | one PDF per MSHA fatality event 2008-2026 (event summary, final report, alert); `events_index.csv` lists all 665 events with metadata and flags |
| `major_disaster_investigations/` | merged investigation and review PDFs for Sago, Aracoma, Darby, Jim Walter No. 5, Crandall Canyon, Quecreek and Upper Big Branch |
| `regulations/cfr_current/` | 30 CFR Chapter I parts, current text (eCFR 2026-10-30) |
| `regulations/cfr_history/` | `cfr_section_versions.jsonl` (distinct versions per section, with first/last edition seen) and `cfr_amendment_history.csv` |
| `regulations/mine_act/`, `regulations/federal_register/` | Mine Act; Federal Register rules + `federal_register_rules_index.csv` |
| `policy_and_guidance/` | Policy Manual, investigation handbook, Part 50 report, Form 7000-1, At a Glance, silica overview |
| `reference_statistics/bls_cfoi/` | BLS fatality statistics (national context) |
| `structured_data/` | Parquet data sets, fatal accident extract, data dictionary, field definitions |
| `processing_reports/` | this report, `source_disposition.csv` (all source files), `excluded_files.csv`, `output_manifest.csv` (hashes, pages, rows), `knowledge_gaps.csv` |

## 4. Excluded files and why

4,640 source files were excluded. Every one is listed with its reason in `excluded_files.csv`; the groups are:

| Reason group | Files |
|---|---|
| Optional pre-2008 layer (not processed) | 1,864 |
| Duplicate or redundant content | 1,792 |
| Boilerplate or metadata-only pages | 411 |
| Personal-data lists / privacy | 364 |
| Unreadable by text extraction (scanned; OCR not available) | 68 |
| Navigation, landing pages and provenance lists | 48 |
| Software assets (models), not documents | 42 |
| Out of scope or low-value for retrieval | 39 |
| Project/method references (not mining-safety knowledge) | 12 |

Detail (distinct reasons):

| Group | Reason | Files |
|---|---|---|
| Boilerplate or metadata-only pages | boilerplate public notice (<=# chars) with investigator name and phone number | 338 |
| Boilerplate or metadata-only pages | unrecognised page type | 63 |
| Boilerplate or metadata-only pages | event page has no narrative (# chars, metadata only); event kept in events_index.csv | 10 |
| Duplicate or redundant content | duplicate content: only # of text is not already in the HTML pages | 1,238 |
| Duplicate or redundant content | short preliminary summary; same text is on the event page (kept there) | 519 |
| Duplicate or redundant content | exact duplicate of chapter#_all_parts/part_#_#-#-#xml | 14 |
| Duplicate or redundant content | Spanish translation of the English fatality alert | 3 |
| Duplicate or redundant content | duplicate of the top-level definition file for the same data set (identical or equivalent content) | 3 |
| Duplicate or redundant content | final report PDF of an event whose full text is already in the cleaned event dossier (and, for two of them, byte-identical to a copy in the  | 3 |
| Duplicate or redundant content | exact duplicate of ftl#m#pdf | 2 |
| Duplicate or redundant content | HTML copy of Volume I: # of its text is already in the PDF volume | 1 |
| Duplicate or redundant content | HTML copy of Volume II: # of its text is already in the PDF volume | 1 |
| Duplicate or redundant content | Spanish translation of the English PSA | 1 |
| Duplicate or redundant content | Spanish translation of the English fact sheet | 1 |
| Duplicate or redundant content | earlier/shorter version of the same final-report summary (text overlap with the kept version #) | 1 |
| Duplicate or redundant content | exact duplicate of appendixu#pdf (Appendix U-#) | 1 |
| Duplicate or redundant content | exact duplicate of fab#m#pdf | 1 |
| Duplicate or redundant content | pre-publication copy of Federal Register document #-#; # of its text matches the published copy kept in regulations/federal_register | 1 |
| Duplicate or redundant content | same Federal Register document #-# as rules_pdf/#-#-# (# of its text matches); kept once under regulations/federal_register | 1 |
| Duplicate or redundant content | table-of-contents page of the same chapter (Cornell LII); the full statute text is in the USC XML | 1 |
| Navigation, landing pages and provenance lists | search-result listing page (navigation); event metadata is taken from the event pages into events_index.csv | 24 |
| Navigation, landing pages and provenance lists | provenance record (URL list, download manifest, checksums): superseded by the processing manifest, which also records each source URL | 11 |
| Navigation, landing pages and provenance lists | navigation/metadata only (title tree or snapshot date); snapshot date is recorded in the processing report | 3 |
| Navigation, landing pages and provenance lists | navigation index of #-# fatal alerts (links only); pre-# layer not included | 2 |
| Navigation, landing pages and provenance lists | JavaScript application shell with no content (# characters) | 1 |
| Navigation, landing pages and provenance lists | JavaScript shell (# characters); the FY# At a Glance PDF is included instead | 1 |
| Navigation, landing pages and provenance lists | catalog listing of the Accidents data set (publisher, dates); the dataset description is kept from msha.gov | 1 |
| Navigation, landing pages and provenance lists | landing page (breadcrumbs and links to the BLS tables that are included as xlsx/CSV) | 1 |
| Navigation, landing pages and provenance lists | landing page for NIOSH charts; interactive data not downloadable here (listed as a gap) | 1 |
| Navigation, landing pages and provenance lists | landing page for interactive NIOSH charts; no downloadable data (listed as a gap) | 1 |
| Navigation, landing pages and provenance lists | list of report URLs (provenance); superseded by the processing manifest | 1 |
| Navigation, landing pages and provenance lists | navigation shell only (menus, search options); no article content | 1 |
| Optional pre-2008 layer (not processed) | optional #-# archive: different report format, no consistent root-cause/enforcement sections, # of # pages name victims in a form this clean | 1,864 |
| Out of scope or low-value for retrieval | dictionary of an excluded data set | 20 |
| Out of scope or low-value for retrieval | ZIP extracted and inspected (rows counted); out of scope for incident-investigation retrieval (health sampling, production, ownership or pen | 14 |
| Out of scope or low-value for retrieval | raw belt examination logbook (handwritten log entries, low retrieval value) | 2 |
| Out of scope or low-value for retrieval | handwritten rock-dust crew notebook scans (no usable text, # chars in # pages) | 1 |
| Out of scope or low-value for retrieval | internal procedure for copying photographs (not mine-safety content) | 1 |
| Out of scope or low-value for retrieval | one-page announcement in the Navajo language; not usable by an English retrieval index and no unique safety content | 1 |
| Personal-data lists / privacy | preliminary-report form: fields already on the event page; form lists the victim's full name (privacy) | 359 |
| Personal-data lists / privacy | list of deceased and injured miners (personal names only) | 1 |
| Personal-data lists / privacy | list of personnel assisting the investigation (names only) | 1 |
| Personal-data lists / privacy | list of personnel who exercised Fifth Amendment rights (names only) | 1 |
| Personal-data lists / privacy | list of the operator's corporate structure and employees (names only) | 1 |
| Personal-data lists / privacy | mine rescue personnel and teams responding (names only) | 1 |
| Project/method references (not mining-safety knowledge) | AI-security reference (# characters of content) | 1 |
| Project/method references (not mining-safety knowledge) | AI-security reference for the prompt-injection tests: project methodology | 1 |
| Project/method references (not mining-safety knowledge) | AI-security reference for the prompt-injection tests: project methodology, not domain knowledge | 1 |
| Project/method references (not mining-safety knowledge) | abstract page of a research paper (related work), not mining-safety knowledge | 1 |
| Project/method references (not mining-safety knowledge) | description of the source folder; its findings are reflected in the processing report | 1 |
| Project/method references (not mining-safety knowledge) | evaluation-method paper (ALCE) abstract page: project methodology reference, not mining-safety knowledge | 1 |
| Project/method references (not mining-safety knowledge) | evaluation-method paper (ALCE): project methodology reference, not mining-safety knowledge | 1 |
| Project/method references (not mining-safety knowledge) | evaluation-method paper (LLM-as-a-judge) abstract page: project methodology reference | 1 |
| Project/method references (not mining-safety knowledge) | evaluation-method paper (LLM-as-a-judge): project methodology reference | 1 |
| Project/method references (not mining-safety knowledge) | evaluation-method paper (RAGAS) abstract page: project methodology reference | 1 |
| Project/method references (not mining-safety knowledge) | evaluation-method paper (RAGAS): project methodology reference | 1 |
| Project/method references (not mining-safety knowledge) | licence/public-domain statement: project compliance note, recorded in the processing report; not knowledge content | 1 |
| Software assets (models), not documents | local embedding/reranker model files (weights, tokenizer, config): software assets, not documents for the knowledge base | 42 |
| Unreadable by text extraction (scanned; OCR not available) | no text layer (scanned images): OCR needed; HTML final report exists so content is probably covered | 63 |
| Unreadable by text extraction (scanned; OCR not available) | no text layer (scanned images): OCR needed | 5 |

## 5. Data quality checks

- Disposition recorded for **6,887 of 6,887** source files (unaccounted: 0).
- Section-presence check (Root Cause Analysis, Conclusion, Enforcement Actions present in the source report and in its PDF): **0** sections lost across 604 final reports.
- **813** output files; unreadable: **0**; PDFs with low text density: 0.
- The 100-item benchmark's gold quotes (verified earlier against the original text) were searched in the cleaned PDFs: **83** found, **0** missing, 17 not checkable (policy items without a source quote).
- Source folder after processing: 6,887 files; files changed or added since the initial inventory: **0**.
- Parquet row counts equal the source line counts (see section 6).

## 6. Structured data check

| Data set | Rows | Columns | Placeholders set to null | Parquet MB | Matches source |
|---|---|---|---|---|---|
| Accidents | 275,673 | 57 | 2,234,999 | 35.1 | True |
| Mines | 92,101 | 59 | 1,691,017 | 6.8 | True |
| Violations | 3,110,622 | 61 | 40,477,100 | 103.3 | True |
| Inspections | 1,164,046 | 45 | 2,218,608 | 33.8 | True |
| MinesProdYearly | 658,945 | 11 | 72,213 | 4.4 | True |
| OrdersIssued | 3,880 | 13 | 7,766 | 0.2 | True |

## 7. Missing data, gaps and recommendations

| Gap | Evidence | Impact | Recommendation |
|---|---|---|---|
| Fatality events without a final report | 61 of 665 events have no published final report in the source snapshot (28 are from 2025-2026); their dossiers contain only preliminary information and the alert | High for root-cause questions on recent events; keep them out of gold root-cause items | Re-collect after MSHA publishes more final reports |
| Event pages with no narrative | 10 events have only metadata (no description) and were not turned into PDFs: 2009/fatality-17-march-19-2009-0, 2009/fatality-14-august-27-2009, 2010/fatality-3-march-22-2010, 2012/fatality-15-october-10-2012, 2013/fatality-20-december-6-2013, 2018/fatality-8-august-8-2018, 2022/september-9-2022-fatatlity, 2025/october-16-2025-fatalty, 2026/october-22-2026-fatality, 2026/october-23-2026-fatality | Low | Check the MSHA site for later updates |
| Scanned PDFs without a text layer (OCR needed) | 68 source PDFs have no text layer: 63 belong to events whose HTML final report exists (content probably covered), the rest have no text alternative. Quecreek has 25 of 133 pages without text; UBB appendices B, H, L, P, Z are scans | Medium | Install Tesseract/OCRmyPDF and run OCR on the listed files (see excluded_files.csv, reason 'no text layer') |
| Optional 1995-2007 fatality archive not processed | 1,864 files (1995-2007 reports, alerts and year indexes) were left out: different format, no consistent root-cause sections, many name victims | Medium for breadth of similar-incident search | Process with the same pipeline after adding a stronger redaction (named-entity) step |
| Redaction is pattern-based | The deceased miner's name and staff names introduced with a job title are replaced; co-workers or witnesses named without a title can remain. 0 detected victim-name leaks in 655 dossiers | High before any public release or demo | Add a named-entity redaction pass (for example spaCy or Presidio) during chunking; keep the original text out of logs and traces |
| Sketches, photographs and maps are not included | Report appendices of maps/sketches/photos are images (and may be third-party); they were dropped, so statements such as 'see Appendix C' point to content that is not available | Medium for location/layout questions | If needed, add image captions manually or use the original PDFs under the source licence rules |
| Program Policy Manual is not the latest | Volume III in the dataset is the April 2006 release and Volume V June 2015; MSHA's site says Volume III was updated 26 Apr 2024 | Medium for policy interpretation questions | Download the current volumes |
| Law before 2017 and for some parts | Exact-date snapshots exist only for Parts 50, 56, 57, 75, 77 from 2017; earlier years only as July-1 annual editions (2008-2025); no 2026 annual edition; Parts 46/47/48/62 have no exact-date snapshots | Medium for 'law at incident date' questions | State 'version unverified' where no edition matches; refresh when 2026 edition is published |
| Federal Register proposed rules have no full text | 227 proposed rules are in the index (title, abstract, CFR references) but only final rules have PDFs | Low | Fetch PDFs for specific proposed rules if needed |
| Upper Big Branch main report body | The dataset holds the 40-page final-report summary, the executive summary and appendices but not the full chapter-by-chapter report body | Medium for UBB detail questions | Obtain the full report from MSHA |
| NIOSH and FMSHRC sources | NIOSH mining charts are interactive (no downloadable data) and FMSHRC decisions were blocked when collected; neither is in the dataset | Low to medium (contested citations, statistics cross-checks) | Add if the project needs penalty-contest or statistics context |
| Excluded MSHA data sets | 15 further MSHA data sets (health samples, production, penalties, ownership) were not converted; one (107(a) orders) was kept; DustData-1986-2016.zip was advertised by MSHA but returned HTTP 404 and was never collected | Low for the planned tools | Convert on demand; they remain in the source folder |

## 8. Assumptions

- 'Source' means `Capstone Project/KGP-SafeMine/KGP-SafeMine_Data`; the new folder is created next to `KGP-SafeMine`, as requested.
- A PDF in the fatality folder is treated as a duplicate when less than 15% (or fewer than 400 characters) of its text is absent from the HTML pages of the same event.
- Relevance is judged for an incident-investigation and regulatory-intelligence knowledge base: AI-method papers, security cheat sheets, model weights and navigation pages are not domain knowledge.
- Nothing was created to fill gaps; OCR could not be run because no OCR engine is installed.