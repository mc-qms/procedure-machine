#!/usr/bin/env python3
"""draft.py - build draft v1 from a source packet + template.

Deterministic Python only, v1. No LLM call is made by this script.
The mid-tier model wording pass (regulated plain English, imperative
voice, conditions before actions) is a separate, optional step, and
is NOT run here. This script assembles the structural draft: template
order, verbatim packet excerpts, gap markers, no invented content.

Usage:
  python draft.py build --session <session_id>
  python draft.py build --session-dir <path>
  python draft.py --version

Input (in the session folder):
  source_packet.json   - built by packet.py. The only source of
                         content, plus the template file.

Rules:
- Input is packet + template only. No other sources, no internet.
- Incorporate only issues dispositioned Incorporate in the packet.
  Any other disposition is excluded, and the exclusion is recorded.
- Never invent parameters, criteria, responsibilities, records, or
  requirements. Never fill a packet gap.
- A missing required section gets a gap marker, not invented text:
  [AUTHOR INPUT REQUIRED: ...]
  Three exceptions, all deterministic packet data, not invention.
  Records: when no source has a Records section, draft.py fills
  it from the packet's own source list — the source documents are
  the records for a guidance-derived SOP (Manuel, Nov 11, 2026:
  "records can literally be the guidelines"). References: the
  same — when no source has a References section, the packet's
  source list is the References section (Manuel, Nov 11, 2026:
  "References — ICH Q7 itself at minimum"). Responsibilities:
  when no source has a Responsibilities section, draft.py fills
  it from the packet's intended_user — the audience statement is
  where the user already said who does what (Manuel, Nov 11,
  2026: "why do I have to fill in responsibilities if I'm saying
  who its for in the packet?").
- Preserve template structure and required headings. A template is
  a scaffold, not a checklist to inflate.
- Output is labelled Discussion Draft, per the audit-output
  draft-maturity gate. It is not a clean copy, and formal appearance
  must not imply approval.

Outputs (in the session folder):
  draft_v1.md
  draft_v1.txt   (same content, for docsrc.py check)
  draft_v1_summary.json

Exit codes: 0 = draft built (including an all-gaps skeleton when the packet has no usable sections), 2 = missing packet.
"""

import argparse
import datetime
import json
import os
import re
import sys

VERSION = "1.0"


def die(msg, code=2):
    print(msg)
    sys.exit(code)


