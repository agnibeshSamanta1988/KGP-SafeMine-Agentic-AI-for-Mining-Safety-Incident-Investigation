# KGP-SafeMine-Data: data description and RAG build guide

Applies to `Capstone Project/KGP-SafeMine-Data/` as built on 15 Nov 2026 (source snapshot: MSHA files dated 30 Oct 2026, eCFR as of 2026-10-30). Everything below was checked against the files: counts are computed, and the code in section 7 was run on this data.

**Status tags used:** **[C]** confirmed in the data or a project document · **[P]** proposed in the Build Plan or architecture diagram, not yet built · **[?]** pending decision.

---

## 1. What this dataset is

A cleaned, de-duplicated, partly redacted knowledge base about US mining safety (MSHA). It feeds the three offline pipelines in your architecture diagram (Phase 1: A reports, B structured data, C regulations) and the four tools of Phase 4 (`hybrid_search`, `accident_stats`, `cfr_lookup`, `verify_claims`). It is **data only**: there are no chunk store, indexes or embeddings in it yet; you build those in Phase 1.

| Item | Value |
|---|---|
| Fatality events with a PDF dossier | 655 (2008-2026); 604 with a final report |
| Estimated text size | ~12,855,679 characters (about 3.0 million tokens at 4 characters per token, an estimate) |
| Estimated chunks at 450 tokens / 50 overlap | ~10,570 (6,063 sections; estimate from the tested chunker; Build Plan expected 8,600-13,400) |
| Law store | 2,534 CFR sections, 3,337 distinct versions, 377 sections with more than one version |
| Structured tables | Accidents 275,673 · Mines 92,101 · Violations 3,110,622 · Inspections 1,164,046 · MinesProdYearly 658,945 · 107(a) orders 3,880 |
| Total files / size | 813 files, 0.67 GB |

## 2. Folder map

```text
KGP-SafeMine-Data/
  DATA_GUIDE_AND_RAG_BUILD.md/   1 files, 0.0 MB
  README.md/   1 files, 0.0 MB
  fatality_investigations/   656 files, 71.9 MB
  major_disaster_investigations/   10 files, 349.9 MB
  policy_and_guidance/   6 files, 7.8 MB
  reference_statistics/   14 files, 1.3 MB
  regulations/   115 files, 52.8 MB
  structured_data/   10 files, 184.9 MB
  README.md   short overview
  DATA_GUIDE_AND_RAG_BUILD.md   this file
```

| Folder | Content | Feeds |
|---|---|---|
| `fatality_investigations/<year>/` | one PDF per fatality event + `events_index.csv` | Phase 1A, `hybrid_search`, `verify_claims` |
| `major_disaster_investigations/` | 10 long investigation / review PDFs | optional long-form corpus |
| `regulations/cfr_current/` | 42 Parts of 30 CFR Chapter I, current text | reading, optional dense index |
| `regulations/cfr_history/` | version store (JSONL) + amendment history (CSV) | Phase 1C, `cfr_lookup` |
| `regulations/mine_act/`, `regulations/federal_register/` | Mine Act; 69 rule PDFs + index of 173 final and 227 proposed rules | `cfr_lookup` (rule status) |
| `policy_and_guidance/` | Policy Manual, handbook PH20-I-4, Part 50 report, Form 7000-1, silica overview, At a Glance | interpretation questions, output template |
| `reference_statistics/bls_cfoi/` | BLS national fatality tables (2 PDFs + 12 CSV) | context and cross-checks |
| `structured_data/` | 6 Parquet tables, fatal-accident CSV, data dictionary (PDF + CSV) | Phase 1B, `accident_stats` |
| `processing_reports/` | processing report, per-file disposition, output manifest with SHA-256, knowledge gaps | audit, versioned releases |

---

## 3. Fatality investigations (`fatality_investigations/`)

### 3.1 One PDF per event

Each PDF merges, in this order: **(1)** the MSHA event page (metadata and the preliminary summary), **(2)** the cleaned final investigation report, **(3)** the fatality alert (MSHA 'best practices'), and **(4)** a supplementary section only when a source PDF held content the HTML lacked (88 events). Files are named `YYYY-MM-DD_<mine>_<state>_<classification>.pdf` inside `<year>/`.

