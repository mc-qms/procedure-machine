#!/usr/bin/env python3
"""Genesis citation check - deterministic, no model calls.

The Genesis rule: a regulatory citation in the draft must trace to
the packet, or it does not stay. This script is the enforcement,
in code, because a rule that must hold every time cannot rest on a
prompt.

What it verifies, and how (the granularity is stated, not hidden):
- Instruments (ICH Q10, NIST AI RMF, a named FDA guidance, ...):
  verified when the instrument is in the packet's inventory, at
  the exact revision the packet carries - a citation to ICH Q9
  does not verify against a packet whose risk-management source
  is ICH Q9(R1), because the revision is part of what the
  citation claims. The inventory is authoritative from
  genesis_intake.json (the sources the registry sent and the
  instruments each one carries), plus any instrument designation
  found in the packet text itself.
- References entries: an entry in the draft's References section
  that matches no packet source (by a verified instrument it
  names, or by its title) is listed in the flag list as an
  unrecognized reference, for the author to confirm or remove.
  Titles are matched fuzzily, so this is a warning only - title
  entries are never removed automatically.
- CFR sections (21 CFR 211.100 and the like): verified when the
  instrument is a CFR part the packet text works with AND the
  exact section string appears in the packet text.
- Pinpoint sections inside a guidance document (ICH Q10 section
  3.2, say) are verified at instrument level only: extracted text
  does not carry reliable section addressing, so the check does
  not pretend otherwise. The flag list says so, and the section
  number is the author's to confirm in their later edit.

Enforcement is right-or-cut: an unverified citation is REMOVED
from the draft and replaced with a gap marker; the removed text
is quoted only here, in the flag list, never left standing in the
draft as a flag-and-keep. Internal references (the organization's
own document numbers) are the opposite case by design: they are
placeholders, collected into the flag list, and left in the draft
for the author's later edit.

Usage:
  citation_check.py --session-dir DIR [--draft draft_final.md]
                    [--enforce] [--out citation_check.json]

Without --enforce it only reports (JSON to --out and stdout).
With --enforce it rewrites the draft (and its .txt twin), appends
the flag list to the draft, and writes genesis_flags.md.
"""

import argparse
import json
import os
import re
import sys

VERSION = "1.0"

REMOVAL_MARKER = ("[AUTHOR INPUT REQUIRED: regulatory citation removed by the "
                  "source check - it does not appear in the packet "
                  "sources. Cite a source from the packet, or delete the "
                  "reference.]")

# FDA CFR parts a bare section sign (211.100 after a section mark)
# can belong to. A section citation outside these is not read as
# a CFR citation at all.
KNOWN_PARTS = {"4", "7", "11", "210", "211", "600", "601", "606", "610",
               "809", "820", "1271"}

_MARKER_RE = re.compile(
    r"\[(AUTHOR INPUT REQUIRED|TECHNICAL PARAMETER REQUIRED|"
    r"QA REVIEW REQUIRED|REFERENCE CONFLICT):([^\]]+)\]")


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").strip().upper())


def _base(instrument):
    """Instrument identity without its revision tag: ICH Q9(R1)
    and ICH Q9 are the same instrument for verification."""
    return re.sub(r"\s*\(R\d+\)", "", _norm(instrument))


