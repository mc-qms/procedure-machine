#!/usr/bin/env python3
"""step_lint.py - deterministic candidates for the cold read:
numbered steps that may bundle more than one action, and lines
that name a regulatory role term as the actor.

Deterministic Python only, v1. No LLM call is made by this script,
and nothing it emits is a finding. It hands the cold-read model a
candidate list to judge, the same way dedup.py filters what the
model returned: code owns the pattern match, the model owns the
judgment.

Rules (user decision, Nov 21, 2026, from an HFE review of
generated SOPs):
- One action per step. A step that chains distinct actions
  ("assemble X, include Y, confirm Z" as one step) is a candidate.
  A step that lists the OBJECTS of one action (the fields of one
  record entry, the items of one comparison) is not: object-list
  bullets and "including" lists never count as actions, a noun
  that is also a verb ("control record") never counts, and verbs
  inside a "that" clause describe the state being confirmed, not
  actions the user performs.
- Role-term fidelity. A regulatory role term named as the actor
  ("the quality control unit", from 21 CFR 211.22) can conflate
  functions a company keeps separate: testing and laboratory-data
  work is Quality Control's; review, disposition, and release
  authority is Quality Assurance's. Lines naming such a term are
  candidates for the model to test against the document's own
  designated functions.

How the action scan works:
- Numbered steps are collected with their section heading and
  their printed step number, so a candidate can be located
  ("4.5, step 2"). Object-list bullet lines are excluded from
  the scan.
- Each sentence in the step contributes its head action: the
  first action verb in the sentence, allowing a short subject
  before it ("The reviewer assembles ..."), skipping a verb used
  as an adjective after a determiner ("the approved
  specification"). A head verb followed by "that" caps the
  sentence - the rest is the state being acted on.
- A verb chained directly onto a counted action ("reviews and
  approves", "assemble, then record") counts as another action.
- Two or more DISTINCT actions in one step make it a candidate,
  and the actions are recorded as the signal.

Usage:
  python step_lint.py --draft draft_v2.md --out step_lint.json
  --draft may be .md or .txt.

Outputs: JSON {"candidates": [...]} written to --out, plus a
printed summary. Each candidate carries section_step, kind
("multi_action" or "role_term"), the verbatim quote, and the
signal.

Exit codes: 0 = done, 2 = missing input.
"""

import argparse
import json
import re
import sys

# Action verbs, base form. Matching also accepts the verb's
# inflected forms (confirms / confirming / confirmed -> confirm).
ACTION_VERBS = {
    "acknowledge", "add", "adjust", "archive", "assemble", "assess",
    "assign", "attach", "authorize", "calculate", "calibrate",
    "check", "choose", "clean", "close", "collect", "compare",
    "complete", "compute", "confirm", "count", "create", "decide",
    "determine", "discard", "dispose", "distribute", "document",
    "download", "enter", "ensure", "escalate", "establish",
    "evaluate", "examine", "execute", "file", "forward", "gather",
    "hold", "identify", "include", "inform", "initial", "inspect",
    "investigate", "issue", "label", "maintain", "measure",
    "monitor", "note", "notify", "observe", "obtain", "open",
    "pack", "perform", "photograph", "place", "prepare", "print",
    "provide", "quarantine", "read", "receive", "reconcile",
    "record", "refer", "reject", "release", "remove", "repeat",
    "report", "resolve", "retain", "retrieve", "review", "rinse",
    "sample", "scan", "schedule", "seal", "segregate", "select",
    "send", "set", "ship", "sign", "store", "submit", "take",
    "test", "trace", "train", "transfer", "update", "upload",
    "verify", "weigh",
}

# Regulatory role terms that name a function generically. The
# cold read judges whether the term, as used, hides which
# function acts.
ROLE_TERMS = [
    "quality control unit",
]

FILLER_WORDS = {
    "the", "a", "an", "then", "next", "first", "before", "after",
    "once", "when", "while", "only", "also", "must", "shall",
    "may", "can", "will", "to", "and", "or", "is", "are", "was",
    "were", "be", "been", "it", "this", "these", "those", "that",
}

DETERMINERS = {"the", "a", "an", "its", "their", "this", "that",
               "these", "those", "each", "every", "any"}

HEADING_RE = re.compile(r"^#{1,6}\s+(\d+(?:\.\d+)*)\b")
STEP_RE = re.compile(r"^\s{0,3}(\d+)[.)]\s+(\S.*)$")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;])\s+")
CHAIN_RE = re.compile(r"\b(?:and|then)\s+([A-Za-z']+)")
WORD_RE = re.compile(r"[A-Za-z']+")


def die(msg, code=2):
    print(msg)
    sys.exit(code)


