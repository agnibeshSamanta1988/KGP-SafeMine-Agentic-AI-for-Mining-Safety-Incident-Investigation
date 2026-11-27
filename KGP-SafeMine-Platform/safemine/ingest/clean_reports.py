"""Step 1 of the offline pipeline: MSHA fatality HTML -> clean, sectioned, PII-redacted documents.

What is KEPT (useful for the agent)
  * final-report.html  -> OVERVIEW, GENERAL INFORMATION, DESCRIPTION, INVESTIGATION, DISCUSSION
                          (with sub-headings), ROOT CAUSE ANALYSIS, CONCLUSION, ENFORCEMENT
  * event.html         -> metadata only (classification, mine type, material, state, controller, date)
  * fatality-alert.html-> the short summary + "Best Practices" bullets (good prevention evidence)
  * preliminary-report -> only for events that have NO final report yet (marked status=preliminary)

What is DROPPED (noise / PII, no analytical value)
  * public-notice.html (boilerplate + investigator phone numbers)
  * website chrome: breadcrumbs, "PDF Version", file-size lines, "Read more ..." links
  * report header block: investigator names, district office postal address
  * "Approved By" signature blocks
  * APPENDIX A/B/... and "Persons participating / interviewed" lists (names only; sketches live in PDFs)
  * search_pages/, PDFs (same text as HTML; photos/sketches may be third-party), pre2008_optional/ (flag)

PII handling
  A per-report name list is harvested (victim from OVERVIEW/CONCLUSION, people "Name, Title",
  appendix participant tables, header investigators, signatures). Full names and stand-alone
  surnames are replaced with stable pseudonyms ([VICTIM], [PERSON-1] ...). The name lists are
  written to data_processed/_restricted/ for the Output Filter and are never sent to the LLM.

Run:  .venv/bin/python -m safemine.ingest.clean_reports
"""
from __future__ import annotations

import html as htmllib
import json
import re
from collections import Counter
from pathlib import Path

from safemine import config
from safemine.redact import redact_initial_names

# ---------------------------------------------------------------- HTML -> lines
BLOCK_END = re.compile(r"<br\s*/?>|</p>|</h\d>|</li>|</div>|</tr>|</td>|</th>|</section>|</article>", re.I)
CHROME = re.compile(
    r"^(accident report: fatality reference|pdf version|report upload|fatality overview.*|notice|"
    r"read more.*|\(?\d+(\.\d+)? ?(kb|mb)\)?|.*\.pdf|.*- (final report|fatality alert|preliminary report|public notice)$|"
    r"(final report|fatality alert|preliminary report|public notice)( -)?.*fatality.*)$",
    re.I,
)


def html_lines(path: Path) -> list[str]:
    s = path.read_text(encoding="utf-8", errors="ignore")
    i, j = s.find("<main"), s.find("</main>")
    m = s[i:j] if i >= 0 and j > i else s
    m = re.sub(r"<(script|style|nav|noscript)[^>]*>.*?</\1>", " ", m, flags=re.S | re.I)
    m = BLOCK_END.sub("\n", m)
    m = re.sub(r"<[^>]+>", " ", m)
    m = htmllib.unescape(m).replace("\xa0", " ").replace("​", "")
    out = []
    for ln in m.split("\n"):
        ln = re.sub(r"[ \t]+", " ", ln).strip()
        if ln:
            out.append(ln)
    return out


# ---------------------------------------------------------------- sections
CANON = [
    (r"overview|summary", "OVERVIEW"),
    (r"general information", "GENERAL_INFORMATION"),
    (r"description of (the )?accident", "DESCRIPTION"),
    (r"investigation of (the )?accident|investigation", "INVESTIGATION"),
    (r"discussion( of (the )?accident)?", "DISCUSSION"),
    (r"root cause analysis|root cause|root cause analysis and corrective actions?", "ROOT_CAUSE"),
    (r"conclusions?", "CONCLUSION"),
    (r"enforce?ment actions?|enforcment actions?", "ENFORCEMENT"),
    (r"appendix.*|list of appendices|(list of )?persons (participating|interviewed).*|mining company officials", "DROP"),
]
# accepted only when the line is upper-case (otherwise they are DISCUSSION sub-headings)
UPPER_ONLY = [(r"training (and|&) experience|training", "TRAINING_EXPERIENCE"),
              (r"rescue and recovery( efforts| operations)?", "RESCUE_RECOVERY")]


