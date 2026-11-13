#!/usr/bin/env python3
"""dedup.py - remove cold-read findings that only restate a gap
already openly flagged in the draft.

Deterministic Python only, v1. No LLM call is made by this script.

Rule (user decision, Nov 11, 2026): a gap openly stated in the
draft with a gap marker is not a finding by itself. Cold read
re-reports it only if it is part of a larger load-bearing gap.

How it works:
- Read the CURRENT draft. Find gap markers (the current kind is
  [AUTHOR INPUT REQUIRED: ...]; the regex still matches the older
  kinds — TECHNICAL PARAMETER, QA REVIEW, REFERENCE CONFLICT —
  so older drafts keep working) and the step each one sits in.
- For each cold-read finding, if its verbatim quote contains a
  marker in the same step, it is a duplicate UNLESS it names an
  additional break beyond the marker. "Additional break" is
  tested deterministically: the finding's
  what_a_qualified_user_could_reasonably_do_wrong names a quoted
  term from the draft step that sits OUTSIDE the marker
  (for example, in test-006 run 2, 4.3 named 'residue' as
  undefined — the trigger itself, not the cleaning solution).
  If it names such a term, keep it, and record what the
  additional break is. Otherwise drop it, and record why.
- If the HFE human input addressed a gap, drafting will have
  removed its marker and filled the text. There is then no
  marker in the current draft for that step, so the filter does
  not drop a finding there. The filter only applies to gaps
  that are still flagged at cold-read time — which is exactly
  the condition the user stated.

Usage:
  python dedup.py --draft draft_v2.md --findings cold_read.json \
      --out cold_read_filtered.json
  --findings may be a findings JSON object, or a raw OpenRouter
  reply JSON (choices[0].message.content, optionally in a code
  fence). --draft may be .md or .txt.

Outputs: filtered findings JSON, same shape as the input, plus
a "deduped" list recording every dropped finding and why.

Exit codes: 0 = done, 2 = missing input / unparsable findings.
"""

import argparse
import json
import re
import sys

MARKER_RE = re.compile(
    r"\[(AUTHOR INPUT REQUIRED|TECHNICAL PARAMETER REQUIRED|"
    r"QA REVIEW REQUIRED|REFERENCE CONFLICT):\s*([^\]]+)\]"
)
STEP_RE = re.compile(r"^(\d+(?:\.\d+)*)\s")
QUOTED_RE = re.compile(r"'([^']+)'")


def die(msg, code=2):
    print(msg)
    sys.exit(code)


def norm_words(text):
    return set(re.findall(r"[a-z][a-z0-9-]{3,}", (text or "").lower()))


def load_findings(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if "findings" in data:
        return data
    # Raw OpenRouter reply.
    try:
        reply = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        die(f"Cannot read findings from {path}.")
    m = re.search(r"\{.*\}", reply, re.S)
    if not m:
        die(f"Cannot parse findings JSON from {path}.")
    return json.loads(m.group(0))


def markers_by_step(draft_text):
    """step -> [(marker_type, topic, step_text_without_markers)]"""
    by_step = {}
    current_step = None
    step_lines = {}
    for line in draft_text.splitlines():
        m = STEP_RE.match(line.strip())
        if m:
            current_step = m.group(1)
            step_lines.setdefault(current_step, []).append(line)
        elif current_step:
            step_lines.setdefault(current_step, []).append(line)
    for step, lines in step_lines.items():
        text = "\n".join(lines)
        for mm in MARKER_RE.finditer(text):
            by_step.setdefault(step, []).append({
                "type": mm.group(1),
                "topic": mm.group(2).strip(),
                "step_text": MARKER_RE.sub("", text),
            })
    return by_step


def main():
    ap = argparse.ArgumentParser(description="Dedup cold-read findings against draft gap markers.")
    ap.add_argument("--draft")
    ap.add_argument("--findings")
    ap.add_argument("--out")
    ap.add_argument("--version", action="store_true")
    args = ap.parse_args()

    if args.version:
        print("dedup 1.0")
        return 0
    if not args.draft or not args.findings or not args.out:
        ap.error("--draft, --findings, and --out are required")

    with open(args.draft, encoding="utf-8") as f:
        draft_text = f.read()
    data = load_findings(args.findings)
    markers = markers_by_step(draft_text)

    kept = []
    deduped = []
    for finding in data.get("findings", []):
        step = str(finding.get("section_step", "")).strip()
        quote = finding.get("verbatim_quote", "")
        step_markers = markers.get(step, [])
        # Also match by section prefix (e.g. finding "4" vs marker "4.3").
        if not step_markers:
            for s, ms in markers.items():
                if s.startswith(step + ".") or step.startswith(s + "."):
                    step_markers = ms
        has_marker_in_quote = bool(step_markers) and bool(MARKER_RE.search(quote))
        if not has_marker_in_quote:
            kept.append(finding)
            continue
        # Additional break? A quoted term in the finding's wrong-text
        # that appears in the step text OUTSIDE any marker.
        wrong = finding.get("what_a_qualified_user_could_reasonably_do_wrong", "")
        extra = []
        for term in QUOTED_RE.findall(wrong):
            term_low = term.lower()
            step_text_no_markers = step_markers[0]["step_text"].lower() if step_markers else ""
            marker_topics = " ".join(m["topic"] for m in step_markers).lower()
            if term_low in step_text_no_markers and term_low not in marker_topics:
                extra.append(term)
        if extra:
            kept.append(finding)
            finding["_dedup_note"] = (
                "Kept: names an additional break beyond the marker: "
                + ", ".join(extra)
            )
            continue
        deduped.append({
            "section_step": step,
            "failure_type": finding.get("failure_type"),
            "reason": (
                "Only restates a gap already openly flagged in the draft: "
                + "; ".join(f"{m['type']}: {m['topic']}" for m in step_markers)
                + ". No additional break named beyond the marker."
            ),
        })

    out = dict(data)
    out["findings"] = kept
    out["deduped"] = deduped
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print(f"Findings in: {len(data.get('findings', []))}")
    print(f"Kept: {len(kept)}")
    print(f"Deduped (already flagged): {len(deduped)}")
    for d in deduped:
        print(f"  - dropped {d['section_step']}: {d['reason']}")
    for finding in kept:
        if "_dedup_note" in finding:
            print(f"  - kept {finding.get('section_step')}: {finding['_dedup_note']}")
    print(f"Wrote: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
