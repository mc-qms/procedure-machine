#!/usr/bin/env python3
"""packet.py - build one condensed source packet for the Procedure Machine.

Deterministic Python only, v1. No LLM call is made by this script.
Model relevance calls are a separate, optional step (mid-tier, one
call per section, yes/no + one-line reason); they are recorded in
`model_relevance_calls` when run, and are empty here. This script
does not pretend a model call happened.

Usage:
  python packet.py build --session <session_id> --template <template_id>
  python packet.py build --session-dir <path> --template <path-or-id>
  python packet.py --version

Inputs (in the session folder):
  purpose_scope.json   - confirmed purpose / scope / type / template /
                         authority route / work mode, verbatim.
  docsrc_cache.json    - docsrc.py 2.1 cache. Run docsrc.py intake in
                         the session folder first, so the cache lands
                         here (per-session cache, not a shared file).

Template:
  --template may be a path to a template file, or an id looked up in
  ./templates/ (<id>.json or <id>.md). A template JSON is:
    {"template_id": "...", "document_type": "SOP",
     "required_sections": [{"id": "1", "title": "Purpose"}, ...]}
  A template .md/.txt lists required sections as headings, one per
  line, in order. If no template file is found, the built-in SOP
  default is used, and the packet records that the template was a
  built-in default. Demo scope, revised Nov 11, 2026: only SOP
  and Test Method are built.
  Other types (Policy, Work Instruction, Protocol) are rejected,
  not built. Test Methods were briefly SOP-only; Manuel reversed
  that — the two types are too similar to separate by a hard gate.

Outputs (in the session folder):
  source_packet.json
  source_packet.md   (human-readable summary + verbatim excerpts)

Limits:
- Target 8,000-12,000 tokens. Hard cap 20,000 tokens.
- Token estimate method: chars / 4, stated in the packet. It is an
  estimate, not a model tokenizer count.
- If relevant sections exceed the cap, do NOT silently drop sections.
  Write the packet flagged over_cap and exit non-zero, list what
  would exceed it, and let the relevance step trim it — or ask the
  user to narrow scope, drop a source, or confirm a shorter packet.
- Never truncate a section mid-sentence without flagging it truncated.
  This script never truncates: a section is included whole, or not
  at all, and the choice is recorded.
- If a required section is missing from all sources, list it in
  gaps[] and continue. Do not invent it.

Selection rule, deterministic first:
1. Exact section title / number matches to template sections.
2. Keyword matches to purpose / scope terms in section titles and text.
3. Model relevance calls, only if still needed - not run in v1.

Chunk fallback (v1.1): a usable source with no detectable sections
(flat web article, plain text without headings) is split into
~2,000-char passages, titled "Passage N", and selected by the
same keyword rule. Without this, such a source contributes
nothing to the packet even when its content is relevant.

Only OK sources, or the read pages of a PARTIAL source, are used.
UNREADABLE sources are listed in sources[] and excluded from
relevant_sections[], with the reason recorded.

Exit codes: 0 = packet built, 2 = usage / missing input / over cap.
On over-cap the packet is still written, flagged "over_cap": true,
so the relevance step can trim it; the exit code still says it does
not fit yet. Nothing is silently dropped.
"""

import argparse
import datetime
import json
import os
import re
import sys
import uuid

VERSION = "1.1"
TARGET_TOKENS = (8000, 12000)
HARD_CAP_TOKENS = 20000
# Token estimate: chars / 4. Stated in the packet; not a tokenizer count.
CHARS_PER_TOKEN = 4
# Chunk fallback: a section-less source is split into passages of at
# most this many chars, preferring blank-line boundaries.
CHUNK_CHARS = 2000

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "with",
    "by", "is", "are", "be", "this", "that", "it", "as", "at", "from",
    "into", "per", "using", "use", "used", "how", "what", "when",
}