def canon_heading(line: str) -> str | None:
    key = re.sub(r"[:.]$", "", line.strip()).strip()
    low = key.lower()
    if len(key) > 70:
        return None
    for pat, name in CANON:
        if re.fullmatch(pat, low):
            # mixed-case "Investigation"/"Summary" is too ambiguous: require upper-case for those
            if name in ("INVESTIGATION", "OVERVIEW") and not key.isupper():
                return None
            return name
    if key.isupper():
        for pat, name in UPPER_ONLY:
            if re.fullmatch(pat, low):
                return name
    return None


def is_subheading(line: str, nxt: str | None) -> bool:
    """DISCUSSION sub-headings: short Title-Case line, no final period, followed by a paragraph."""
    if len(line) > 70 or line.endswith((".", ",", ";")) or not nxt or len(nxt) < 60:
        return False
    words = re.findall(r"[A-Za-z][A-Za-z'/&-]*", line)
    if not words or len(words) > 9:
        return False
    caps = sum(w[0].isupper() for w in words if w.lower() not in {"of", "and", "the", "to", "in", "on", "for", "a", "or"})
    return caps >= max(1, len([w for w in words if w.lower() not in {"of", "and", "the", "to", "in", "on", "for", "a", "or"}]) - 0)


# ---------------------------------------------------------------- header metadata
DATE_RE = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}"
MINE_ID_RE = re.compile(r"(?:I\.?\s?D\.?|Identification)\s*(?:No\.?|Number)?\s*:?\s*(\d{2}-\d{5})", re.I)


def parse_header(lines: list[str]) -> dict:
    meta: dict = {}
    txt = "\n".join(lines)
    m = MINE_ID_RE.search(txt)
    if m:
        meta["mine_id"] = m.group(1).replace("-", "")
        meta["mine_id_display"] = m.group(1)
    for i, ln in enumerate(lines):
        m = re.match(r"^Fatal (.+?) Accidents?$", ln, re.I)
        if m:
            meta.setdefault("classification_report", m.group(1).strip())
            # lines after the accident-type line: date, mine name, operator, location
            rest = lines[i + 1:i + 6]
            if rest and re.fullmatch(DATE_RE, rest[0]):
                meta.setdefault("accident_date_text", rest[0])
                if len(rest) > 1:
                    meta.setdefault("mine_name", rest[1])
                if len(rest) > 2:
                    meta.setdefault("operator", rest[2])
                if len(rest) > 3 and "," in rest[3]:
                    meta.setdefault("location", rest[3])
        if re.match(r"^(Surface|Underground|Facility|Mill|Shop)", ln) and "mine_category" not in meta and len(ln) < 60:
            meta["mine_category"] = ln
        if re.fullmatch(r"\(.+\)", ln) and "commodity" not in meta:
            meta["commodity"] = ln.strip("()")
    return meta


def parse_event(path: Path) -> dict:
    meta = {}
    if not path.exists():
        return meta
    for ln in html_lines(path)[:15]:
        m = re.match(r"^(Accident Classification|Location|Mine Controller|Mine Type|Mined Material|Incident Date/Time):\s*(.+)$", ln)
        if m:
            k = {"Accident Classification": "classification", "Location": "location_event", "Mine Controller": "controller",
                 "Mine Type": "mine_type", "Mined Material": "material", "Incident Date/Time": "incident_datetime"}[m.group(1)]
            meta[k] = m.group(2).strip()
    loc = meta.get("location_event", "")
    if " - " in loc:
        meta["county_state"] = loc.rsplit(" - ", 1)[1].strip()
        meta["state"] = meta["county_state"].split(",")[-1].strip()
    return meta