def verb_base(word):
    """Map a word to its base action verb, or None."""
    w = word.lower().strip("()[]{}\"'")
    if w in ACTION_VERBS:
        return w
    for suffix in ("ing", "es", "ed", "s", "d"):
        if w.endswith(suffix) and len(w) > len(suffix) + 2:
            stem = w[: -len(suffix)]
            if stem in ACTION_VERBS:
                return stem
            if suffix == "ing" and stem + "e" in ACTION_VERBS:
                return stem + "e"
            if suffix in ("es", "s") and stem.endswith("i"):
                if stem[:-1] + "y" in ACTION_VERBS:
                    return stem[:-1] + "y"
    return None


def sentence_head(words):
    """(head_action, capped) for one sentence's word list.

    The head is the first action verb, allowing filler and a
    short subject (up to 4 content tokens scanned). A verb right
    after a determiner is an adjective or noun, not the head.
    capped is True when the head is followed by 'that': the rest
    of the sentence states what is acted on, not more actions."""
    scanned = 0
    for i, word in enumerate(words):
        low = word.lower()
        if low in FILLER_WORDS:
            continue
        scanned += 1
        if scanned > 4:
            return None, False
        prev = words[i - 1].lower() if i > 0 else ""
        base = verb_base(word)
        if base and prev not in DETERMINERS:
            capped = (i + 1 < len(words)
                      and words[i + 1].lower() == "that")
            return base, capped
    return None, False


def step_actions(step_text):
    """Distinct actions the step assigns, in order."""
    found = []
    for sentence in SENTENCE_SPLIT_RE.split(step_text):
        words = WORD_RE.findall(sentence)
        if not words or words[0].lower() in ("including", "include"):
            continue
        head, capped = sentence_head(words)
        if head and head not in found:
            found.append(head)
        if capped or not head:
            continue
        # Verbs chained directly onto the head ("reviews and
        # approves") are further actions in the same step.
        for m in CHAIN_RE.finditer(sentence):
            base = verb_base(m.group(1))
            if base and base not in found:
                found.append(base)
    return found


def collect_steps(lines):
    """Yield (section_step, scan_text, quote) per numbered step.
    Bullet lines are object lists: excluded from the scan text
    and from the quote."""
    section = None
    steps = []
    current = None  # (label, [scan lines])
    for line in lines:
        h = HEADING_RE.match(line)
        if h:
            if current:
                steps.append(current)
                current = None
            section = h.group(1)
            continue
        s = STEP_RE.match(line)
        if s:
            if current:
                steps.append(current)
            label = (f"{section}, step {s.group(1)}" if section
                     else f"step {s.group(1)}")
            current = (label, [s.group(2)])
            continue
        if current is not None:
            if line.strip() == "---":
                steps.append(current)
                current = None
                continue
            if line.lstrip().startswith("- "):
                continue  # object list, not step text
            if "[AUTHOR INPUT REQUIRED" in line:
                continue  # gap marker, not step text
            current[1].append(line)
    if current:
        steps.append(current)
    out = []
    for label, text_lines in steps:
        text = "\n".join(text_lines).strip()
        out.append((label, text, re.sub(r"\s+", " ", text)[:400]))
    return out


def lint(draft_text):
    candidates = []
    for label, text, quote in collect_steps(draft_text.splitlines()):
        actions = step_actions(text)
        if len(actions) >= 2:
            candidates.append({
                "section_step": label,
                "kind": "multi_action",
                "quote": quote,
                "signals": "distinct actions in one step: "
                           + ", ".join(actions),
            })
    for i, line in enumerate(draft_text.splitlines(), start=1):
        low = line.lower()
        for term in ROLE_TERMS:
            if term in low:
                candidates.append({
                    "section_step": f"line {i}",
                    "kind": "role_term",
                    "quote": line.strip()[:400],
                    "signals": "regulatory role term named as actor: "
                               f"'{term}'",
                })
    return candidates


def main():
    ap = argparse.ArgumentParser(
        description="Flag candidate multi-action steps and role-term lines for the cold read.")
    ap.add_argument("--draft")
    ap.add_argument("--out")
    ap.add_argument("--version", action="store_true")
    args = ap.parse_args()

    if args.version:
        print("step_lint 1.0")
        return 0
    if not args.draft or not args.out:
        ap.error("--draft and --out are required")

    try:
        with open(args.draft, encoding="utf-8") as f:
            draft_text = f.read()
    except OSError:
        die(f"Cannot read draft: {args.draft}")

    candidates = lint(draft_text)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"candidates": candidates}, f, indent=2)

    multi = [c for c in candidates if c["kind"] == "multi_action"]
    roles = [c for c in candidates if c["kind"] == "role_term"]
    print(f"Candidates: {len(candidates)} "
          f"({len(multi)} multi-action, {len(roles)} role-term)")
    for c in candidates:
        print(f"  - {c['section_step']} [{c['kind']}]: {c['signals']}")
    print(f"Wrote: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
