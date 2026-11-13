"""Lookup: obtain what the relevant guidance says about an uncovered
workflow step, and assess whether it covers the gap (v26, test-046).

The packet check (packet_check.py) finds the workflow steps the
source does not cover. This step does what the user did with a
search AI: for each uncovered step, it obtains what the relevant
guidance documents, regulations, or standards say about it, and
assesses whether that information covers the substance of the step
or only the regulatory framework — in which case the operational
mechanics remain site-specific, defined in the user's own internal
SOPs, and the hard gap stays open. It does not write the
explanation from its own knowledge (that was v25, removed in v26):
it obtains, then assesses.

The model is Flash-Lite by default — the same class as the search
AI the user used, and good enough for a recall-and-summarise
lookup. A lookup is one model call per uncovered step (usually
2-4 steps, a fraction of a cent each).

Input: packet_check.json (fit, uncovered_steps) and
purpose_scope.json (purpose, scope_in, document_type) in the
session dir. Runs only for a PARTIAL_REGULATORY_FIT with
uncovered steps; otherwise writes an empty lookup.json and exits
0. A failed lookup never blocks the build: the step is recorded
with assessment "error" and the run continues.

Output: lookup.json in the session dir:
  {model, lookups: [{step, found, sources, assessment,
                     assessment_note}]}
`assessment` is "covers", "framework_only", "not_found", or
"error". Record files lookup-user-{i}.txt / lookup-system.txt /
lookup-raw-{i}.json are written per call (excluded from the
stored-sources list by the "lookup-" prefix in app.py).

Usage:
  python3 lookup.py --session-dir sessions/<id> --mode env|vault
                    [--model google/gemini-2.5-flash-lite]
"""

import argparse
import json
import os
import subprocess
import sys

VERSION = "1.0"

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_CALL = os.path.join(HERE, "..", "..", "..", "agents", "model_call.py")
SYSTEM_FILE = os.path.join(HERE, "lookup-system.txt")


def die(msg):
    print(f"lookup: {msg}", file=sys.stderr)
    sys.exit(2)


def strip_fence(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def lookup_step(model, mode, session_dir, purpose, step, i):
    """One lookup call for one uncovered step. Returns a lookup dict.

    Never raises: a model failure or a bad reply is recorded as
    assessment "error" with the step kept, so the gate can say the
    lookup failed instead of silently dropping the step.
    """
    user = (
        f"Document type: {purpose.get('document_type', 'SOP')}\n"
        f"Purpose: {purpose.get('purpose', '')}\n"
        f"In scope: {purpose.get('scope_in', '')}\n"
        f"\nUncovered workflow step: {step}\n"
    )
    user_file = os.path.join(session_dir, f"lookup-user-{i}.txt")
    sys_file = os.path.join(session_dir, "lookup-system.txt")
    out_file = os.path.join(session_dir, f"lookup-raw-{i}.json")
    with open(user_file, "w", encoding="utf-8") as f:
        f.write(user)
    with open(SYSTEM_FILE, encoding="utf-8") as f:
        system = f.read()
    with open(sys_file, "w", encoding="utf-8") as f:
        f.write(system)
    result = {"step": step, "found": "", "sources": [],
              "assessment": "error",
              "assessment_note": "Lookup failed — no information obtained."}
    try:
        r = subprocess.run(
            [sys.executable, MODEL_CALL, "--mode", mode,
             "--model", model, "--system-file", sys_file,
             "--user-file", user_file, "--out", out_file],
            capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            result["assessment_note"] = (
                "Lookup failed — the model call did not return.")
            return result
        with open(out_file, encoding="utf-8") as f:
            data = json.load(f)
        parsed = json.loads(strip_fence(
            data["choices"][0]["message"]["content"]))
        found = parsed.get("found", "")
        if not isinstance(found, str):
            found = ""
        result["found"] = found.strip()[:600]
        sources = parsed.get("sources", [])
        if isinstance(sources, list):
            result["sources"] = [str(s)[:200] for s in sources if s]
        assessment = parsed.get("assessment", "")
        if assessment in ("covers", "framework_only", "not_found"):
            result["assessment"] = assessment
        else:
            result["assessment"] = "error"
            result["assessment_note"] = (
                "Lookup returned information but the assessment was unclear.")
            return result
        note = parsed.get("assessment_note", "")
        result["assessment_note"] = (str(note).strip()[:200]
                                     if isinstance(note, str) and note.strip()
                                     else "")
    except (OSError, json.JSONDecodeError, KeyError, IndexError):
        pass
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-dir", required=True)
    ap.add_argument("--mode", choices=("env", "vault"), required=True)
    ap.add_argument("--model", default="google/gemini-2.5-flash-lite")
    args = ap.parse_args()
    session_dir = args.session_dir
    check_path = os.path.join(session_dir, "packet_check.json")
    purpose_path = os.path.join(session_dir, "purpose_scope.json")
    out_path = os.path.join(session_dir, "lookup.json")
    lookups = []
    if os.path.exists(check_path) and os.path.exists(purpose_path):
        check = json.load(open(check_path))
        purpose = json.load(open(purpose_path))
        steps = check.get("uncovered_steps", [])
        if check.get("fit") == "PARTIAL_REGULATORY_FIT" and steps:
            for i, step in enumerate(steps):
                lookups.append(lookup_step(args.model, args.mode,
                                           session_dir, purpose, step, i))
    result = {"model": args.model, "lookups": lookups}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"lookup: {len(lookups)} uncovered step(s) looked up "
          f"({args.model})")


if __name__ == "__main__":
    main()
