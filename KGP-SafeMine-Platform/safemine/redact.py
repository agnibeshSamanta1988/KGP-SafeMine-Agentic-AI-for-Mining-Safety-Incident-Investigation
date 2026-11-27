"""Redaction of "First I." / "First I. Surname" person mentions.

The cleaned dataset replaced victims' surnames with "the miner" but left the first name and middle initial
("John Q. The miner, truck driver, ...") and names other people as "Jane R. Roe". The pattern-based name harvester
does not see either form, so they reached chunks and answers. This module is dependency-free: it is used by the data
pipeline (clean_reports.Redactor, so chunks and indexes are clean) and again by the Output Filter (guard.output_filter,
so a name that survives anywhere is still removed from the answer).
"""
from __future__ import annotations

import re

# capitalised words that are followed by a single capital letter + period but are not first names
NOT_FIRST = {
    "Appendix", "Appendi", "Appendices", "After", "Aisle", "Area", "Coroner", "Crew", "Discussion", "Investigation", "Neither",
    "Photos", "Photo", "President", "Run", "Screen", "Sheet", "Street", "Tower", "Upon", "When", "While", "Section", "Figure",
    "Table", "Exhibit", "Part", "Page", "Level", "Zone", "Unit", "Plan", "Item", "Attachment", "Title", "Diagram", "Drawing",
    "Map", "Fire", "Class", "Type", "Mine", "Plant", "Belt", "Pit", "Bench", "Shaft", "Slope", "Entry", "Panel", "Block",
    "Lot", "Road", "Route", "Highway", "Hwy", "Building", "Bldg", "Chapter", "Phase", "Step", "Rule", "Order", "Citation",
    "Condition", "Practice", "Statement", "Interview", "Witness", "Victim", "Miner", "Foreman", "Supervisor", "Operator",
}
# capitalised words that follow an initial but are sentence starts / organisation words, not surnames
NOT_SURNAME = {
    "The", "He", "She", "His", "Her", "It", "They", "In", "On", "At", "An", "This", "That", "There", "After", "Before",
    "When", "While", "Mine", "Plant", "Quarry", "Company", "Inc", "Corp", "Corporation", "Coal", "Mining", "Safety", "Health",
    "Department", "Administration", "Office", "District", "Section", "Resources", "Construction", "Stone", "Sand", "Gravel",
    "Industries", "Materials", "Services", "Energy", "Operator", "Miner", "Foreman", "Supervisor", "Victim", "Investigator",
}
_NAME = r"[A-Z][A-Za-z'’-]{2,}"
_THE_MINER = re.compile(rf"\b({_NAME}) [A-Z]\.\s+(?=[Tt]he miner\b)")
_FULL = re.compile(rf"\b({_NAME}) [A-Z]\.\s+({_NAME})\b")
_INITIAL = re.compile(rf"\b({_NAME}) [A-Z]\.(?!\w)")


def redact_initial_names(text: str) -> str:
    """'John Q. The miner' -> 'The miner';  'Jane R. Roe' -> '[PERSON]';  'Richard E.' -> '[PERSON]'."""
    if not text:
        return text
    text = _THE_MINER.sub(lambda m: m.group(0) if m.group(1) in NOT_FIRST else "", text)
    text = _FULL.sub(lambda m: m.group(0) if m.group(1) in NOT_FIRST or m.group(2) in NOT_SURNAME else "[PERSON]", text)
    return _INITIAL.sub(lambda m: m.group(0) if m.group(1) in NOT_FIRST else "[PERSON]", text)