def load_inventory(session_dir):
    """What the packet actually contains, for verification.

    Returns {"instruments": set of normalized names,
             "bases": set of base forms,
             "cfr_sections": set of 'NNN.NN' strings in the packet text,
             "cfr_parts": set of part numbers the packet text uses,
             "sources": [intake source dicts, when present]}.
    """
    inv = {"instruments": set(), "bases": set(), "cfr_sections": set(),
           "cfr_parts": set(), "sources": []}
    intake_path = os.path.join(session_dir, "genesis_intake.json")
    if os.path.exists(intake_path):
        try:
            intake = json.load(open(intake_path))
            inv["sources"] = intake.get("sources", [])
            for src in inv["sources"]:
                for inst in src.get("instruments", []):
                    inv["instruments"].add(_norm(inst))
                    inv["bases"].add(_base(inst))
        except (OSError, json.JSONDecodeError):
            pass
    packet_text = ""
    for name in ("source_packet.md",):
        path = os.path.join(session_dir, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="replace") as f:
                packet_text = f.read()
    # Instruments named in the packet text itself join the
    # inventory: a guidance in the packet that discusses ICH Q10
    # by name puts ICH Q10 within the drafter's reach.
    for m in re.finditer(r"\bICH\s+([QMES]\d+(?:\s*\(R\d+\))?)", packet_text):
        # Normalized exactly as extract_citations normalizes, so a
        # designation the packet text carries ("ICH Q9(R1)") and a
        # citation to it land on the same inventory string.
        inst = "ICH " + re.sub(r"\s+", "", m.group(1).upper())
        inv["instruments"].add(_norm(inst))
        inv["bases"].add(_base(inst))
    if re.search(r"\bNIST\s+AI\s+(RMF|100-1)\b", packet_text):
        inv["instruments"].update({"NIST AI RMF", "NIST AI 100-1", "AI RMF"})
        inv["bases"].update({"NIST AI RMF", "NIST AI 100-1", "AI RMF"})
    if re.search(r"\bGood Machine Learning Practice\b", packet_text):
        inv["instruments"].add("GOOD MACHINE LEARNING PRACTICE")
        inv["bases"].add("GOOD MACHINE LEARNING PRACTICE")
    for m in re.finditer(r"\b(\d{1,3})\.(\d+)\b", packet_text):
        inv["cfr_sections"].add(f"{m.group(1)}.{m.group(2)}")
        inv["cfr_parts"].add(m.group(1))
    for m in re.finditer(r"\bPart\s+(\d{1,3})\b", packet_text):
        inv["cfr_parts"].add(m.group(1))
    return inv


def extract_citations(text):
    """Citation-shaped references in a draft. Each result:
    {raw, kind, instrument, section, start, end}. Overlaps are
    resolved longest-first."""
    found = []

    def add(m, kind, instrument, section=None):
        found.append({"raw": m.group(0), "kind": kind,
                      "instrument": instrument, "section": section,
                      "start": m.start(), "end": m.end()})

    for m in re.finditer(r"\b(\d{1,2})\s*CFR\s*(?:Part\s*)?(\d{1,3})\.(\d+)\b", text):
        add(m, "CFR", f"{m.group(1)} CFR Part {m.group(2)}",
            f"{m.group(2)}.{m.group(3)}")
    for m in re.finditer(r"\b(\d{1,2})\s*CFR\s*(?:Part\s*)?(\d{1,3})\b", text):
        add(m, "CFR", f"{m.group(1)} CFR Part {m.group(2)}")
    for m in re.finditer(r"§\s*(\d{1,3})\.(\d+)\b", text):
        if m.group(1) in KNOWN_PARTS:
            add(m, "CFR", f"21 CFR Part {m.group(1)}",
                f"{m.group(1)}.{m.group(2)}")
    for m in re.finditer(
            r"\bICH\s+([QMES]\d+(?:\s*\(R\d+\))?)"
            r"(?:\s*[,;]?\s*(?:section|clause|chapter|annex)\s*([0-9]+(?:\.[0-9]+)*))?",
            text, re.IGNORECASE):
        inst = "ICH " + re.sub(r"\s+", "", m.group(1).upper())
        add(m, "ICH", inst, m.group(2))
    for m in re.finditer(r"\bNIST\s+AI\s+(?:RMF|100-1)\b|\bAI\s+RMF\b", text,
                         re.IGNORECASE):
        add(m, "NIST", "NIST AI RMF")
    for m in re.finditer(r"\bGood Machine Learning Practice\b|\bGMLP\b", text):
        add(m, "GMLP", "Good Machine Learning Practice")
    for m in re.finditer(r"\bUSP\s*<(\d+)>", text):
        add(m, "USP", f"USP <{m.group(1)}>")
    for m in re.finditer(r"\bUSP\s*(\d{3,4})\b|\bUSP[-–]NF\b", text):
        add(m, "USP", f"USP {m.group(1)}" if m.group(1) else "USP-NF")
    for m in re.finditer(r"\bISO\s*(\d{4,5}(?::\d{4})?)\b", text):
        add(m, "ISO", f"ISO {m.group(1)}")
    for m in re.finditer(
            r"\bEU\s+GMP\s+(?:(?:Chapter|Annex)\s+\d+|Part\s+(?:IV|II|I))\b",
            text):
        add(m, "EU GMP", m.group(0))
    for m in re.finditer(r"\bFDA(?:'s)?\s+(?:draft\s+)?guidance\b", text,
                         re.IGNORECASE):
        add(m, "FDA guidance", "FDA guidance")
    found.sort(key=lambda c: (c["start"], -(c["end"] - c["start"])))
    out, last_end = [], -1
    for c in found:
        if c["start"] >= last_end:
            out.append(c)
            last_end = c["end"]
    return out