# ---------------------------------------------------------------- PII harvesting
NAME_TOK = r"[A-Z][a-zA-Z'’\-]+"
FULL_NAME = rf"{NAME_TOK}(?:\s+[A-Z]\.)?(?:\s+{NAME_TOK}){{1,2}}(?:,?\s+(?:Jr|Sr|II|III|IV)\.?)?"
ROLE_WORDS = (
    r"inspector|investigator|manager|specialist|foreman|operator|supervisor|superintendent|mechanic|miner|"
    r"laborer|labourer|electrician|driver|leadman|lead man|engineer|director|president|owner|coroner|officer|"
    r"technician|helper|counsel|representative|attorney|examiner|agent|administrator|chief|coordinator|welder|"
    r"trainer|boss|dispatcher|clerk|geologist|surveyor|assistant|analyst|employee|worker|crusher|loader|"
    r"truck|dozer|shift|section|safety|maintenance|plant|mine|general|vice|deputy|son|brother|father|victim|"
    r"contractor|partner|attendant|bolter|scoop|repairman|serviceman|mason|apprentice|trainee|member|"
    r"specialist|lineman|fireboss|outby|longwall|continuous|roof|belt|utility|electric|haul|equipment"
)
NOT_NAMES = {
    "Mine Safety", "United States", "Department Of", "Health Administration", "Accident Investigators",
    "Originating Office", "District Manager", "Federal Mine", "Root Cause", "Corrective Action", "The Mine",
    "Emergency Medical", "Medical Services", "National Contact", "Contact Center", "Mine Act", "Code Of",
}
VICTIM_PATTERNS = [
    re.compile(rf"(?:^|On {DATE_RE},?\s*(?:at [^,]+,)?\s*)({FULL_NAME}),\s+(?:a|an)\s+\d+[\s-]*year", re.M),
    re.compile(rf"({FULL_NAME}),\s+(?:a\s+)?[a-z][a-z /-]+,\s+(?:age|aged)\s+\d+"),
    re.compile(rf"({FULL_NAME}),\s+age\s+\d+"),
    re.compile(rf"({FULL_NAME})\s+\((?i:victim)\)"),
    re.compile(rf"\bvictim,\s+({FULL_NAME})"),
]
TITLE_FIRST = re.compile(rf"(?i:{ROLE_WORDS})s?,\s+({FULL_NAME})")
PAREN_ROLE = re.compile(rf"({FULL_NAME})\s+\([^)]*(?i:{ROLE_WORDS})[^)]*\)")
NAME_LIST_ROLE = re.compile(rf"((?:{FULL_NAME})(?:(?:,\s+|,?\s+and\s+)(?:{FULL_NAME}))+),\s+(?:[A-Za-z]+\s+){{0,4}}(?i:{ROLE_WORDS})")
DOT_LEADER = re.compile(rf"^({FULL_NAME})\s*\.{{3,}}")
TITLED = re.compile(rf"({FULL_NAME}),\s+(?:the\s+|a\s+|an\s+)?(?:[A-Za-z/&-]+\s+){{0,5}}?(?i:{ROLE_WORDS})\b")
# "Lee Example — Plant Manager" (principal-officials lists in the cleaned PDF dossiers)
DASH_ROLE = re.compile(rf"({FULL_NAME})\s+[\u2014\u2013-]\s+(?:[A-Za-z/&-]+\s+){{0,5}}?(?i:{ROLE_WORDS})\b")


TRAILING_ROLE = {"supervisory", "assistant", "inspector", "specialist", "manager", "investigator", "district",
                 "foreman", "superintendent", "engineer", "director", "president", "operator", "mechanic", "deputy"}


US_STATES = {"Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware", "Florida",
             "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine",
             "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska",
             "Nevada", "Hampshire", "Jersey", "Mexico", "York", "Carolina", "Dakota", "Ohio", "Oklahoma", "Oregon",
             "Pennsylvania", "Rhode", "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington", "Wisconsin",
             "Wyoming", "Rico"}
