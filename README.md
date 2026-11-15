# KGP-SafeMine-Data (cleaned dataset for RAG)

Cleaned, de-duplicated, redacted knowledge sources for the KGP-SafeMine project (US mining safety, MSHA). Built from the read-only source folder `KGP-SafeMine/KGP-SafeMine_Data`.

| Folder | What is inside | Suggested use |
|---|---|---|
| `fatality_investigations/` | One PDF per fatality event (2008-2026): event summary, final report, alert. `events_index.csv` = metadata for all events | Primary retrieval corpus; doc id = source folder in the PDF's first table |
| `major_disaster_investigations/` | Sago, Aracoma, Darby, Jim Walter No. 5, Crandall Canyon, Quecreek, Upper Big Branch | Long-form investigation and review documents |
| `regulations/` | 30 CFR (current PDFs, version store, amendment history), Mine Act, Federal Register rules | `cfr_lookup`, regulation questions, rule status |
| `policy_and_guidance/` | Program Policy Manual, PH20-I-4 handbook, Part 50 report, Form 7000-1, silica overview, At a Glance | Interpretation and procedure questions |
| `reference_statistics/` | BLS national fatality statistics | Context and cross-checks |
| `structured_data/` | Accidents, Mines, Violations, Inspections, MinesProdYearly, 107(a) orders (Parquet), fatal accident extract (CSV), data dictionary | `accident_stats` (SQL/DuckDB), not text retrieval |
| `processing_reports/` | Final report, disposition of every source file, output manifest with SHA-256, knowledge gaps | Audit and traceability |

Privacy: the deceased miner's name is replaced by "the miner" and staff names introduced with a job title by "[name withheld]" (pattern-based; see the report for limits). Do not treat the PDFs as fully anonymised.

Licence: US Government works are generally public domain, but images and some content may belong to others; attribute MSHA and do not imply endorsement.

See `DATA_GUIDE_AND_RAG_BUILD.md` for the detailed data description and the step-by-step RAG build guide (tested code included).

## Getting this data from GitHub

Three files are larger than 50 MB and are stored with [Git LFS](https://git-lfs.com) (`.gitattributes` lists them): `structured_data/Violations.parquet`, the Upper Big Branch investigation/appendices PDF and the Sago PDF. Install Git LFS **before** cloning:

```bash
git lfs install
git config --global core.longpaths true     # Windows only: allows paths over 260 characters
git clone https://github.com/agnibeshSamanta1988/KGP-SafeMine-Agentic-AI-for-Mining-Safety-Incident-Investigation.git
cd KGP-SafeMine-Agentic-AI-for-Mining-Safety-Incident-Investigation
git lfs pull        # only needed if the large files show up as small text pointers
```

Checksums in `processing_reports/output_manifest.csv` are for the files exactly as stored; the repository disables line-ending conversion (`* -text`) so they stay valid on Windows, macOS and Linux.