def load_json(path, what):
    if not os.path.exists(path):
        die(f"Missing input: {path} ({what}). Run packet.py first.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def norm_stripped(s):
    """norm() plus trailing numbers removed. PDF section anchors
    often carry a page number ("REFERENCES 1901"), which must not
    stop the title matching the template's "References". A source
    section titled "Glossary" canonicalizes to "definitions":
    guidance documents keep their terms in a glossary, templates
    ask for definitions, and they are the same section — without
    this, relevance dropped the glossary and the draft had no
    definitions to work from (found Nov 11, 2026, test-027: the
    live Q7 run asked the human for definitions and to "define
    what 'quality' entails" while Q7's Glossary sat unselected).
    The same helper exists in packet.py; keep them in sync."""
    t = re.sub(r" \d+$", "", norm(s))
    return "definitions" if t == "glossary" else t


def strip_heading(text, title):
    """Remove the section's own heading line from verbatim text, so
    the template heading is not duplicated. Only the first line,
    only if it matches the title/number."""
    lines = text.splitlines()
    if not lines:
        return text
    first = norm(lines[0])
    if norm(title) in first or first.startswith(norm(title).split()[0] if title else ""):
        # Only strip if the first line is short and looks like a heading.
        if len(lines[0]) <= 120:
            return "\n".join(lines[1:]).strip()
    return text.strip()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build draft v1 from a packet.")
    ap.add_argument("command", nargs="?", default="build", choices=["build"])
    ap.add_argument("--session", help="session id (folder sessions/<id>)")
    ap.add_argument("--session-dir", help="session folder path (overrides --session)")
    ap.add_argument("--version", action="store_true")
    args = ap.parse_args(argv)

    if args.version:
        print(f"draft {VERSION}")
        return 0

    if args.session_dir:
        session_dir = args.session_dir
    elif args.session:
        session_dir = os.path.join("sessions", args.session)
    else:
        session_dir = os.path.join("sessions", "default")

    packet = load_json(os.path.join(session_dir, "source_packet.json"), "source_packet.json")

    # Only Incorporate dispositions are included.
    incorporate_titles = set()
    excluded = []
    for d in packet.get("change_dispositions", []):
        issue = d.get("issue", "")
        m = re.match(r"Relevant section: (.+?) \(", issue)
        if not m:
            continue
        title = m.group(1)
        if d.get("disposition") == "Incorporate":
            incorporate_titles.add(norm_stripped(title))
        else:
            excluded.append({"title": title, "disposition": d.get("disposition")})

    by_title = {}
    for r in packet.get("relevant_sections", []):
        by_title.setdefault(norm_stripped(r["title"]), r)

    sections_out = []
    gaps_out = list(packet.get("gaps", []))
    for rs in packet.get("required_sections", []):
        title = rs["title"]
        rel = by_title.get(norm_stripped(title))
        if rel is not None and norm_stripped(title) in incorporate_titles:
            sections_out.append({
                "id": rs["id"], "title": title, "status": "present",
                "text": strip_heading(rel["text"], title),
                "source": rel["source"],
                "section_id": rel["section_id"],
            })
            continue
        if norm(title) == "records":
            # The source documents ARE the records, even when a
            # Records-titled section exists in the packet but was
            # not dispositioned Incorporate: the fill lists the
            # sources, it does not write the section's content in
            # as a requirement, so the disposition does not block
            # it. (Found in test-022: a Records section existed
            # but was not Incorporate, and the old order put the
            # "excluded" marker on Records instead of filling it.)
            srcs = [s.get("name", "?") for s in packet.get("sources", [])
                    if s.get("status") in ("OK", "PARTIAL")]
            if srcs:
                sections_out.append({
                    "id": rs["id"], "title": title, "status": "present",
                    "text": ("Records: the source documents this "
                             "procedure was built from: " +
                             "; ".join(srcs) + "."),
                    "source": "packet sources",
                })
                continue
        if norm(title) == "references":
            # Same rule as Records, same reason (Manuel, Nov 11,
            # 2026: "References — ICH Q7 itself at minimum"): when
            # no source has a References section, the packet's own
            # source list IS the References section. A real
            # References section that IS Incorporate still wins
            # (handled above).
            srcs = [s.get("name", "?") for s in packet.get("sources", [])
                    if s.get("status") in ("OK", "PARTIAL")]
            if srcs:
                sections_out.append({
                    "id": rs["id"], "title": title, "status": "present",
                    "text": ("References: the source documents this "
                             "procedure was built from: " +
                             "; ".join(srcs) + "."),
                    "source": "packet sources",
                })
                continue
        if norm(title) == "responsibilities":
            # The intended user IS the responsibilities, when the
            # user said who does what while describing who the
            # document is for (Manuel, Nov 11, 2026: "why do I
            # have to fill in responsibilities if I'm saying who
            # its for in the packet?"). The intended_user is
            # author-supplied text from the description, not
            # invented. A real Responsibilities section that IS
            # Incorporate still wins (handled above); otherwise
            # the audience statement fills it, and the model
            # revision may refine it into proper statements.
            who = (packet.get("intended_user") or "").strip()
            if who:
                sections_out.append({
                    "id": rs["id"], "title": title, "status": "present",
                    "text": f"Responsibilities: {who}",
                    "source": "packet intended_user",
                })
                continue
        if rel is None:
            # v24 (Gemini Argon review, test-044): NO negative
            # priming. The section heading stays (Python owns the
            # schema) but the body is empty — the drafting model
            # fills it from the packet or marks inline where it
            # truly cannot. The old text ("not present in any OK
            # source. Do not invent.") told the model a
            # deterministic check had already proved the section
            # absent, which primed a conservative model to leave
            # the whole section as a gap even when the packet held
            # the content under a different title (external
            # guidelines almost never use SOP section headers).
            # The backstop is in app.py _revise: after the model
            # runs, a section still empty gets the gap marker, so
            # a section never silently vanishes.
            sections_out.append({
                "id": rs["id"], "title": title, "status": "missing",
                "text": "",
            })
            continue
        sections_out.append({
            "id": rs["id"], "title": title, "status": "excluded",
            "text": f"[AUTHOR INPUT REQUIRED: {title} - relevant section "
                    f"was not dispositioned Incorporate, so it was not "
                    f"included in this draft.]",
        })
        excluded.append({"title": title, "disposition": "not Incorporate"})

    # Prune the packet's gap list against what was actually built
    # (v28, test-048): gaps_out starts as every packet gap, but the
    # deterministic fills above (Records, References,
    # Responsibilities) resolve some of them, and the stale list
    # went into "## Unresolved items" anyway — a draft could list a
    # section as missing directly under the filled section. A gap
    # naming a required section that is present is not a gap.
    _present = {norm_stripped(s["title"]) for s in sections_out
                if s["status"] == "present"}

    def _gap_section_title(g):
        w = g.get("what_is_missing", "")
        if w.startswith("Required section:"):
            return norm_stripped(w.split(":", 1)[1].strip())
        return None

    gaps_out = [g for g in gaps_out
                if _gap_section_title(g) is None
                or _gap_section_title(g) not in _present]

    # No usable sections is not a failure: the draft is built anyway, as
    # all flagged gaps. Halting here would contradict "Don't Halt, Flag
    # Gaps" — the human answers the gaps in section 3 of the app.
    # (Nov 11, 2026: the live end-to-end test hit the old die() here on
    # the default example run, whose sources have no usable sections,
    # and the whole demo dead-ended on an error instead of reaching
    # the human. The skeleton draft is the fix.)
    if not any(s["status"] == "present" for s in sections_out):
        print("NOTE: no sections present in the packet — the draft is "
              "all flagged gaps. This is a valid Discussion Draft; "
              "the human answers the gaps.")

    doc_type = packet.get("document_type", "SOP")
    lines = []
    lines.append(f"# {doc_type} — Discussion Draft")
    lines.append("")
    lines.append(f"Status: Discussion Draft. Not a clean copy. Formal appearance "
                 f"does not imply approval.")
    lines.append(f"Packet: {packet.get('packet_id')}  Template: {packet.get('template_id')}")
    lines.append(f"Authority route: {packet.get('authority_route')}  "
                 f"Work mode: {packet.get('work_mode')}")
    lines.append(f"Purpose: {packet.get('purpose')}")
    lines.append(f"Scope: {packet.get('scope_in')}")
    if packet.get("scope_out"):
        lines.append(f"Out of scope: {packet.get('scope_out')}")
    lines.append("")
    for s in sections_out:
        lines.append(f"## {s['id']}. {s['title']}")
        lines.append("")
        lines.append(s["text"])
        lines.append("")
    if gaps_out:
        lines.append("## Unresolved items")
        lines.append("")
        for g in gaps_out:
            lines.append(f"- {g.get('what_is_missing')}: {g.get('why_it_matters')}")
        lines.append("")

    content = "\n".join(lines)
    md_path = os.path.join(session_dir, "draft_v1.md")
    txt_path = os.path.join(session_dir, "draft_v1.txt")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(content)

    summary = {
        "draft": "v1",
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "packet_id": packet.get("packet_id"),
        "template_id": packet.get("template_id"),
        "document_type": doc_type,
        "status": "Discussion Draft",
        "sections": [{"id": s["id"], "title": s["title"], "status": s["status"]} for s in sections_out],
        "excluded": excluded,
        "gaps": gaps_out,
        "chars": len(content),
        "model_wording_pass": None,
        "model_wording_note": (
            "No model wording pass was run in draft.py v1. "
            "The draft is a structural assembly of verbatim packet "
            "excerpts under template headings. The mid-tier model "
            "wording pass is a separate, optional step."
        ),
    }
    with open(os.path.join(session_dir, "draft_v1_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("DRAFT v1")
    print(f"Document type: {doc_type}  Template: {packet.get('template_id')}")
    for s in sections_out:
        print(f"  - [{s['status']}] {s['id']} {s['title']}")
    print(f"Excluded (not Incorporate): {len(excluded)}")
    print(f"Gaps: {len(gaps_out)}")
    print(f"Chars: {len(content)}")
    print(f"Wrote: {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