NOT_NAME_WORDS = {"technician", "analysis", "events", "accident", "equipment", "operations", "operator", "manager",
                  "maintenance", "support", "examinations", "area", "services", "report", "safety", "health", "plant",
                  "unit", "crew", "shift", "department", "superintendent", "foreman", "president", "co-president",
                  "supervisor", "engineer", "inspector", "specialist", "director", "superintendant", "mechanic",
                  "training", "general", "assistant", "laborer", "owner", "employee", "contractor", "electrician",
                  "boss", "truck", "driver", "death", "medical", "medicolegal", "approval", "articulating", "dyno",
                  "nobel", "no", "loader", "dozer", "conveyor", "crusher", "examiner", "investigator", "coroner"}


def _clean_name(n: str) -> str | None:
    n = re.sub(r"\s+", " ", n).strip(" ,.")
    n = re.sub(r"^(On|At|By|And|Then|When|While|After|Before|Mr|Ms|Mrs|Dr)\.?\s+", "", n)
    toks = n.split()
    while toks and toks[0].lower().strip(",") in NOT_NAME_WORDS:   # "Manager Alex Sample" -> "Alex Sample"
        toks = toks[1:]
    if any(t in US_STATES or t.lower() in NOT_NAME_WORDS for t in toks):
        return None
    while toks and toks[0].isupper() and len(toks[0]) > 2:   # "ACCIDENT Sam Doe" -> "Sam Doe"
        toks = toks[1:]
    while toks and toks[-1].lower() in TRAILING_ROLE:   # "Bo Sample Supervisory" -> "Bo Sample"
        toks = toks[:-1]
    n = " ".join(toks)
    if any(not t[0].isupper() for t in toks if t not in ("Jr.", "Sr.")):
        return None
    if len(toks) < 2 or len(toks) > 5:
        return None
    if any(t.lower() in {"the", "mine", "company", "inc", "llc", "corporation", "county", "district", "msha",
                          "department", "administration", "office", "center", "quarry", "plant", "pit", "section",
                          "mining", "seam", "operators", "inspectors", "services", "division", "energy", "resources",
                          "materials", "construction", "stone", "sand", "gravel", "coal", "industries", "field"} for t in toks):
        return None
    if " ".join(toks[:2]) in NOT_NAMES or n.isupper():
        return None
    if re.search(DATE_RE, n):
        return None
    return n


def harvest_names(lines: list[str], sections: dict[str, list[str]]) -> tuple[set[str], set[str]]:
    victims: set[str] = set()
    people: set[str] = set()
    body = "\n".join(lines)
    focus = "\n".join(sections.get("OVERVIEW", []) + sections.get("CONCLUSION", []) + sections.get("GENERAL_INFORMATION", [])[:3])
    for pat in VICTIM_PATTERNS:
        for m in pat.finditer(focus):
            n = _clean_name(m.group(1))
            if n:
                victims.add(n)
    for m in list(TITLED.finditer(body)) + list(DASH_ROLE.finditer(body)) + list(TITLE_FIRST.finditer(body)) + list(PAREN_ROLE.finditer(body)):
        n = _clean_name(m.group(1))
        if n:
            people.add(n)
    for m in NAME_LIST_ROLE.finditer(body):
        for part in re.split(r",\s+|,?\s+and\s+", m.group(1)):
            n = _clean_name(part)
            if n:
                people.add(n)
    for ln in lines:
        m = DOT_LEADER.match(ln)
        if m and _clean_name(m.group(1)):
            people.add(_clean_name(m.group(1)))
    # tables: "Name    Title" (appendix lists, principal officials) -> name before 2+ spaces / tab
    for ln in lines:
        parts = re.split(r"\s{2,}|\t", ln)
        if len(parts) >= 2 and re.fullmatch(FULL_NAME, parts[0].strip()):
            n = _clean_name(parts[0])
            if n:
                people.add(n)
        m = re.fullmatch(rf"({FULL_NAME}),?\s+(?:District Manager|Assistant District Manager|Supervisory .+|Mine Safety and Health .+|Accident Investigator.*)", ln)
        if m:
            n = _clean_name(m.group(1))
            if n:
                people.add(n)
    return victims, people - victims