def verify(citation, inv):
    """(verified, basis). Basis says what the verification rests
    on, in plain words, for the flag list."""
    kind = citation["kind"]
    if kind == "CFR":
        part = re.search(r"Part\s+(\d{1,3})", citation["instrument"])
        part = part.group(1) if part else None
        if citation.get("section"):
            if citation["section"] in inv["cfr_sections"]:
                return True, (f"section {citation['section']} appears in the "
                              f"packet text")
            return False, (f"section {citation['section']} does not appear in "
                           f"the packet text")
        if part and part in inv["cfr_parts"]:
            return True, f"Part {part} is worked with in the packet text"
        return False, f"Part {part} is not worked with in the packet text"
    if kind == "FDA guidance":
        if any(i.startswith("FDA") for i in inv["instruments"]):
            return True, "an FDA guidance is a packet source"
        return False, "no FDA guidance is a packet source"
    if kind == "NIST":
        if "NIST AI RMF" in inv["instruments"] or "AI RMF" in inv["instruments"]:
            return True, "the NIST AI RMF is a packet source"
        return False, "the NIST AI RMF is not a packet source"
    # ICH, GMLP, USP, ISO, EU GMP: instrument-level verification at
    # the exact revision. The packet's inventory carries the exact
    # forms; a citation whose revision differs from the packet's -
    # or that names no revision where the packet's instrument has
    # one - does not verify. It becomes a repair item, then a cut
    # at delivery, like any other unverified citation.
    if _norm(citation["instrument"]) in inv["instruments"]:
        return True, f"{citation['instrument']} is a packet source"
    if _base(citation["instrument"]) in inv["bases"]:
        return False, (f"the packet carries {_base(citation['instrument'])} "
                       f"in a different revision - a citation must match "
                       f"the packet's revision exactly")
    return False, f"{citation['instrument']} is not a packet source"


def check_text(text, inv):
    verified, unverified = [], []
    for c in extract_citations(text):
        ok, basis = verify(c, inv)
        entry = {k: c[k] for k in ("raw", "kind", "instrument", "section")}
        entry["basis"] = basis
        (verified if ok else unverified).append(entry)
    return {"verified": verified, "unverified": unverified}


def enforce_text(text, inv):
    """Remove unverified citations (right or cut). Returns
    (new_text, removed entries). Replacements run last-first so
    spans stay valid."""
    removed = []
    spans = []
    for c in extract_citations(text):
        ok, basis = verify(c, inv)
        if not ok:
            entry = {k: c[k] for k in ("raw", "kind", "instrument", "section")}
            entry["basis"] = basis
            removed.append(entry)
            spans.append((c["start"], c["end"]))
    new_text = text
    for start, end in sorted(spans, reverse=True):
        new_text = new_text[:start] + REMOVAL_MARKER + new_text[end:]
    return new_text, removed


