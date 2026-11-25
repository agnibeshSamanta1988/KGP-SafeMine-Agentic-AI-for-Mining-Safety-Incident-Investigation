"""Step 1 (cleaned team dataset): PDF event dossiers -> cleaned, sectioned, redacted documents (docs.jsonl).

Input: KGP-SafeMine-Data/fatality_investigations/<year>/*.pdf + events_index.csv. Each dossier is
  front page (metadata table) | 1. Event summary (preliminary) | 2. Final investigation report |
  3. Fatality alert | 4. Supplementary document (88 events: text a source PDF had that the HTML lacked)

Output: the same docs.jsonl schema as the old HTML reader (clean_reports.py), so chunk.py, the indexes and the
tools are unchanged. doc_types: final_report, fatality_alert, preliminary_report (only when no final report).

PDF text comes out per block (= paragraph). We drop the per-page footer, split "Sub-heading\\nParagraph" blocks
(DISCUSSION sub-headings), and re-join paragraphs broken by a page break.

Privacy: the dataset already replaces the victim with "the miner" and titled staff with "[name withheld]"
(pattern-based). We run our own name harvester on top (e.g. "Name — Plant Manager" lines survive the first pass)
and store the names in _restricted/names.json for the Output Filter.

Run:  .venv/bin/python -m safemine.ingest.clean_pdfs
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

import pymupdf

from safemine import config
from safemine.ingest.clean_reports import (CFR_RE, FULL_NAME, SIGNATURE, Redactor, _clean_name, canon_heading,
                                           harvest_header_people, harvest_names, parse_header, parse_root_causes,
                                           structure_discussion)

FOOTER = re.compile(r"MSHA fatality investigation record\s*\|?\s*Page \d+\s*$|^Page \d+$")
PART = re.compile(r"^(\d)\.\s+(Event summary|Final investigation report|Fatality alert|Supplementary document)", re.I)
FRONT_KEYS = {"Event ID (source folder)": "event_id", "Incident date": "date_iso", "Classification": "classification",
              "Location": "location_event", "Mine controller": "controller", "Mine type": "mine_type",
              "Mined material": "material", "Incident date/time": "incident_datetime", "Report status": "report_status"}
SENT_END = re.compile(r"[.:;?!\"”’)\]]$")


def _join(lines: list[str]) -> str:
    out = ""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if out.endswith("-") and re.search(r"[a-z]-$", out):   # "year-\nold" -> "year-old"
            out += ln
        else:
            out = f"{out} {ln}" if out else ln
    return re.sub(r"\s+", " ", out).strip()


def _looks_heading(first: str, rest: str) -> bool:
    """First line of a block is a heading when it is short, has no final punctuation, and text follows."""
    return (len(first) <= 70 and not SENT_END.search(first) and len(rest) >= 20
            and first[:1].isupper() and not re.match(r"^\d+\.\s", first))


def pdf_blocks(path: Path) -> list[dict]:
    """-> [{text, lines, heading}] in reading order; footers removed; page-broken paragraphs re-joined."""
    out: list[dict] = []
    with pymupdf.open(path) as d:
        for pg in d:
            page_top = True
            for b in sorted(pg.get_text("blocks"), key=lambda b: (b[1], b[0])):
                if b[6] != 0:  # image block
                    continue
                raw = [ln for ln in b[4].split("\n") if ln.strip()]
                if not raw or FOOTER.search(_join(raw)):
                    continue
                first, rest = raw[0].strip(), _join(raw[1:])
                at_top, page_top = page_top, False
                if len(raw) > 1 and _looks_heading(first, rest) and not PART.match(first) and first not in FRONT_KEYS:
                    out.append({"text": first, "lines": [first], "heading": True})
                    out.append({"text": rest, "lines": raw[1:], "heading": False})
                    continue
                text = _join(raw)
                single = len(raw) == 1 and len(text) <= 70 and not SENT_END.search(text)
                prev = out[-1] if out else None
                # paragraph continued across a page break: previous paragraph has no sentence end
                if (prev and not prev["heading"] and not single and not SENT_END.search(prev["text"])
                        and (text[:1].islower() or at_top)):
                    prev["text"] += " " + text
                    prev["lines"] += raw
                    continue
                out.append({"text": text, "lines": raw, "heading": single})
    return out


def split_dossier(blocks: list[dict]) -> dict:
    """-> {front: {key: value}, summary: [text], report: [block], alert: [text], supplement: [text]}"""
    parts = {"front": {}, "summary": [], "report": [], "alert": [], "supplement": []}
    cur = "front"
    for b in blocks:
        m = PART.match(b["text"])
        if m:
            cur = {"1": "summary", "2": "report", "3": "alert"}.get(m.group(1), "supplement")
            continue
        if cur == "front":
            k = b["lines"][0].strip()
            if k in FRONT_KEYS and len(b["lines"]) > 1:
                parts["front"][FRONT_KEYS[k]] = _join(b["lines"][1:])
            continue
        if cur == "report":
            parts["report"].append(b)
        else:
            parts[cur].append(b["text"])
    return parts


MAIN_TOC = [(r"overview|summary", "OVERVIEW"), (r"general information", "GENERAL_INFORMATION"),
            (r"description of (the )?accident", "DESCRIPTION"), (r"investigation of (the )?accident", "INVESTIGATION"),
            (r"discussion", "DISCUSSION"), (r"root cause analysis", "ROOT_CAUSE"), (r"conclusions?", "CONCLUSION"),
            (r"enforcement actions?", "ENFORCEMENT")]
RC_PARA = re.compile(r"^(\d+\.\s*)?(Root Cause|Corrective Action)s?\s*\d*\s*:", re.I)
ENF_PARA = re.compile(r"^(\d+\.\s*)?(A|An)\s+(10[3-7]|110|314)\s*\([a-z]\)|^(\d+\.\s*)?(Citation|Order|Safeguard)\s+No", re.I)


BARE_CFR = re.compile(r"(?<![\d.])(\d{2,3}\.\d{1,5}[a-z]?(?:-\d+)?)(?=\s*\(|[\s.,:;]|$)")
_KNOWN = None


def known_sections() -> set[str]:
    global _KNOWN
    if _KNOWN is None:
        p = config.REG_DIR / "cfr_history" / "cfr_section_versions.jsonl"
        _KNOWN = {json.loads(l)["section"] for l in open(p)} if p.exists() else set()
    return _KNOWN


def cited_sections(enf_text: str) -> list[str]:
    """30 CFR sections cited in Enforcement Actions; older reports write '77.1605(l)' without '30 CFR'."""
    found = {m.group(1).split("(")[0] for m in CFR_RE.finditer(enf_text)}
    found |= {m.group(1) for m in BARE_CFR.finditer(enf_text) if m.group(1) in known_sections()}
    return sorted(found)


GLUED = re.compile(r"^(ROOT CAUSE ANALYSIS|ROOT CAUSES?|CONCLUSIONS?|ENFORCEMENT ACTIONS?|DISCUSSION|OVERVIEW|"
                   r"GENERAL INFORMATION|DESCRIPTION OF (?:THE )?ACCIDENT|INVESTIGATION OF (?:THE )?ACCIDENT)\s+(?=[A-Z][a-z])")


def _unglue(blocks: list[dict]) -> list[dict]:
    """'ROOT CAUSE ANALYSIS The accident investigation team ...' -> heading block + paragraph block."""
    out = []
    for b in blocks:
        m = GLUED.match(b["text"])
        if m and not b["heading"]:
            out.append({"text": m.group(1), "lines": [m.group(1)], "heading": True})
            rest = b["text"][m.end():]
            out.append({"text": rest, "lines": [rest], "heading": False})
        else:
            out.append(b)
    return out


def toc_section(title: str) -> str | None:
    low = re.sub(r"[:.]$", "", title.strip()).lower()
    for pat, name in MAIN_TOC:
        if re.fullmatch(pat, low):
            return name
    return None


def report_sections(blocks: list[dict], toc_titles: set[str]):
    """Final-report blocks -> (header_lines, {SECTION: [paragraph]}, dropped_lines, used_fallback).

    Section headings come from the PDF bookmarks (exact titles); appendix headings are dropped. 39 older reports
    lost their headings in the conversion: for those, root-cause pairs and citations are found by their wording.
    """
    main = {t for t in toc_titles if toc_section(t)}
    header, secs, dropped, cur, in_sig = [], {}, [], "HEADER", False
    fallback = not main
    for b in _unglue(blocks):
        t = b["text"]
        h = None
        if t in main:
            h = toc_section(t)
        elif len(t) <= 70 and canon_heading(t) == "DROP":
            h = "DROP"
        elif len(t) <= 70 and (fallback or t.isupper()):
            h = canon_heading(t)   # upper-case headings missing from the bookmarks ("ROOT CAUSE", "CONCLUSION")
        if h:
            cur, in_sig = h, False
            if h != "DROP":
                secs.setdefault(h, [])
            continue
        if cur == "DROP":
            dropped += b["lines"]
            continue
        if SIGNATURE.match(t):
            in_sig = True
            dropped.append(t)
            continue
        if in_sig and len(t) < 80:
            dropped.append(t)
            continue
        in_sig = False
        if cur == "HEADER":
            header += [ln.strip() for ln in b["lines"]]
        else:
            secs[cur].append(t)
    if fallback and not any(secs.values()):
        # header ends at the "Originating Office" block (or the first long paragraph)
        cut = next((i for i, ln in enumerate(header) if ln.lower().startswith("originating office")), None)
        hdr_lines = header
        body_blocks = [b for b in blocks if b["text"] and not b["heading"]]
        if cut is not None:
            office = header[cut]
            idx = next((i for i, b in enumerate(blocks) if office in [ln.strip() for ln in b["lines"]]), 0)
            # skip the office address block(s): body starts at the first real paragraph
            start = next((j for j in range(idx + 1, len(blocks)) if len(blocks[j]["text"]) > 200
                          and not re.match(r"^(Mine Safety and Health Administration|District \d)", blocks[j]["text"])), len(blocks))
            body_blocks = blocks[start:]
            hdr_lines = header[:cut + 14]
        else:
            first_long = next((i for i, b in enumerate(blocks) if len(b["text"]) > 250), len(blocks))
            body_blocks = blocks[first_long:]
        header = hdr_lines
        secs = {}
        for b in body_blocks:
            t = b["text"]
            if len(t) <= 70 and canon_heading(t) == "DROP":
                break
            if RC_PARA.match(t):
                secs.setdefault("ROOT_CAUSE", []).append(t)
            elif ENF_PARA.match(t) or ("ENFORCEMENT" in secs and not RC_PARA.match(t) and "ROOT_CAUSE" in secs):
                secs.setdefault("ENFORCEMENT", []).append(t)
            elif "OVERVIEW" not in secs:
                secs["OVERVIEW"] = [t]
            else:
                secs.setdefault("DESCRIPTION", []).append(t)
    return header, secs, dropped, fallback


def alert_split(texts: list[str]) -> tuple[list[str], list[str]]:
    summary, practices, cur = [], [], "s"
    for t in texts:
        low = t.lower()
        if low.startswith("best practice"):
            cur = "b"
            rest = re.sub(r"^best practices?:?\s*", "", t, flags=re.I)
            if rest:
                practices.append(rest)
            continue
        if low.startswith(("additional information", "this is ms", "fatality alert")) and len(t) < 120:
            cur = "x" if low.startswith("additional") else cur
            continue
        (summary if cur == "s" else practices if cur == "b" else []).append(t)
    return summary, practices


def _state(meta: dict, idx_row: dict) -> str | None:
    loc = meta.get("location_event", "")
    if " - " in loc:
        return loc.rsplit(" - ", 1)[1].split(",")[-1].strip() or None
    return idx_row.get("state") or None


def process_pdf(path: Path, idx_row: dict) -> list[dict]:
    blocks = pdf_blocks(path)
    parts = split_dossier(blocks)
    front = parts["front"]
    event_id = front.get("event_id") or idx_row["event_id"]
    year = int(event_id.split("/")[0])
    rel = str(path.relative_to(config.DATA))
    ev_meta = {**{k: v for k, v in front.items() if k != "event_id"},
               "mine_name": idx_row.get("mine") or None}
    ev_meta["state"] = _state(ev_meta, idx_row)
    if " - " in ev_meta.get("location_event", ""):
        ev_meta["county_state"] = ev_meta["location_event"].rsplit(" - ", 1)[1].strip()
    has_final = bool(parts["report"]) and idx_row.get("has_final_report") == "True"

    with pymupdf.open(path) as d:
        toc = {t.strip() for lvl, t, _ in d.get_toc() if lvl == 2}
    header, secs, dropped, fallback = report_sections(parts["report"], toc) if has_final else ([], {}, [], False)
    hmeta = parse_header(header)
    meta = {**ev_meta, **{k: v for k, v in hmeta.items() if k not in ("mine_name",) or not ev_meta.get("mine_name")}}

    # names: harvest over everything we keep (report, alert, summary, supplement)
    all_lines = header + [p for v in secs.values() for p in v] + parts["alert"] + parts["summary"] + parts["supplement"]
    victims, people = harvest_names(all_lines, secs)
    people |= harvest_header_people(header)
    # appendix participant lists are dropped from the text, but their names must be redacted elsewhere
    _, extra = harvest_names(dropped, {})
    people |= extra
    for ln in dropped:   # "Gaither Frazier .. General Manager"
        for m in re.finditer(rf"({FULL_NAME})\s*\.{{2,}}", ln):
            n = _clean_name(m.group(1))
            if n:
                people.add(n)
    people -= victims
    protected = " ".join(filter(None, [meta.get("mine_name"), meta.get("operator"), meta.get("controller")]))
    red = Redactor(victims, people, protected)
    names = {"victims": sorted(victims), "people": sorted(people)}
    docs = []

    # table-of-contents / participant lines ("OVERVIEW ......... 1", "Name ........ Title"): names harvested above,
    # text dropped (no content, and dot runs explode the token count)
    keep = lambda t: not re.search(r"\.{6,}|(?:\. ){5,}", t)  # noqa: E731
    secs = {k: [p for p in v if keep(p)] for k, v in secs.items()}
    parts["supplement"] = [t for t in parts["supplement"] if keep(t)]

    if has_final:
        sections = {}
        for name, paras in secs.items():
            paras = [red(p) for p in paras]
            sections[name] = structure_discussion(paras) if name == "DISCUSSION" else [{"subheading": None, "paras": paras}]
        if parts["supplement"]:
            sections["SUPPLEMENT"] = [{"subheading": None, "paras": [red(t) for t in parts["supplement"]]}]
        enf = " ".join(secs.get("ENFORCEMENT", []))
        n_chars = sum(len(p) for s in sections.values() for b in s for p in b["paras"])
        docs.append({
            "doc_id": f"{event_id}#final", "event_id": event_id, "doc_type": "final_report", "year": year,
            "source_path": rel, "meta": meta, "sections": sections,
            "root_causes": (parse_root_causes([red(p) for p in secs.get("ROOT_CAUSE", [])])
                            or parse_root_causes([red(t) for t in parts["supplement"]])),
            "cfr_cited": cited_sections(enf),
            "n_chars": n_chars,
            "quality_flags": [f for f, c in [("stub_short_report", n_chars < 4000), ("no_root_cause", "ROOT_CAUSE" not in secs),
                                             ("no_enforcement", "ENFORCEMENT" not in secs),
                                             ("no_headings_fallback", fallback)] if c],
            "_names": names,
        })

    summary, practices = alert_split(parts["alert"])
    if summary or practices:
        docs.append({
            "doc_id": f"{event_id}#alert", "event_id": event_id, "doc_type": "fatality_alert", "year": year,
            "source_path": rel, "meta": ev_meta,
            "sections": {"ALERT_SUMMARY": [{"subheading": None, "paras": [red(t) for t in summary]}],
                         "BEST_PRACTICES": [{"subheading": None, "paras": [red(t) for t in practices]}]},
            "root_causes": [], "cfr_cited": [], "n_chars": sum(map(len, summary + practices)), "quality_flags": [],
            "_names": {"victims": [], "people": []},
        })

    if not has_final:
        pl = [t for t in parts["summary"] + parts["supplement"]
              if "based on preliminary data ONLY" not in t and t.lower() not in ("preliminary report", "event summary")]
        if pl:
            docs.append({
                "doc_id": f"{event_id}#prelim", "event_id": event_id, "doc_type": "preliminary_report", "year": year,
                "source_path": rel, "meta": ev_meta,
                "sections": {"PRELIMINARY": [{"subheading": None, "paras": [red(t) for t in pl]}]},
                "root_causes": [], "cfr_cited": [], "n_chars": sum(map(len, pl)), "quality_flags": ["preliminary_not_final"],
                "_names": names,
            })
    return docs


def main():
    config.OUT.mkdir(parents=True, exist_ok=True)
    config.REDACTION_DIR.mkdir(parents=True, exist_ok=True)
    rows = [r for r in csv.DictReader(open(config.EVENTS_INDEX)) if r["pdf_dossier"] == "True"]
    stats, names_all, n_names = Counter(), {}, 0
    with open(config.DOCS_JSONL, "w") as f:
        for r in rows:
            for d in process_pdf(config.DATA / r["output_pdf"], r):
                nm = d.pop("_names")
                if nm["victims"] or nm["people"]:
                    names_all[d["doc_id"]] = nm
                    n_names += len(nm["victims"]) + len(nm["people"])
                stats[d["doc_type"]] += 1
                for q in d["quality_flags"]:
                    stats["flag:" + q] += 1
                stats["root_cause_pairs"] += len(d["root_causes"])
                f.write(json.dumps(d) + "\n")
    (config.REDACTION_DIR / "names.json").write_text(json.dumps(names_all, indent=1))
    print(f"dossiers={len(rows)} residual_names_redacted={n_names}", dict(stats))
    print("wrote", config.DOCS_JSONL)


if __name__ == "__main__":
    main()