def harvest_header_people(header: list[str]) -> set[str]:
    out = set()
    grab = False
    for ln in header:
        if re.match(r"^Accident Investigators?|^Investigators?$", ln, re.I):
            grab = True
            continue
        if re.match(r"^Originating Office", ln, re.I):
            grab = False
        if grab or re.search(r",\s*District Manager$", ln):
            m = re.match(rf"^({FULL_NAME})", ln)
            if m:
                n = _clean_name(m.group(1))
                if n:
                    out.add(n)
    return out


COMMON_CAPS = {"The", "Mine", "Mines", "Company", "Inc", "Coal", "Safety", "Health", "Manager", "Operator", "Foreman",
               "Inspector", "Supervisor", "Mining", "Section", "Plant", "Quarry", "County", "District", "Office",
               "Department", "Accident", "Investigation", "Report", "Root", "Cause", "Action", "Federal", "State",
               "North", "South", "East", "West", "Main", "Unit", "Shift", "Center", "Services", "Corporation", "LLC"}


class Redactor:
    def __init__(self, victims: set[str], people: set[str], protected_text: str):
        self.map: dict[str, str] = {}
        for v in sorted(victims):
            self.map[v] = "[VICTIM]" if len(victims) == 1 else f"[VICTIM-{len([k for k in self.map.values() if 'VICTIM' in k]) + 1}]"
        for i, p in enumerate(sorted(people), 1):
            self.map[p] = f"[PERSON-{i}]"
        # surnames (and first+last without middle initial) for stand-alone mentions
        self.surname: dict[str, str] = {}
        self.protected = protected_text  # mine / operator names: don't destroy "Wheeler Rock Quarry"
        for full, tag in list(self.map.items()):
            toks = [t for t in full.replace(",", " ").split() if not re.fullmatch(r"[A-Z]\.|Jr\.?|Sr\.?|II|III|IV", t)]
            if len(toks) >= 2 and re.fullmatch(r"[A-Z][a-zA-Z'\u2019-]{2,}", toks[-1]) and toks[-1] not in COMMON_CAPS:
                self.surname.setdefault(toks[-1], tag)
                self.surname.setdefault(f"{toks[0]} {toks[-1]}", tag)

    def __call__(self, text: str) -> str:
        for full in sorted(self.map, key=len, reverse=True):
            text = re.sub(rf"\b{re.escape(full)}\b(?:’s|'s)?", lambda m, t=self.map[full]: t + ("'s" if m.group(0).endswith("s") and m.group(0) != full else ""), text)
        for sn in sorted(self.surname, key=len, reverse=True):
            tag = self.surname[sn]
            # skip when followed by another Capitalised word (e.g. "Wheeler Rock Quarry", "Gore Construction")
            text = re.sub(rf"\b(?:(?:Mr|Ms|Mrs|Dr)\.?\s+)?{re.escape(sn)}\b(?!\s+[A-Z][a-z])", tag, text)
        text = re.sub(r"\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b", "[PHONE]", text)
        text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[EMAIL]", text)
        return redact_initial_names(text)   # "John Q. The miner", "Jane R. Roe": not caught by the harvester


# ---------------------------------------------------------------- final report parsing
SIGNATURE = re.compile(r"^(Approved By:?|Approved:?|_{5,}.*|Date|District Manager|Acting District Manager)$", re.I)
CFR_RE = re.compile(r"30\s*C\.?F\.?R\.?\s*(?:§+\s*)?(?:Part\s+)?(\d{1,3}\.\d+(?:-\d+)?(?:\([a-z0-9]+\))*)", re.I)