The first page is a metadata table: **Event ID (source folder)**, Incident date, Classification, Location, Mine controller, Mine type, Mined material, Incident date/time, **Report status**, Contents, Source URL and a Privacy note. The **Event ID is the document id** (for example `2024/may-9-2024-fatality`): it is what your benchmark's evidence IDs use. PDF bookmarks mirror the structure (`1. Event summary`, `2. Final investigation report` with one bookmark per section, `3. Fatality alert`).

### 3.2 Final-report sections (the evidence-id suffixes)

`OVERVIEW`, `GENERAL INFORMATION`, `DESCRIPTION OF THE ACCIDENT`, `INVESTIGATION OF THE ACCIDENT`, `DISCUSSION`, `ROOT CAUSE ANALYSIS`, `CONCLUSION`, `ENFORCEMENT ACTIONS`. Root Cause Analysis holds numbered *Root Cause:* / *Corrective Action:* pairs; Enforcement Actions lists orders and citations with the 30 CFR standard cited. **Heading spellings vary** (for example 'Description Of The Accident' in 320 PDFs and 'Description Of Accident' in 235; a few upper-case variants), so normalise names (the helper in section 7 does).

### 3.3 `events_index.csv`

One row per event record (**665**; the source has 666 folders because `2024/april-13-2024` holds the final report of the Morgan County Quarry event and was merged into `2024/april-13-2024-fatality`). Several fatalities on one date have separate records with suffixes `-0`, `-1` and often near-identical preliminary text. Columns: `output_pdf`, `event_id`, `year`, `incident_date`, `classification`, `mine`, `state`, `mine_type`, `mined_material`, `has_final_report`, `has_fatality_alert`, `supplementary_pdfs`, `victim_names_redacted`, `pages`, `narrative_chars`, `pdf_dossier`. `pdf_dossier` is False for 10 events whose page has no narrative (no PDF was made); `output_pdf` is the path relative to the dataset root; `victim_names_redacted` counts redacted name variants. Mine ID, controller and accident link are **not** columns (see the gaps list in section 6).

Dossiers per year (and how many have a final report):

| year | dossiers | final |
|---|---|---|
| 2008 | 53 | 52 |
| 2009 | 35 | 35 |
| 2010 | 42 | 41 |
| 2011 | 38 | 35 |
| 2012 | 36 | 36 |
| 2013 | 41 | 41 |
| 2014 | 44 | 43 |
| 2015 | 29 | 29 |
| 2016 | 25 | 23 |
| 2017 | 27 | 27 |
| 2018 | 28 | 28 |
| 2019 | 28 | 26 |
| 2020 | 30 | 26 |
| 2021 | 37 | 36 |
| 2022 | 31 | 28 |
| 2023 | 41 | 36 |
| 2024 | 28 | 25 |
| 2025 | 34 | 27 |
| 2026 | 28 | 10 |

Top classifications: Powered Haulage 205; Machinery 148; Slip or Fall of Person 62; Falling, Rolling, or Sliding Rock or Material of Any Kind 50; Fall of Face, Rib, Side or Highwall 43; Fall of Roof or Back 37; Electrical 29; Other 19.  Sector split: Surface 339; Underground 233; Facility 71; Surface of Underground 8; nan 4.  States: 84 distinct.

### 3.4 What was removed or changed (so you can explain it)