def internal_references(text, citations):
    """The organization's own document references - placeholders
    by design, flag and keep. Citation spans are excluded so a
    verified reference is never double-counted."""
    spans = [(c["start"], c["end"]) for c in citations]

    def inside(pos):
        return any(s <= pos < e for s, e in spans)

    matches = []
    patterns = [
        # The Genesis sister-procedure subtype first, so it is
        # always captured whole: [INTERNAL SOP PLACEHOLDER: name].
        r"\[INTERNAL SOP PLACEHOLDER:[^\]]+\]",
        r"\bSOP-[A-Z]{1,4}-\d{2,4}\b",
        r"\b[A-Z]{2,4}-\d{3,4}\b",
        r"\[[^\]]{0,120}placeholder[^\]]{0,120}\]",
    ]
    for pat in patterns:
        flags = re.IGNORECASE if "placeholder" in pat.lower() else 0
        for m in re.finditer(pat, text, flags):
            if not inside(m.start()):
                matches.append((m.start(), m.end(), m.group(0)))
    # A short match inside a longer one is the same reference
    # (QA-001 inside SOP-QA-001): keep the longest span at each
    # location.
    matches.sort(key=lambda t: (t[0], -(t[1] - t[0])))
    refs, kept_spans = [], []
    for start, end, raw in matches:
        if any(s <= start and end <= e for s, e in kept_spans):
            continue
        kept_spans.append((start, end))
        if raw not in refs:
            refs.append(raw)
    return refs


def gap_markers(text):
    out = []
    for _kind, body in _MARKER_RE.findall(text):
        body = body.strip()
        if body not in out:
            out.append(body)
    return out


_REF_HEADING_RE = re.compile(
    r"^##\s+(?:\d+(?:\.\d+)?\.\s*)?References\b", re.IGNORECASE)
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.+?)\s*$")


def reference_entries(text):
    """The entries in the draft's References section: bulleted or
    numbered lines under the References heading, up to the next
    section heading. Only list lines count - a stray line of prose
    under the heading is not an entry."""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if _REF_HEADING_RE.match(ln.strip()):
            start = i + 1
            break
    if start is None:
        return []
    entries = []
    for ln in lines[start:]:
        if ln.startswith("## "):
            break
        m = _BULLET_RE.match(ln)
        if m and m.group(1):
            entries.append(m.group(1))
    return entries


def _content_tokens(text):
    """Significant words for title matching: four or more letters,
    or any token carrying a digit (Q9, 100-1, 2025)."""
    toks = set()
    for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]*", (text or "").upper()):
        if len(w) >= 4 or any(ch.isdigit() for ch in w):
            toks.add(w)
    return toks


def _title_matches_source(entry, sources):
    """Fuzzy title match against the packet's source names: the
    entry and a source name are the same document when most of
    the shorter one's significant words appear in the other, with
    at least four words in common. Deliberately conservative -
    this feeds a warning, never a removal."""
    etoks = _content_tokens(entry)
    if not etoks:
        return False
    for src in sources:
        stoks = _content_tokens(src.get("name", ""))
        if not stoks:
            continue
        shared = etoks & stoks
        if len(shared) >= 4 and len(shared) / min(len(etoks), len(stoks)) >= 0.6:
            return True
    return False


def unrecognized_references(text, inv, check):
    """References-section entries that match no packet source:
    not by a verified instrument they name, and not by title.
    A full title is invisible to the citation patterns above -
    an invented guidance cited by title only would otherwise pass
    the check entirely. Entries carrying a citation that failed
    verification are not listed here: they are already reported
    as unverified citations. Warning only - the flag list names
    them for the author's edit; nothing is removed."""
    out = []
    for entry in reference_entries(text):
        if _MARKER_RE.search(entry) or "citation removed" in entry:
            continue
        cits = extract_citations(entry)
        if any(verify(c, inv)[0] for c in cits):
            continue
        if cits:
            continue
        if _title_matches_source(entry, inv["sources"]):
            continue
        if entry not in out:
            out.append(entry)
    return out