def split_sections(lines: list[str]) -> tuple[list[str], dict[str, list[str]], list[str]]:
    """Returns (header_lines, {SECTION: lines}, dropped_lines)."""
    # cut website chrome before the report proper
    start = 0
    for i, ln in enumerate(lines[:40]):
        if ln.upper() in ("REPORT OF INVESTIGATION", "UNITED STATES") or ln.startswith(("MAI-", "CAI-", "FAI-")):
            start = i
            break
    lines = [ln for ln in lines[start:] if not CHROME.match(ln)]
    header, secs, dropped = [], {}, []
    cur = "HEADER"
    in_sig = False
    for ln in lines:
        h = canon_heading(ln)
        if h:
            cur = h
            in_sig = False
            if h != "DROP":
                secs.setdefault(h, [])
            continue
        if cur == "DROP":
            dropped.append(ln)
            continue
        if SIGNATURE.match(ln):
            in_sig = True
            dropped.append(ln)
            continue
        if in_sig:  # names / titles right after "Approved By" until the next heading
            if len(ln) < 80:
                dropped.append(ln)
                continue
            in_sig = False
        if cur == "HEADER":
            header.append(ln)
        else:
            secs.setdefault(cur, []).append(ln)
    return header, secs, dropped


def structure_discussion(lines: list[str]) -> list[dict]:
    """[{subheading, paragraphs}] for DISCUSSION-like sections."""
    blocks, cur = [], {"subheading": None, "paras": []}
    for i, ln in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        if is_subheading(ln, nxt):
            if cur["paras"] or cur["subheading"]:
                blocks.append(cur)
            cur = {"subheading": ln.rstrip(":"), "paras": []}
        else:
            cur["paras"].append(ln)
    if cur["paras"]:
        blocks.append(cur)
    return blocks


def parse_root_causes(lines: list[str]) -> list[dict]:
    txt = "\n".join(lines)
    pairs = []
    for m in re.finditer(r"Root Cause\s*\d*\s*:\s*(.+?)\s*Corrective Actions?\s*:\s*(.+?)(?=(?:\n\s*\d+\.?\s*)?Root Cause\s*\d*\s*:|\Z)", txt, re.S | re.I):
        rc = re.sub(r"\s+", " ", m.group(1)).strip()
        ca = re.sub(r"\s+", " ", m.group(2)).strip()
        ca = re.sub(r"\s*\d+\.?$", "", ca)
        pairs.append({"root_cause": rc, "corrective_action": ca})
    return pairs