BUILTIN_TEMPLATES = {
    "SOP": [
        ("1", "Purpose"),
        ("2", "Scope"),
        ("3", "Responsibilities"),
        ("4", "Procedure"),
        ("5", "Records"),
        ("6", "References"),
    ],
    "Test Method": [
        ("1", "Purpose"),
        ("2", "Scope"),
        ("3", "Responsibilities"),
        ("4", "Procedure"),
        ("4.1", "Sample Quantity"),
        ("4.2", "Standard Preparation"),
        ("4.3", "Sample Preparation"),
        ("4.4", "Analysis"),
        ("4.5", "Calculations"),
        ("5", "Records"),
        ("6", "References"),
    ],
}


def die(msg, code=2):
    print(msg)
    sys.exit(code)


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
    The same helper exists in draft.py; keep them in sync."""
    t = re.sub(r" \d+$", "", norm(s))
    return "definitions" if t == "glossary" else t


def token_estimate(chars):
    return max(1, chars // CHARS_PER_TOKEN)


def load_json(path, what):
    if not os.path.exists(path):
        die(f"Missing input: {path} ({what}). Run the earlier intake step first.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_template(template_arg, document_type, base_dir):
    """Return (template_id, required_sections, template_source)."""
    candidates = []
    if template_arg:
        candidates.append(template_arg)
        candidates.append(os.path.join("templates", template_arg))
        candidates.append(os.path.join("templates", template_arg + ".json"))
        candidates.append(os.path.join("templates", template_arg + ".md"))
        candidates.append(os.path.join(base_dir, template_arg))
    for cand in candidates:
        if cand and os.path.exists(cand):
            if cand.lower().endswith(".json"):
                data = load_json(cand, "template")
                secs = [(str(s.get("id", "")), s.get("title", "")) for s in data.get("required_sections", [])]
                return data.get("template_id", os.path.basename(cand)), secs, cand
            # .md / .txt: headings are required sections, in order.
            secs = []
            with open(cand, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    m = re.match(r"^#{1,3}\s*(?:(\d+(?:\.\d+)*)\.?\s+)?(.+)$", line)
                    if m:
                        secs.append((m.group(1) or "", m.group(2).strip()))
            if secs:
                return os.path.splitext(os.path.basename(cand))[0], secs, cand
    # Built-in default.
    secs = BUILTIN_TEMPLATES.get(document_type) or BUILTIN_TEMPLATES["SOP"]
    return f"builtin-{document_type.lower().replace(' ', '-')}", list(secs), "built-in default"


def keywords(text):
    words = re.findall(r"[a-z][a-z0-9-]{2,}", (text or "").lower())
    return {w for w in words if w not in STOPWORDS}


def merge_table_rows(sections, lines):
    """Merge runs of table-row 'sections' into one table section.

    Some PDFs (compendial chapters especially) give docsrc anchors
    that are table rows, not headings: short lines of numbers with
    no letters (e.g. '1.72 — — 4.09 6.84 — 8.96 — 11.45'). Each row
    becomes its own 'section', so the table's data is scattered
    across a dozen junk sections that selection drops one by one
    and the packet check fetches under garbage titles (found on
    USP <791>, test-059: Table 2 never reached the packet as
    usable content, and several draft markers were really about
    its absence). A run of >= 3 consecutive letter-less sections
    is merged into a single section spanning the run; when a
    'Table N.' caption line sits just above the run, the merged
    section starts there and takes the caption as its title, so
    the values arrive as content the selection rules and the
    drafter can actually use. Real headings always contain
    letters, so prose sections are never merged.
    """
    def is_row(title):
        t = (title or "").strip()
        return len(t) >= 3 and not any(c.isalpha() for c in t)

    merged = []
    i = 0
    while i < len(sections):
        if is_row(sections[i][2]):
            j = i
            while j + 1 < len(sections) and is_row(sections[j + 1][2]):
                j += 1
            if j - i + 1 >= 3:
                start, end = sections[i][0], sections[j][1]
                title = None
                for ln in range(max(0, start - 6), start):
                    if ln < len(lines) and len(lines[ln]) > 1:
                        txt = (lines[ln][1] or "").strip()
                        if (txt.lower().startswith("table ")
                                and any(c.isdigit() for c in txt)):
                            title = txt
                            start = ln
                merged.append((start, end, title or "Table data (rows)",
                               sections[i][3]))
                i = j + 1
                continue
        merged.append(sections[i])
        i += 1
    return merged


def chunk_lines(rec):
    """Split a section-less source into ~2,000-char passages by line ranges.

    Used only when a usable source has no detectable sections (no
    anchors) — flat web articles, plain text without headings. The
    packet builder otherwise has nothing to select from, and a source
    with real content produces an empty packet (found Nov 11, 2026:
    a real espresso-cleaning guide read as 0 sections, packet tokens 1).

    Lines are the unit: accumulate whole lines into a chunk until
    ~CHUNK_CHARS, preferring to close at a blank line. A chunk is
    never closed below 500 chars unless a single line exceeds the
    limit (then that line is its own chunk). A chunk boundary can
    fall mid-paragraph for long unbroken text; the chunk is then
    included whole, never truncated mid-sentence by selection.
    Returns [(start_line, end_line), ...] ranges into rec["lines"].
    """
    lines = rec.get("lines", [])
    texts = [entry[1] if len(entry) > 1 else "" for entry in lines]
    ranges = []
    start = 0
    cur = 0
    for i, t in enumerate(texts):
        if cur > 0 and cur + len(t) + 1 > CHUNK_CHARS:
            # Prefer a blank-line boundary: close at the last blank
            # line inside the current chunk if there is one.
            cut = None
            for j in range(i - 1, start, -1):
                if not texts[j].strip():
                    cut = j + 1
                    break
            if cut is not None and cut - start >= 1 and cur >= 500:
                ranges.append((start, cut))
                start = cut
                cur = sum(len(x) + 1 for x in texts[cut:i])
            elif cur >= 500:
                ranges.append((start, i))
                start = i
                cur = 0
        if cur == 0:
            start = i
        cur += len(t) + 1
    if cur > 0:
        ranges.append((start, len(texts)))
    return ranges


def section_text(rec, start_line, end_line):
    # docsrc lines are [page, text, ...] - page may be None, and a
    # third element may be present. Only the first two are used here.
    lines = rec.get("lines", [])
    out = []
    for entry in lines[start_line:end_line]:
        out.append(entry[1] if len(entry) > 1 else "")
    return "\n".join(out).strip()


def section_page(rec, start_line, end_line):
    pages = [l[0] for l in rec.get("lines", [])[start_line:end_line] if l and l[0]]
    return pages[0] if pages else None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build a condensed source packet.")
    ap.add_argument("command", nargs="?", default="build", choices=["build"])
    ap.add_argument("--session", help="session id (folder sessions/<id>)")
    ap.add_argument("--session-dir", help="session folder path (overrides --session)")
    ap.add_argument("--template", help="template id or path")
    ap.add_argument("--version", action="store_true")
    args = ap.parse_args(argv)

    if args.version:
        print(f"packet {VERSION}")
        return 0

    if args.session_dir:
        session_dir = args.session_dir
    elif args.session:
        session_dir = os.path.join("sessions", args.session)
    else:
        session_dir = os.path.join("sessions", "default")

    purpose = load_json(os.path.join(session_dir, "purpose_scope.json"), "purpose_scope.json")
    cache = load_json(os.path.join(session_dir, "docsrc_cache.json"), "docsrc_cache.json")

    document_type = purpose.get("document_type") or purpose.get("type") or "SOP"
    # Demo scope is SOPs and Test Methods (revised Nov 11, 2026).
    # Flag, do not silently build, any other type.
    if document_type not in ("SOP", "Test Method"):
        die(f"Out of demo scope: document_type is {document_type!r}. "
            f"The demo builds SOPs and Test Methods only.")
    template_id, required, template_source = load_template(
        args.template or purpose.get("template_id") or purpose.get("template"),
        document_type, session_dir,
    )

    # --- sources -------------------------------------------------------
    # Dedupe by content hash (test-040, Nov 12, 2026): the same
    # document can reach the session twice — once as a fetched
    # link, once as an upload (a download renamed by the browser,
    # or the link left in the box). packet.py used to build
    # sections from every file in the cache, so the packet doubled
    # (Q1: 72,092 tokens from one copy, 144,184 from two) and the
    # trim chain could not bring it under cap. Two files with the
    # same sha256 are the same document; keep the first and record
    # the rest as duplicates (visible in the packet, not silent).
    sources = []
    usable = []  # (name, rec) for OK sources, or PARTIAL read pages
    duplicate_sources = []
    seen_sha = {}
    for name, rec in cache.get("files", {}).items():
        status = rec.get("status", "UNREADABLE")
        sha = rec.get("sha256")
        if sha and sha in seen_sha:
            duplicate_sources.append({
                "name": name,
                "sha256": sha,
                "duplicate_of": seen_sha[sha],
                "status": status,
            })
            continue
        if sha:
            seen_sha[sha] = name
        sources.append({
            "name": name,
            # Provisional: the fetch-record pass below upgrades
            # fetched sources to "link" with their URL. (The value
            # used to be computed against an empty list — finding
            # 16 — which made this dead code that always said
            # "upload" anyway; now it says so plainly.)
            "source_kind": "upload",
            "url": None,
            "sha256": rec.get("sha256"),
            "status": status,
            "pages": rec.get("pages"),
            "chars": rec.get("chars", 0),
            "sections": len(rec.get("anchors", [])),
        })
        if status == "OK":
            usable.append((name, rec))
        elif status == "PARTIAL":
            usable.append((name, rec))  # only read pages are used, below

    # Attach fetch URLs where a fetch record exists.
    fetch_path = os.path.join(session_dir, "fetch_record.json")
    if os.path.exists(fetch_path):
        try:
            with open(fetch_path, encoding="utf-8") as f:
                fetch_records = json.load(f)
            by_name = {}
            for r in fetch_records:
                saved = r.get("saved_as", "")
                by_name[os.path.basename(saved)] = r
            for s in sources:
                r = by_name.get(s["name"])
                if r:
                    s["source_kind"] = "link"
                    s["url"] = r.get("final_url") or r.get("url")
        except (json.JSONDecodeError, OSError):
            pass

    sources_chars_total = sum(s["chars"] for s in sources)

    # --- selection -----------------------------------------------------
    purpose_text = " ".join([
        str(purpose.get("purpose", "")),
        str(purpose.get("scope_in", "")),
        str(purpose.get("scope_out", "")),
    ])
    terms = keywords(purpose_text)
    # norm_stripped, not norm: it canonicalizes synonyms
    # ("Glossary" -> "definitions") and strips trailing page
    # numbers, so the template side and the source side match on
    # the same keys. Every lookup below uses norm_stripped.
    template_titles = {norm_stripped(title): (sid, title) for sid, title in required}

    relevant = []
    selected_ranges = []  # (source, start, end) already included
    chunked_sources = []  # sources with no sections, split into passages
    for name, rec in usable:
        anchors = rec.get("anchors", [])
        lines = rec.get("lines", [])
        # A source with no detectable sections (flat web article, plain
        # text without headings) is chunked into passages and treated
        # as sections titled "Passage N". Without this, such a source
        # contributes nothing to the packet even when its content is
        # relevant. Chunks are selected by the same keyword rule below;
        # they never template-match. A chunk is traceable by `find`
        # (its text is verbatim from the file); it is not a real
        # docsrc section, so `get` cannot retrieve it by name.
        sections = []
        if anchors:
            for idx, anchor in enumerate(anchors):
                start = anchor["line"]
                end = len(lines)
                for nxt in anchors[idx + 1:]:
                    if nxt["level"] <= anchor["level"]:
                        end = nxt["line"]
                        break
                sections.append((start, end, anchor.get("title", ""),
                                 anchor.get("id") or anchor.get("title", "")))
        else:
            chunked_sources.append(name)
            for n, (cs, ce) in enumerate(chunk_lines(rec), 1):
                sections.append((cs, ce, f"Passage {n}", f"chunk-{n}"))
        sections = merge_table_rows(sections, lines)
        for start, end, title, section_id in sections:
            # Skip a subsection already contained in an included parent
            # section (e.g. 4.1-4.5 inside Procedure). Otherwise the
            # same text is included twice and the packet inflates.
            # Full containment, not start-only (finding 19): a
            # merged table section starts at its caption line,
            # which can sit inside the preceding section's range
            # while its rows run past it — start-only containment
            # dropped exactly the tables the merge exists to save.
            if any(s == name and rs <= start and end <= re_ for s, rs, re_ in selected_ranges):
                continue
            text = section_text(rec, start, end)
            if not text:
                continue
            title_norm = norm_stripped(title)
            reason = None
            if title_norm in template_titles:
                reason = "template-match"
            else:
                # Keyword match on title, then on text.
                title_words = keywords(title)
                if title_words & terms:
                    reason = "keyword-match: " + ", ".join(sorted(title_words & terms))
                else:
                    text_words = keywords(text)
                    hit = text_words & terms
                    if hit:
                        reason = "keyword-match: " + ", ".join(sorted(hit))
            if reason is None:
                continue
            # PARTIAL sources: only include sections on read pages.
            # docsrc marks empty pages in rec["empty_pages"]; a section
            # whose lines are all on an empty page is skipped.
            if rec.get("status") == "PARTIAL" and rec.get("empty_pages"):
                pages = [l[0] for l in lines[start:end] if l and l[0]]
                if pages and all(p in rec["empty_pages"] for p in pages):
                    continue
            relevant.append({
                "source": name,
                "section_id": section_id,
                "title": title,
                "page": section_page(rec, start, end),
                "lines": [start, end],
                "text": text,
                "chars": len(text),
                "selection_reason": reason,
            })
            selected_ranges.append((name, start, end))

    # --- required sections present / missing ---------------------------
    # norm_stripped on both sides, for the same synonym reason as
    # template_titles above: a source "GLOSSARY" is present for a
    # template "Definitions".
    present_titles = {norm_stripped(r["title"]) for r in relevant}
    required_sections = []
    for sid, title in required:
        required_sections.append({
            "id": sid,
            "title": title,
            "status": "present" if norm_stripped(title) in present_titles else "missing",
        })

    # --- token cap -----------------------------------------------------
    # The cap is checked here, but the packet is still written below
    # (flagged over_cap) before returning 2. A big guideline can
    # legitimately over-select — Q1 (Nov 11, 2026): one ANNEXES
    # section alone is ~22,000 tokens — and the relevance step is
    # the designed remedy: it trims the packet, it does not need a
    # packet that already fits. Exiting without writing left the
    # app with nothing to trim and, worse, a stale packet from an
    # earlier run to draft from. Nothing is silently dropped here;
    # the over-cap listing is printed and the flag is in the packet.
    packet_text_chars = sum(r["chars"] for r in relevant)
    est_tokens = token_estimate(packet_text_chars)
    over_cap = est_tokens > HARD_CAP_TOKENS

    # --- gaps, dispositions, and the remaining packet fields -----------
    gaps = []
    change_dispositions = []
    for rs in required_sections:
        if rs["status"] == "missing":
            gaps.append({
                "what_is_missing": f"Required section: {rs['title']}",
                "why_it_matters": "Template requires this section; the draft cannot be complete without it.",
                "where_it_was_looked_for": ", ".join(s["name"] for s in sources) or "no sources",
                "what_would_close_it": "A source containing this section, or a user answer supplying its content.",
            })
            change_dispositions.append({
                "issue": f"Missing required section: {rs['title']}",
                "disposition": "Author/SME decision required",
                "basis": "Missing, not present in any OK source. Provisional, assigned by packet.py v1 deterministic rule.",
                "provisional": True,
            })
    for r in relevant:
        if norm_stripped(r["title"]) in template_titles:
            change_dispositions.append({
                "issue": f"Relevant section: {r['title']} ({r['source']})",
                "disposition": "Incorporate",
                "basis": "Template-required and present verbatim in a usable (OK or PARTIAL) source. Provisional, assigned by packet.py v1 deterministic rule; no scope test is performed — relevance alone does not justify Incorporate, this rule also requires template-required + usable source.",
                "provisional": True,
            })

    # Procedural elements: present / missing, as stated, never inferred.
    # A cue is recorded when found; the value is never filled in.
    cues = {
        "trigger": r"\b(when|upon|if|before|after|once)\b",
        "actor": r"\b(operator|analyst|technician|supervisor|user|personnel|role)\b",
        "action": r"\b(shall|must|add|mix|record|measure|verify|check|prepare)\b",
        "object": r"\b(sample|solution|equipment|record|form|result)\b",
        "condition": r"\b(if|unless|provided|while|until)\b",
        "record": r"\b(record|document|log|enter|form)\b",
        "handoff": r"\b(notify|inform|transfer|hand|submit|forward)\b",
    }
    procedural_elements = []
    for r in relevant:
        elements = {}
        for key, pat in cues.items():
            m = re.search(pat, r["text"], re.I)
            elements[key] = {
                "status": "present" if m else "missing",
                "evidence": m.group(0) if m else None,
            }
        procedural_elements.append({
            "section_id": r["section_id"],
            "title": r["title"],
            "elements": elements,
        })

    # Forms / fields, calculations / criteria: only what is explicitly
    # stated in the excerpt. No derivation, no inference.
    forms_and_fields = []
    calculations_criteria = []
    for r in relevant:
        for line in r["text"].splitlines():
            if re.search(r"(___+|\[ *\]|enter .* in|record .* in)", line, re.I):
                forms_and_fields.append({
                    "field": line.strip()[:120],
                    "section_id": r["section_id"],
                    "mapped_to": "not yet mapped (deterministic packet; the drafting model maps fields from the packet text)",
                    "units": None, "entry_format": None,
                    "supplied_criteria": None, "conditional_path": None,
                    "risk_flags": [],
                })
            if re.search(r"\d+\s*(mg|mL|µL|uL|g|°C|min|rpm|%|nm)\b", line):
                calculations_criteria.append({
                    "section_id": r["section_id"],
                    "statement": line.strip()[:200],
                    "variable_definitions": None, "units": None,
                    "dimensional_consistency": "not checked - requires model judgment",
                    "factors_dilutions": None, "rounding_authority": None,
                    "calculation_vs_reportable_precision": None,
                    "criteria_placement": None, "window_start_stop_inclusivity": None,
                })

    source_classifications = []
    source_scope_tests = []
    for r in relevant:
        is_required = norm_stripped(r["title"]) in template_titles
        source_classifications.append({
            "section_id": r["section_id"],
            "title": r["title"],
            "classification": "required content" if is_required else "optional",
            "comparison": "aligned" if is_required else "not applicable",
            "basis": "Deterministic v1 baseline only: template-required vs not. No further classification is performed.",
        })
        source_scope_tests.append({
            "section_id": r["section_id"],
            "subject_governed": document_type,
            "scope": purpose.get("scope_in"),
            "specific_sentence": r["text"].splitlines()[0][:200] if r["text"] else None,
            "internal_document_already_governing": "not stated in packet",
            "basis": "Deterministic v1 baseline. Do not generalize beyond stated scope.",
        })

    packet = {
        "packet_id": str(uuid.uuid4())[:8],
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "document_type": document_type,
        "template_id": template_id,
        "template_source": template_source,
        "purpose": purpose.get("purpose"),
        "scope_in": purpose.get("scope_in"),
        "scope_out": purpose.get("scope_out"),
        "intended_user": purpose.get("intended_user"),
        "authority_route": purpose.get("authority_route"),
        "work_mode": purpose.get("work_mode", "Draft/Format"),
        "communication_form": purpose.get("communication_form"),
        "routing_internal": {
            "route": purpose.get("authority_route"),
            "requested_mode": purpose.get("work_mode", "Draft/Format"),
            "authorized_mode": purpose.get("work_mode", "Draft/Format"),
            "communication_form": purpose.get("communication_form"),
            "sources_and_status": [(s["name"], s["status"]) for s in sources],
            "exclusions": purpose.get("scope_out"),
            "conflicts": [],
        },
        "sources": sources,
        "duplicate_sources": duplicate_sources,
        "chunked_sources": chunked_sources,
        "required_sections": required_sections,
        "relevant_sections": relevant,
        "procedural_elements": procedural_elements,
        "forms_and_fields": forms_and_fields,
        "calculations_criteria": calculations_criteria,
        "source_classifications": source_classifications,
        "source_scope_tests": source_scope_tests,
        "structured_elements": [],
        "change_dispositions": change_dispositions,
        "gaps": gaps,
        "exceptions": [],
        "model_relevance_calls": [],
        "model_relevance_note": (
            "No model relevance call was run in packet.py v1. "
            "Selection was deterministic (template-match, then keyword-match). "
            "Mid-tier relevance calls are a separate, optional step."
        ),
        "packet_chars": packet_text_chars,
        "packet_tokens_estimate": est_tokens,
        "over_cap": over_cap,
        "token_estimate_method": f"chars / {CHARS_PER_TOKEN} (estimate, not a model tokenizer count)",
        "sources_chars_total": sources_chars_total,
    }

    # --- write outputs -------------------------------------------------
    json_path = os.path.join(session_dir, "source_packet.json")
    md_path = os.path.join(session_dir, "source_packet.md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(packet, f, indent=2)

    lines = []
    lines.append(f"# Source Packet — {document_type}")
    lines.append("")
    lines.append(f"Packet: {packet['packet_id']}  Template: {template_id} ({template_source})")
    lines.append(f"Purpose: {purpose.get('purpose')}")
    lines.append(f"Intended user: {purpose.get('intended_user')}")
    lines.append(f"Authority route: {purpose.get('authority_route')}  Work mode: {packet['work_mode']}")
    lines.append(f"Packet size: {packet_text_chars} chars, ~{est_tokens} tokens "
                 f"(estimate: chars / {CHARS_PER_TOKEN})")
    lines.append(f"Sources: {len(sources)}  Relevant sections: {len(relevant)}  "
                 f"Gaps: {len(gaps)}")
    lines.append("")
    lines.append("## Required sections")
    for rs in required_sections:
        lines.append(f"- [{rs['status']}] {rs['id']} {rs['title']}")
    lines.append("")
    lines.append("## Gaps")
    for g in gaps:
        lines.append(f"- {g['what_is_missing']}: {g['why_it_matters']}")
    lines.append("")
    lines.append("## Relevant sections (verbatim)")
    for r in relevant:
        lines.append(f"### {r['source']} — {r['title']} "
                     f"(section {r['section_id']}, page {r['page']}, "
                     f"lines {r['lines'][0]}-{r['lines'][1]}, {r['selection_reason']})")
        lines.append("")
        lines.append(r["text"])
        lines.append("")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    if over_cap:
        # The packet is written (flagged) so the relevance step can
        # trim it; the exit code still says it does not fit yet.
        print(f"PACKET OVER CAP: {est_tokens} tokens estimated "
              f"(hard cap {HARD_CAP_TOKENS}), {len(relevant)} sections, "
              f"{packet_text_chars} chars.")
        print("No sections were silently dropped. Run the relevance "
              "step to trim it, or narrow the scope, drop a source, "
              "or confirm a shorter packet, then re-run.")
        for r in relevant:
            print(f"  - {r['source']} / {r['title']} "
                  f"({token_estimate(r['chars'])} tokens)")
        return 2

    # --- summary -------------------------------------------------------
    print("PACKET SUMMARY")
    print(f"Document type: {document_type}  Purpose: {purpose.get('purpose')}")
    print(f"Template: {template_id} ({template_source})")
    print(f"Authority route: {purpose.get('authority_route')}  Work mode: {packet['work_mode']}")
    print("Sources read:")
    for s in sources:
        print(f"  - {s['name']} ({s['status']}, {s['chars']} chars, {s['sections']} sections)")
    if chunked_sources:
        print(f"Chunked into passages (no detectable sections): "
              f"{', '.join(chunked_sources)}")
    present = sum(1 for rs in required_sections if rs["status"] == "present")
    print(f"Required sections: {present}/{len(required_sections)} present")
    for rs in required_sections:
        if rs["status"] == "missing":
            print(f"  - MISSING: {rs['title']}")
    print(f"Packet size: {packet_text_chars} chars, ~{est_tokens} tokens "
          f"(target 8,000-12,000, hard cap 20,000)")
    print(f"Gaps: {len(gaps)}")
    for g in gaps:
        print(f"  - {g['what_is_missing']}")
    print("Proceed to drafting?")
    return 0


if __name__ == "__main__":
    sys.exit(main())