def build_flag_list(session_dir, draft_text, inv, check, removed):
    """The flag list that travels with a Genesis Discussion Draft:
    what to correct, what to decide, and what the draft's
    citations rest on. Plain words, no scores."""
    intake = {}
    intake_path = os.path.join(session_dir, "genesis_intake.json")
    if os.path.exists(intake_path):
        try:
            intake = json.load(open(intake_path))
        except (OSError, json.JSONDecodeError):
            intake = {}
    lines = ["# Flag list - for your later edit", ""]
    lines.append("This draft was built from public regulations "
                 "only, and it is a Discussion Draft by design. Work through "
                 "this list in your own document system; the draft is not "
                 "final until every item below is resolved.")
    lines.append("")
    lines.append("## The run")
    if intake:
        lines.append(f"- Archetype: {intake.get('archetype_label', '?')}")
        lines.append(f"- Market: {intake.get('market_label', '?')}")
        funcs = intake.get("functions", [])
        lines.append(f"- Functions: {', '.join(funcs) if funcs else '(none selected)'}")
        lines.append(f"- Procedure: {intake.get('topic_title', '?')}")
        lines.append(f"- Document title: {intake.get('title', '?')}")
    else:
        lines.append("- (No intake record in this session.)")
    lines.append("")
    lines.append("## Coverage - what this packet does and does not cover")
    covers = intake.get("coverage_covers", [])
    for c in covers:
        lines.append(f"- Covers: {c}")
    cov_flags = intake.get("coverage_flags", [])
    if cov_flags:
        lines.append("Flagged for this run - the selections below run past "
                     "what the packet's sources cover. The draft does not "
                     "cover them, and they are not filled in:")
        for fl in cov_flags:
            lines.append(f"- {fl}")
    else:
        lines.append("- No coverage deficits were flagged for this run: "
                     "the selections sit inside what the packet covers.")
    lines.append("")
    lines.append("## Sources the packet was built from")
    if inv["sources"]:
        for src in inv["sources"]:
            status = src.get("read_status") or src.get("fetch_status") or "?"
            lines.append(f"- {src.get('name', '?')} - read status: {status}")
    else:
        lines.append("- (Source list unavailable.)")
    # A source can read OK and still contribute nothing to the
    # packet (no section matched, or every section was trimmed).
    # The packet's final state is authoritative: name such sources
    # here, so a read-OK source is never silently absent from the
    # draft's grounding.
    pkt_path = os.path.join(session_dir, "source_packet.json")
    if os.path.exists(pkt_path):
        try:
            pkt = json.load(open(pkt_path))
            counts = {}
            for sec in pkt.get("relevant_sections", []):
                counts[sec.get("source")] = counts.get(sec.get("source"), 0) + 1
            for s in pkt.get("sources", []):
                if (s.get("status") in ("OK", "PARTIAL")
                        and counts.get(s["name"], 0) == 0):
                    lines.append(
                        f"- Source contributed no sections to this packet: "
                        f"{s['name']}. The draft is not grounded in it.")
        except (OSError, json.JSONDecodeError):
            pass
    lines.append("")
    lines.append("## Regulatory citations")
    verified = check.get("verified", [])
    lines.append(f"- Verified against the packet: {len(verified)}")
    seen = []
    for v in verified:
        label = f"  - {v['raw']} ({v['basis']})"
        if label not in seen:
            seen.append(label)
    lines.extend(seen[:40])
    if len(seen) > 40:
        lines.append(f"  - ... and {len(seen) - 40} more verified citations")
    lines.append(f"- Removed by the source check: {len(removed)}")
    for r in removed:
        lines.append(f"  - Removed: \"{r['raw']}\" - {r['basis']}. The removed "
                     f"text is recorded here only; it does not stand in the draft.")
    lines.append("- How verification works: a citation is verified when its "
                 "instrument is a packet source, at the exact revision the "
                 "packet carries (a citation to ICH Q9 does not verify "
                 "against an ICH Q9(R1) packet); a CFR section must also "
                 "appear in the packet text. A pinpoint section inside a "
                 "guidance document is verified at instrument level only - "
                 "confirm the section number against the source in your "
                 "later edit.")
    lines.append("")
    lines.append("## References in the draft")
    unrec = unrecognized_references(draft_text, inv, check)
    if unrec:
        lines.append("Unrecognized references - confirm or remove in your "
                     "edit. These entries in the draft's References section "
                     "match no packet source, by instrument or by title. "
                     "The source check does not remove title entries "
                     "automatically; an entry that should not be there is "
                     "yours to delete:")
        for e in unrec:
            lines.append(f"- {e}")
    else:
        lines.append("- Every entry in the draft's References section "
                     "matches a packet source.")
    lines.append("")
    lines.append("## Internal references - placeholders by design")
    refs = internal_references(draft_text, extract_citations(draft_text))
    if refs:
        lines.append("These name your organization's own documents. They are "
                     "placeholders: correct each one to the real document, or "
                     "delete it, in your later edit.")
        for r in refs:
            lines.append(f"- {r}")
    else:
        lines.append("- None found in the draft.")
    lines.append("")
    lines.append("## Decisions still open")
    markers = gap_markers(draft_text)
    if markers:
        lines.append("Each flagged gap in the draft is a decision only your "
                     "organization can make:")
        for m in markers:
            lines.append(f"- {m}")
    else:
        lines.append("- No gap markers remain in the draft.")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Citation check.")
    ap.add_argument("--session-dir", required=True)
    ap.add_argument("--draft", default="draft_final.md")
    ap.add_argument("--enforce", action="store_true",
                    help="rewrite the draft with unverified citations removed, "
                         "append the flag list, and write genesis_flags.md")
    ap.add_argument("--out", default=None,
                    help="JSON report path (default: citation_check.json, or "
                         "citation_check_final.json with --enforce)")
    ap.add_argument("--version", action="store_true")
    args = ap.parse_args()
    if args.version:
        print(f"citation_check {VERSION}")
        return 0
    session_dir = args.session_dir
    draft_path = os.path.join(session_dir, args.draft)
    if not os.path.exists(draft_path):
        print(f"CITATION CHECK BLOCKED: no draft at {draft_path}", file=sys.stderr)
        return 2
    with open(draft_path, encoding="utf-8") as f:
        text = f.read()
    inv = load_inventory(session_dir)
    removed = []
    if args.enforce:
        text, removed = enforce_text(text, inv)
    check = check_text(text, inv)
    flags = build_flag_list(session_dir, text, inv, check, removed)
    if args.enforce:
        if "## Flag list" not in text:
            flag_body = flags.split("\n", 1)[1] if "\n" in flags else flags
            text = (text.rstrip() + "\n\n## Flag list "
                    "(for your later edit)\n\n" + flag_body)
        with open(draft_path, "w", encoding="utf-8") as f:
            f.write(text)
        twin = draft_path.replace(".md", ".txt")
        if twin != draft_path:
            with open(twin, "w", encoding="utf-8") as f:
                f.write(text)
        with open(os.path.join(session_dir, "genesis_flags.md"), "w",
                  encoding="utf-8") as f:
            f.write(flags)
    out_name = args.out or ("citation_check_final.json" if args.enforce
                            else "citation_check.json")
    report = {"draft": args.draft, "enforced": bool(args.enforce),
              "verified": check["verified"], "unverified": check["unverified"],
              "removed": removed,
              "unrecognized_references": unrecognized_references(
                  text, inv, check),
              "internal_references": internal_references(
                  text, extract_citations(text)),
              "gap_markers": gap_markers(text)}
    with open(os.path.join(session_dir, out_name), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({"verified": len(check["verified"]),
                      "unverified": len(check["unverified"]),
                      "removed": len(removed),
                      "unrecognized_references": len(
                          report["unrecognized_references"]),
                      "internal_references": len(report["internal_references"]),
                      "gap_markers": len(report["gap_markers"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