def process_event(ev_dir: Path) -> list[dict]:
    year = ev_dir.parent.name
    event_id = f"{year}/{ev_dir.name}"
    ev_meta = parse_event(ev_dir / "event.html")
    docs = []

    fr = ev_dir / "final-report.html"
    if fr.exists():
        lines = html_lines(fr)
        header, secs, dropped = split_sections(lines)
        meta = {**ev_meta, **parse_header(header)}
        victims, people = harvest_names(lines, secs)
        people |= harvest_header_people(header)
        # appendix participant lists are dropped, but their names must still be redacted elsewhere
        _, extra = harvest_names(dropped, {})
        people |= extra
        people -= victims
        protected = " ".join(filter(None, [meta.get("mine_name"), meta.get("operator"), meta.get("controller")]))
        red = Redactor(victims, people, protected)

        sections = {}
        for name, sl in secs.items():
            sl = [red(x) for x in sl]
            if name in ("DISCUSSION", "TRAINING_EXPERIENCE", "INVESTIGATION", "DESCRIPTION", "GENERAL_INFORMATION", "RESCUE_RECOVERY"):
                sections[name] = structure_discussion(sl) if name == "DISCUSSION" else [{"subheading": None, "paras": sl}]
            else:
                sections[name] = [{"subheading": None, "paras": sl}]
        rc_lines = [red(x) for x in secs.get("ROOT_CAUSE", [])]
        enf_text = " ".join(secs.get("ENFORCEMENT", []))
        cfr_cited = sorted({m.group(1).split("(")[0] for m in CFR_RE.finditer(enf_text)})
        n_chars = sum(len(p) for s in sections.values() for b in s for p in b["paras"])
        docs.append({
            "doc_id": f"{event_id}#final",
            "event_id": event_id,
            "doc_type": "final_report",
            "year": int(year),
            "source_path": str(fr.relative_to(config.DATA)),
            "meta": meta,
            "sections": sections,
            "root_causes": parse_root_causes(rc_lines),
            "cfr_cited": cfr_cited,
            "n_chars": n_chars,
            "quality_flags": [f for f, c in [("stub_use_pdf", n_chars < 4000), ("no_root_cause", "ROOT_CAUSE" not in secs),
                                             ("no_enforcement", "ENFORCEMENT" not in secs)] if c],
            "_names": {"victims": sorted(victims), "people": sorted(people)},
        })

    fa = ev_dir / "fatality-alert.html"
    if fa.exists():
        al = [ln for ln in html_lines(fa) if not CHROME.match(ln)]
        al = [ln for ln in al if not re.match(r"^(April|May|June|July|August|September|October|November|December|January|February|March).*Fatality( #\d+)?$|^Fatality #\d+", ln)]
        summary, practices, cur = [], [], "s"
        for ln in al:
            low = ln.lower()
            if low.startswith("best practice"):
                cur = "b"; continue
            if low.startswith("additional information"):
                cur = "x"; continue
            if cur == "s":
                summary.append(ln)
            elif cur == "b":
                practices.append(ln)
        if summary or practices:
            docs.append({
                "doc_id": f"{event_id}#alert", "event_id": event_id, "doc_type": "fatality_alert", "year": int(year),
                "source_path": str(fa.relative_to(config.DATA)), "meta": ev_meta,
                "sections": {"ALERT_SUMMARY": [{"subheading": None, "paras": summary}],
                             "BEST_PRACTICES": [{"subheading": None, "paras": practices}]},
                "root_causes": [], "cfr_cited": [], "n_chars": sum(map(len, summary + practices)), "quality_flags": [],
                "_names": {"victims": [], "people": []},
            })

    pr = ev_dir / "preliminary-report.html"
    if pr.exists() and not fr.exists():
        pl = [ln for ln in html_lines(pr) if not CHROME.match(ln)]
        pl = [ln for ln in pl if "based on preliminary data ONLY" not in ln and not ln.lower().startswith("preliminary report overview")]
        pl = [ln for ln in pl if not re.search(r"Fatality( #\d+)?$", ln)]
        if pl:
            docs.append({
                "doc_id": f"{event_id}#prelim", "event_id": event_id, "doc_type": "preliminary_report", "year": int(year),
                "source_path": str(pr.relative_to(config.DATA)), "meta": ev_meta,
                "sections": {"PRELIMINARY": [{"subheading": None, "paras": pl}]},
                "root_causes": [], "cfr_cited": [], "n_chars": sum(map(len, pl)), "quality_flags": ["preliminary_not_final"],
                "_names": {"victims": [], "people": []},
            })
    return docs


def main():
    config.OUT.mkdir(parents=True, exist_ok=True)
    (config.REDACTION_DIR).mkdir(parents=True, exist_ok=True)
    # legacy reader for the original HTML layout (02_fatality_reports/html); the cleaned dataset uses clean_pdfs.py
    events = sorted(p for p in (config.DATA / "02_fatality_reports" / "html").glob("*/*") if p.is_dir())
    stats = Counter()
    names_all = {}
    with open(config.DOCS_JSONL, "w") as f:
        for ev in events:
            for d in process_event(ev):
                names_all[d["doc_id"]] = d.pop("_names")
                stats[d["doc_type"]] += 1
                for q in d["quality_flags"]:
                    stats["flag:" + q] += 1
                f.write(json.dumps(d) + "\n")
    (config.REDACTION_DIR / "names.json").write_text(json.dumps(names_all, indent=1))
    print(f"events={len(events)}", dict(stats))
    print("wrote", config.DOCS_JSONL)


if __name__ == "__main__":
    main()