- Removed: navigation, scripts, images, appendices (people lists and image-only maps), the investigator block and approval signatures, public notices (boilerplate with phone numbers), and the separate preliminary-report pages (their text is on the event page).
- The deceased miner's name is replaced by **`the miner`**; staff or co-workers introduced with a job title by **`[name withheld]`**; individual owners listed as mine controller by `[name withheld] (individual owner/operator)`. This is pattern-based. Co-workers named without a title can remain. Never try to infer or restore names.
- The fatality folder holds 1,820 source PDFs: 62 belong to the Upper Big Branch package (section 4.1) and, of the other 1,758, 1,666 were not used (duplicates of the HTML, Spanish translations, scans without text, and preliminary-report forms, which print the victim's full name) while 92 contributed the supplementary sections.

### 3.5 Things that matter for retrieval

- **61 events have no final report** (28 from 2025-2026). Their text is preliminary only: tag them (`has_final_report=False`) and keep them out of root-cause questions.
- Text in the *Event summary* section is **preliminary** and may differ from the final report; the *Fatality alert* gives MSHA's recommended practices, not findings.
- Every page repeats a footer line (`<mine> | <date> | MSHA fatality investigation record` and `Page N`) and the first page has boilerplate rows (Contents, Privacy note): strip them before chunking (the helper does).
- Only 407 of 655 dossiers print a mine ID.

---

## 4. Other collections

### 4.1 Major disaster investigations

| file | pages | MB |
|---|---|---|
| 00_MSHA_Mine_Disaster_Investigations_Overview.pdf | 1.0 | 0.1 |
| Aracoma_Alma_Mine_No1_2006_Investigation_and_Review.pdf | 397.0 | 23.4 |
| Crandall_Canyon_Mine_2007_Investigation_and_Review.pdf | 723.0 | 43.8 |
| Darby_Mine_No1_2006_Investigation_and_Review.pdf | 278.0 | 3.1 |
| Jim_Walter_Resources_No5_Mine_2001_Investigation_and_Review.pdf | 253.0 | 11.9 |
| Quecreek_Mine_2002_Accident_Investigation_Report.pdf | 133.0 | 7.4 |
| Sago_Mine_2006_Investigation_and_Review.pdf | 816.0 | 53.6 |
| Upper_Big_Branch_Mine_2010_Accident_Investigation_Summary_and_Appendices.pdf | 1973.0 | 141.1 |
| Upper_Big_Branch_Mine_2010_Reviews_Assessments_and_Corrective_Actions.pdf | 486.0 | 21.8 |
| Upper_Big_Branch_Mine_2010_Technical_Investigation_Methane_and_Multi-Gas_Detectors.pdf | 1097.0 | 43.7 |

Each Sago/Aracoma/Darby/Jim Walter/Crandall file contains the accident investigation report followed by MSHA's internal or independent review, with one bookmark per part. These are long documents: chunk by page ranges or headings and tag them `source_type=major_disaster`. Some victim names appear (historic public reports; not redacted).

### 4.2 Regulations

- `cfr_current/30-CFR-Part-NNN_<title>_eCFR-2026-10-30.pdf`: 42 Parts, 822 pages, bookmarks per subpart and section.
- `cfr_history/cfr_section_versions.jsonl`: one line per *distinct text* of a section. Fields: `section`, `cfr_citation`, `heading`, `version_no`, `n_versions`, `seen_in`, `first_seen`, `last_seen`, `is_current`, `text`. `seen_in` lists labels `annual-YYYY` (official annual edition, a **1 July** snapshot) and `ecfr-YYYY-MM-DD` (exact amendment-date snapshot, available only for Parts 50, 56, 57, 75, 77 from 2017). Identical text across editions is stored once.
- `cfr_history/cfr_amendment_history.csv`: 2,625 rows (`part`, `section`, `heading`, `amendment_date`, `issue_date`, `substantive`, `removed`, `subpart`, `type`).
- `mine_act/`: 30 U.S.C. chapter 22 (89 sections) as one PDF.
- `federal_register/`: 69 final-rule PDFs named `date_docnumber_title.pdf` (one correction merged into its rule) and `federal_register_rules_index.csv` (227 proposed + 173 final entries; publication dates 1994-11-02 to 2026-10-16). Columns: `kind`, `document_number`, `publication_date`, `effective_on`, `type`, `title`, `action`, `citation`, `cfr_references`, `abstract`, `html_url`, `pdf_available_in_dataset`, `pdf_file`. **`effective_on` alone does not show a stay**: for the silica notice 2026-06584 it reads 2024-04-18 while the notice delays those amendments indefinitely; read `abstract` and `action` too.

### 4.3 Policy and guidance, statistics

| file | pages |
|---|---|
| MSHA_Accident_Investigation_Procedures_Handbook_PH20-I-4.pdf | 75.0 |
| MSHA_Form_7000-1_Mine_Accident_Injury_and_Illness_Report.pdf | 5.0 |
| MSHA_FY2025_At_a_Glance_Fatality_and_Injury_Statistics.pdf | 2.0 |
| MSHA_Program_Policy_Manual_Volumes_I-V.pdf | 506.0 |
| MSHA_Report_on_30_CFR_Part_50_Accident_Reporting.pdf | 52.0 |
| MSHA_Silica_Final_Rule_2024_Overview_Fact_Sheet_and_PSA.pdf | 4.0 |

The Policy Manual copy is **not current** (Volume III is the April 2006 release; MSHA's site notes an update on 26 Apr 2024). BLS tables in `reference_statistics/bls_cfoi/` are all-industry national statistics: use only for context, not for mining rates.

---

## 5. Structured data (`structured_data/`)

Parquet (zstd), **every column stored as text exactly as published**; whitespace trimmed; the placeholders `?`, `No Value Found` and empty strings are null. No rows were removed. Dates are `MM/DD/YYYY` text; numbers must be cast.

| Table | Rows | Columns | Key and join notes |
|---|---|---|---|
| Accidents | 275,673 | 57 | `DOCUMENT_NO` unique; join to Mines on `MINE_ID`; `DEGREE_INJURY_CD='01'` = fatal (1,218 rows); `ACCIDENT_DT`, `CAL_YR`, `CLASSIFICATION`, `ACCIDENT_TYPE`, `MINING_EQUIP`, `NARRATIVE` |
| Mines | 92,101 | 59 | `MINE_ID` unique; `CURRENT_MINE_NAME`, `COAL_METAL_IND`, `CURRENT_MINE_TYPE`, `STATE`, `FIPS_CNTY_NM` |
| Violations | 3,110,622 | 61 | `VIOLATION_NO` is **not** unique (51 repeats; same for the pair `EVENT_NO`+`VIOLATION_NO`); join on `MINE_ID` and `EVENT_NO`; `PART_SECTION` = standard cited |
| Inspections | 1,164,046 | 45 | `EVENT_NO` has 1 repeat; join on `MINE_ID` |
| MinesProdYearly | 658,945 | 11 | columns are `CALENDAR_YR`, `ANNUAL_HRS`, `C_M_IND`, `SUBUNIT_CD` (your diagram says `CAL_YR`); use for hours-based rates |
| OrdersIssued | 3,880 | 13 | 107(a) imminent-danger orders; headers are free text (`Mine ID`, `Violation No.`) |

`accidents_fatal_2000-2026.csv` is a derived convenience file: the 1,218 fatal rows with mine name, type, state and county added (62 columns; narratives up to 384 characters; two coal/metal columns, `COAL_METAL_IND` and `COAL_METAL_IND_mine`). `data_dictionary.csv` and the PDF of the same name describe every column. **Do not load Violations into pandas in full**: read only the columns you need (`pd.read_parquet(path, columns=[...])`) or query with DuckDB.

---

## 6. Checks that were run, and what is not covered

- All 6,887 source files have a recorded outcome (`processing_reports/source_disposition.csv`); the source folder was re-hashed after processing: **0** changes.
- 813 outputs open; no section of Root Cause Analysis, Conclusion or Enforcement Actions was lost between the source reports and the PDFs (0 losses).
- A scan of 655 dossiers found 0 detected victim names.
- The benchmark's 83 checkable gold quotes are found in the cleaned PDFs, and the section splitter in section 7 resolves all 64 `doc#SECTION` gold evidence IDs to the right section.
- 214 of the 215 standards cited in the reports exist in the version store (`47.7` does not; not investigated).

### Not in the data (gaps that affect the build)

1. **No embedding or reranker model.** `bge-small-en-v1.5` and `ms-marco-MiniLM-L6-v2` are in the original `05_models` folder, not here. Whether the hosted endpoint offers embeddings or a reranker is unconfirmed [?].
2. **No event-to-accident link table.** Tested join: 406 events match by mine ID + date (+-1 day), 168 by a unique date, 81 do not match. The helper in section 7 builds it.
3. **No OCR:** 68 scanned source PDFs were excluded (63 belong to events whose HTML report exists).
4. **Pre-2008 archive (1,864 files) not processed.**
5. **Prompt-injection and refusal test documents** must be written by the team.
6. **No NER-based redaction**; add one before any public demo.

---

## 7. Reference code (tested)

These helpers were run against this folder. Requirements: `pandas`, `pymupdf`, `pyarrow`.

```python
"""Reference helpers used in the data guide (tested against KGP-SafeMine-Data)."""
import re, json
from pathlib import Path
import pandas as pd
import pymupdf

DATA = Path("KGP-SafeMine-Data")          # change to where the folder lives

# ---- 1. split a dossier PDF into evidence sections ---------------------------------
ALIAS = {"DESCRIPTION OF ACCIDENT": "DESCRIPTION OF THE ACCIDENT", "INVESTIGATION OF ACCIDENT": "INVESTIGATION OF THE ACCIDENT", "ENFORCEMENT ACTION": "ENFORCEMENT ACTIONS"}
REPORT_HEADS = ["OVERVIEW", "GENERAL INFORMATION", "DESCRIPTION OF THE ACCIDENT", "INVESTIGATION OF THE ACCIDENT", "DISCUSSION", "ROOT CAUSE ANALYSIS", "CONCLUSION", "ENFORCEMENT ACTIONS"]
PART_HEADS = {"EVENT SUMMARY (MSHA EVENT PAGE)": "EVENT_SUMMARY", "FINAL INVESTIGATION REPORT": "FINAL_REPORT", "FATALITY ALERT": "ALERT"}
FOOTER = re.compile(r"^(?:.+ \| \d{4}-\d{2}-\d{2} \| MSHA fatality investigation record|Page \d+)$")


def dossier_text(pdf):
    d = pymupdf.open(pdf)
    lines = []
    for pg in d:
        lines += [l.strip() for l in pg.get_text().splitlines()]
    d.close()
    return [l for l in lines if l and not FOOTER.match(l)]


def split_sections(pdf):
    """-> {'EVENT_SUMMARY': text, 'ROOT CAUSE ANALYSIS': text, ..., 'ALERT': text}. Keys are the evidence-id suffixes."""
    out, cur, part = {}, "FRONT", None
    for l in dossier_text(pdf):
        key = re.sub(r"^\d+\.\s*", "", l).upper()
        if key in PART_HEADS:
            part = PART_HEADS[key]
            cur = part if part != "FINAL_REPORT" else "REPORT_HEADER"
            out.setdefault(cur, [])
            continue
        if part == "FINAL_REPORT" and ALIAS.get(l.upper(), l.upper()) in REPORT_HEADS:
            cur = ALIAS.get(l.upper(), l.upper())
            out.setdefault(cur, [])
            continue
        if re.match(r"^\d+\.\s*Supplementary document", l):
            part, cur = "SUPPLEMENT", "SUPPLEMENT"
            out.setdefault(cur, [])
            continue
        out.setdefault(cur, []).append(l)
    return {k: " ".join(v) for k, v in out.items() if k != "FRONT"}


# ---- 2. sentence-aware chunker (~450 tokens, 50 overlap; 1 token ~ 4 characters) ---------
def chunk(text, max_tok=450, overlap_tok=50):
    sents = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\"\u201c])", text)
    max_c, ov_c, chunks, cur = max_tok * 4, overlap_tok * 4, [], ""
    for s in sents:
        if cur and len(cur) + len(s) + 1 > max_c:
            chunks.append(cur)
            cur = cur[-ov_c:].split(" ", 1)[-1] + " " + s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        chunks.append(cur)
    return chunks


# ---- 3. law at an incident date ------------------------------------------------------------
def label_date(label):
    kind, rest = label.split("-", 1)
    return pd.Timestamp(rest + "-07-01") if kind == "annual" else pd.Timestamp(rest)


_VERS = None
def cfr_as_of(section, date):
    """Version of 30 CFR <section> in force on <date>: latest edition/snapshot dated on or before it."""
    global _VERS
    if _VERS is None:
        _VERS = {}
        for l in open(DATA / "regulations/cfr_history/cfr_section_versions.jsonl", encoding="utf-8"):
            r = json.loads(l)
            _VERS.setdefault(r["section"], []).append(r)
    date = pd.Timestamp(date)
    best = None
    for r in _VERS.get(section, []):
        for lab in r["seen_in"]:
            ld = label_date(lab)
            if ld <= date and (best is None or ld > best[0]):
                best = (ld, lab, r)
    if best is None:
        return {"status": "version unverified", "reason": "no edition on or before this date"}
    ld, lab, r = best
    return {"status": "ok", "edition_used": lab, "edition_date": str(ld.date()), "version_no": r["version_no"], "n_versions": r["n_versions"], "heading": r["heading"], "text": r["text"]}


# ---- 4. accident_stats: fatal events per year joined to exposure hours -------------------------
def fatality_rate_by_year(first=2008, last=2025):
    acc = pd.read_parquet(DATA / "structured_data/Accidents.parquet", columns=["MINE_ID", "CAL_YR", "DEGREE_INJURY_CD", "COAL_METAL_IND"])
    fat = acc[acc.DEGREE_INJURY_CD == "01"].groupby(["CAL_YR", "COAL_METAL_IND"]).size().rename("fatalities").reset_index()
    prod = pd.read_parquet(DATA / "structured_data/MinesProdYearly.parquet", columns=["CALENDAR_YR", "C_M_IND", "ANNUAL_HRS"])
    prod["ANNUAL_HRS"] = pd.to_numeric(prod.ANNUAL_HRS, errors="coerce")
    hrs = prod.groupby(["CALENDAR_YR", "C_M_IND"]).ANNUAL_HRS.sum().rename("hours").reset_index()
    out = fat.merge(hrs, left_on=["CAL_YR", "COAL_METAL_IND"], right_on=["CALENDAR_YR", "C_M_IND"], how="left")
    out["rate_per_200k_hours"] = out.fatalities / out.hours * 200000
    out = out[(out.CAL_YR.astype(int) >= first) & (out.CAL_YR.astype(int) <= last)]
    return out[["CAL_YR", "COAL_METAL_IND", "fatalities", "hours", "rate_per_200k_hours"]]


# ---- 5. link events to fatal accident rows ------------------------------------------------------
def link_events_to_accidents():
    idx = pd.read_csv(DATA / "fatality_investigations/events_index.csv")
    idx = idx[idx.pdf_dossier]
    fat = pd.read_csv(DATA / "structured_data/accidents_fatal_2000-2026.csv", dtype=str)
    fat["d"] = pd.to_datetime(fat.ACCIDENT_DT, format="%m/%d/%Y", errors="coerce")
    rows = []
    for _, r in idx.iterrows():
        d = pymupdf.open(DATA / r.output_pdf)
        txt = " ".join(p.get_text() for p in d)
        d.close()
        m = re.search(r"ID\s*No\.?\s*:?\s*(\d{2})-(\d{5})", txt)
        mid = (m.group(1) + m.group(2)) if m else None
        day = pd.Timestamp(r.incident_date)
        near = fat[(fat.d >= day - pd.Timedelta(days=1)) & (fat.d <= day + pd.Timedelta(days=1))]
        hit, how = None, "none"
        if mid and (near.MINE_ID == mid).any():
            hit, how = near[near.MINE_ID == mid].DOCUMENT_NO.tolist(), "mine_id+date"
        elif len(near) == 1:
            hit, how = near.DOCUMENT_NO.tolist(), "date_only_unique"
        rows.append({"event_id": r.event_id, "mine_id": mid, "accident_document_no": ";".join(hit) if hit else "", "link_method": how})
    return pd.DataFrame(rows)
```

Example calls (tested):

```python
idx = pd.read_csv(DATA/'fatality_investigations/events_index.csv')
path = dict(zip(idx.event_id, idx.output_pdf))
sections = split_sections(DATA/path['2024/may-9-2024-fatality'])   # keys: 'ROOT CAUSE ANALYSIS', 'ENFORCEMENT ACTIONS', 'ALERT', ...
chunks = chunk(sections['DISCUSSION'])
cfr_as_of('56.9101', '2012-07-26')         # {'status': 'ok', 'edition_used': 'annual-2012', ...}
cfr_as_of('56.9101', '2002-07-14')         # {'status': 'version unverified', ...}  -> abstain
fatality_rate_by_year(2022, 2024)           # fatalities, hours and rate per 200,000 hours by coal/metal
links = link_events_to_accidents()          # event_id, mine_id, accident_document_no, link_method
```

Equivalent DuckDB SQL for `accident_stats` (**not run here**; DuckDB is not installed in this environment):

```sql
SELECT CAL_YR, CLASSIFICATION, COUNT(*) AS fatalities
FROM 'structured_data/Accidents.parquet'
WHERE DEGREE_INJURY_CD = '01' AND CAL_YR BETWEEN '2018' AND '2024'
GROUP BY 1, 2 ORDER BY 1, 3 DESC;
```

---

## 8. How to build the RAG from this data (your phase order: 1 -> 4 -> 2 -> 3 -> 5)

The architecture diagrams show Amazon Bedrock, OpenSearch Serverless, DynamoDB and ECS. The data layer below is the same whichever stack you choose. Whether Bedrock is allowed for the LLM, given that Track B provides a hosted Qwen3-8B endpoint (8,192-token context, 1-1024 completion tokens), is an open decision [?].

### Phase 1: offline data engineering

**1A. Report pipeline** (diagram boxes: parse, redact, section-aware chunking, canonical chunk store, BM25, vector index)

1. Read `events_index.csv`; keep rows with `pdf_dossier=True`. Treat `event_id` as `doc_id`.
2. For each PDF run `split_sections` (strips footers and the first-page boilerplate, normalises headings). Each key is an evidence-id suffix: `evidence_id = f'{event_id}#{SECTION}'`, for example `2024/may-9-2024-fatality#ROOT CAUSE ANALYSIS`. Skip `REPORT_HEADER` (title lines) or keep it as metadata.
3. Run a second redaction pass (named-entity) **before embedding**, so vectors never encode names; keep the original `[name withheld]` and `the miner` tokens.
4. Sub-chunk: sections over 450 tokens (30% of sections) are split with `chunk()` (sentence boundaries, 450 tokens, 50 overlap). Short sections stay whole. Chunk id: `evidence_id#n`. Compare section-only, 350, 450, 600 and adaptive chunking on the dev items [P, from the Build Plan].
5. Chunk record (suggested): `chunk_id, evidence_id, doc_id, section, year, incident_date, classification, mine_type, mined_material, state, has_final_report, source_type (event_summary | final_report | alert | supplement), text, token_count`. All metadata except `section` and `source_type` comes from `events_index.csv`.
6. Build **BM25** with a tokenizer that keeps standard numbers whole (`56.14105`, `75.202(a)`) [P] and a **dense index** with your chosen embedding model. Retrieval plan from the Build Plan [P]: BM25 top 30 + dense top 30, reciprocal-rank fusion (k = 60), rerank top 20, keep 6-8 chunks with at most 2 per report. At about 450 tokens each, 8 chunks are ~3,600 tokens, which fits the 8,192-token window with room for the prompt and a 1,024-token answer.
7. Optional corpora (tag them separately so they never mix into gold root-cause answers): disaster packages, Policy Manual, handbook PH20-I-4, silica overview.
8. Counting rule: the template caps the corpus at 2,000 documents. Count the 655 dossiers (+ optional ~20 long documents); treat tables, CFR sections and accident rows as tool lookups, not documents [P].

**1B. Structured pipeline** (profile/validate, DuckDB)

1. Query the Parquet files in place (DuckDB or pyarrow); do not load Violations wholesale.
2. Cast on use: `CAST(ACCIDENT_DT AS DATE)` with format `%m/%d/%Y`, numeric hours with `TRY_CAST`. Dates and codes are text.
3. Joins: Accidents-Mines on `MINE_ID`; rates need MinesProdYearly (`MINE_ID`, `CALENDAR_YR`). Do not assume `VIOLATION_NO` or `EVENT_NO` are unique keys.
4. Expose a **fixed menu** (group-by, filters, metrics) rather than free SQL; return rows plus the filter used and the snapshot date (30 Oct 2026). Label counts as *records*, not individuals.
5. Run `link_events_to_accidents()` once and store the result as a table so the agent can combine a report with its accident row.

**1C. Regulatory pipeline** (versioned law store, rule status)

1. Load `cfr_section_versions.jsonl` into a table keyed by `(section, version_no)`; `cfr_as_of(section, date)` implements 'law at incident date' using the latest edition dated on or before the incident. Annual editions are dated 1 July, so an amendment between 1 July and the incident can be missed before 2017: say so in the answer. Return `version unverified` when no edition qualifies (for example any date before 2008) and abstain on questions that depend on it.
2. Join rule status from `federal_register_rules_index.csv` (type, publication date, abstract, `cfr_references`). Tag provisions in force / proposed / stayed from the abstract and action text, not from `effective_on` alone. The silica notice is the worked example: the 2024 rule's conforming amendments to Parts 56/57 are delayed indefinitely pending judicial review.
3. Optional: also index CFR sections as short documents (`CFR:<section>` ids) so `hybrid_search` can find a standard by topic; keep `cfr_lookup` for exact citation.

### Phase 4: online agentic investigation (tools and data)

| Tool | Reads | Return / rules |
|---|---|---|
| `hybrid_search(query, filters, k)` | chunk store, filters from `events_index` | ranked chunks with `evidence_id`; handle empty result, no filter match, timeout |
| `accident_stats(group_by, filters, metric)` | Parquet tables | rows + filter used + snapshot date; reject unknown columns |
| `cfr_lookup(section, as_of)` / search | version store + FR index | text with version label and status, or `version unverified` |
| `verify_claims(draft)` | stored chunk text | per claim: id exists, quote is a verbatim substring (normalise whitespace), numbers/dates/ids match |

Behaviours the data forces: abstain for events after the 30 Oct 2026 snapshot or before 2008, non-US jurisdictions, root causes of non-fatal accidents (only a short narrative exists), and events without a final report; never reveal or guess a victim's name; treat retrieved text as data, not instructions (the planned injection tests need synthetic documents that you write).

### Phase 2: container build and release

Do not bake the 0.67 GB into the image: mount `KGP-SafeMine-Data/` read-only (or pull it from object storage) and build indexes with one script. Record `processing_reports/output_manifest.csv` (SHA-256 per file) in the release notes so any index can be traced to exact inputs.

### Phase 3: AWS infrastructure and deployment

Mirror the folder layout in the data bucket; keep `structured_data/` and the indexes as separate prefixes. The AWS design is not required by the template (it asks for a containerised UI) and no roadmap task covers it yet [?].

### Phase 5: operations, evaluation and governance

- **Retrieval metrics:** your benchmark's `doc#SECTION` evidence IDs map directly to chunks (`evidence_id` prefix match). Compute recall@5/10 and MRR separately from answer quality. For leave-one-out experiments exclude the whole `doc_id`.
- **Splits:** split by incident (`event_id`), never by question.
- **Safety tests:** run a name-leak scan over answers, traces and logs; test refusals and injection with synthetic documents kept out of the real index.
- **Versioning:** a new index release = new manifest hash; keep the previous one for rollback.

---

## 9. Quick checklist

- [ ] Decide LLM and embedding source (Bedrock vs the provided endpoint); copy the two local models if needed
- [ ] Parse and split all dossiers; verify the 64 benchmark evidence IDs resolve
- [ ] Add NER redaction; re-scan for names
- [ ] Chunk, build BM25 and dense indexes; measure recall@k on the 14 dev items first
- [ ] Load Parquet and the version store; build the event-accident link table
- [ ] Implement the four tools with typed inputs and unit tests
- [ ] Keep the benchmark's TEST split untouched until the freeze

---

## 10. Provenance and limits

Original files are in `KGP-SafeMine/KGP-SafeMine_Data` and were not changed. Scripts that rebuilt this folder are in `Capstone Project/data_prep/`. US Government works are generally public domain, but images and some content may belong to others; attribute MSHA and do not imply endorsement. Decision support only: this data does not replace qualified safety professionals or official investigations.
