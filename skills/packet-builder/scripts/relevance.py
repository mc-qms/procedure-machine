#!/usr/bin/env python3
"""Model relevance calls for the packet-builder.

Usage:
  relevance.py --session test-012 [--mode env|vault]
      [--model google/gemini-2.5-flash]

Python's packet selection is deterministic: template-match first,
keyword-match second. On a real guidance document the keyword step
over-selects — common words like "procedure" and "assay" appear in
almost every section, so the packet balloons to nearly the whole
document (test-012: 11 sections, ~17,939 tokens, 1 template-match).
This script is the second step the packet-builder skill specifies:
one mid-tier model call per relevant section, yes/no + one-line
reason, recorded in the packet's `model_relevance_calls`. Sections
the model rejects are dropped from the packet; template-matched
sections are never dropped here (the template requires them).

Modes: env (key from OPENROUTER_API_KEY env — the Streamlit path)
or vault (local testing through the Muse OpenRouter helper).
The model call goes through agents/model_call.py; this script only
builds the per-section prompts and applies the verdicts.
"""

import argparse
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SYSTEM_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "relevance-system.txt")
MODEL_CALL = os.path.join(BASE, "agents", "model_call.py")
VERSION = "1.1"
HARD_CAP_TOKENS = 20000
CHARS_PER_TOKEN = 4


def die(msg):
    print(f"RELEVANCE BLOCKED: {msg}", file=sys.stderr)
    sys.exit(2)


def write_packet_md(session_dir, packet):
    """Regenerate source_packet.md from the (trimmed) packet JSON.

    packet.py writes the .md once; relevance changes the packet, so
    the .md would go stale if it were not rewritten here (known gap
    from test-012, fixed in v1.1). Same format as packet.py.
    """
    relevant = packet.get("relevant_sections", [])
    lines = []
    lines.append(f"# Source Packet — {packet.get('document_type')}")
    lines.append("")
    lines.append(f"Packet: {packet.get('packet_id')}  Template: {packet.get('template_id')}")
    lines.append(f"Purpose: {packet.get('purpose')}")
    lines.append(f"Intended user: {packet.get('intended_user')}")
    lines.append(f"Authority route: {packet.get('authority_route')}  Work mode: {packet.get('work_mode')}")
    lines.append(f"Packet size: {packet.get('packet_chars')} chars, ~{packet.get('packet_tokens_estimate')} tokens "
                 f"(estimate: chars / {CHARS_PER_TOKEN})")
    lines.append(f"Sources: {len(packet.get('sources', []))}  Relevant sections: {len(relevant)}  "
                 f"Gaps: {len(packet.get('gaps', []))}")
    lines.append("")
    lines.append("## Required sections")
    for rs in packet.get("required_sections", []):
        lines.append(f"- [{rs['status']}] {rs['id']} {rs['title']}")
    lines.append("")
    lines.append("## Gaps")
    for g in packet.get("gaps", []):
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
    with open(os.path.join(session_dir, "source_packet.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def strip_fence(text):
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").strip()
        if t.lower().startswith("json"):
            t = t[4:].strip()
    return t


def main():
    ap = argparse.ArgumentParser(description="Model relevance calls for a packet.")
    ap.add_argument("--session", help="session id (folder sessions/<id>)")
    ap.add_argument("--session-dir", help="session folder path (overrides --session)")
    ap.add_argument("--model", default="google/gemini-2.5-flash")
    ap.add_argument("--mode", choices=["env", "vault"], default="env")
    ap.add_argument("--version", action="store_true")
    args = ap.parse_args()

    if args.version:
        print(f"relevance {VERSION}")
        return 0
    if not args.session and not args.session_dir:
        die("--session or --session-dir is required.")

    session_dir = args.session_dir or os.path.join("sessions", args.session)
    packet_path = os.path.join(session_dir, "source_packet.json")
    if not os.path.exists(packet_path):
        die(f"Missing packet: {packet_path}. Run packet.py first.")
    with open(packet_path, encoding="utf-8") as f:
        packet = json.load(f)
    with open(SYSTEM_FILE, encoding="utf-8") as f:
        system = f.read()

    purpose = packet.get("purpose", "")
    doc_type = packet.get("document_type", "SOP")
    sections = packet.get("relevant_sections", [])
    calls = []
    kept = []
    for i, sec in enumerate(sections):
        reason = sec.get("selection_reason", "")
        # Template-matched sections are required by the template;
        # the model does not get to drop them.
        if reason.startswith("template-match"):
            kept.append(sec)
            calls.append({"section": sec.get("title") or sec.get("section_id"),
                          "verdict": "kept-template-match",
                          "reason": "Required by the template; not model-judged."})
            continue
        excerpt = (sec.get("text") or "")[:2000]
        label = sec.get("title") or sec.get("section_id") or f"section {i}"
        user = (f"Document type: {doc_type}\nPurpose: {purpose}\n\n"
                f"Section: {label} (source: {sec.get('source')})\n"
                f"Excerpt:\n{excerpt}")
        user_file = os.path.join(session_dir, f"relevance-user-{i}.txt")
        sys_file = os.path.join(session_dir, "relevance-system.txt")
        out_file = os.path.join(session_dir, f"relevance-raw-{i}.json")
        with open(user_file, "w", encoding="utf-8") as f:
            f.write(user)
        with open(sys_file, "w", encoding="utf-8") as f:
            f.write(system)
        r = subprocess.run(
            [sys.executable, MODEL_CALL, "--mode", args.mode,
             "--model", args.model, "--system-file", sys_file,
             "--user-file", user_file, "--out", out_file],
            capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            die(f"model call failed for section {i}: "
                f"{(r.stdout + r.stderr).strip()[:300]}")
        with open(out_file, encoding="utf-8") as f:
            data = json.load(f)
        try:
            verdict = json.loads(strip_fence(
                data["choices"][0]["message"]["content"]))
        except (KeyError, json.JSONDecodeError):
            die(f"model reply for section {i} is not JSON.")
        rel = str(verdict.get("relevant", "")).strip().lower()
        why = str(verdict.get("reason", ""))[:200]
        calls.append({"section": sec.get("title") or sec.get("section_id"),
                      "verdict": rel, "reason": why})
        if rel == "yes":
            kept.append(sec)

    dropped = len(sections) - len(kept)
    packet["relevant_sections"] = kept
    packet["model_relevance_calls"] = calls
    # Token estimate is chars / 4 over the kept excerpts, as packet.py does.
    chars = sum(len(sec.get("text") or "") for sec in kept)
    packet["packet_chars"] = chars
    packet["packet_tokens_estimate"] = max(1, chars // 4)
    packet["token_estimate"] = packet["packet_tokens_estimate"]
    packet["over_cap"] = packet["token_estimate"] > HARD_CAP_TOKENS
    with open(packet_path, "w", encoding="utf-8") as f:
        json.dump(packet, f, indent=2)
    write_packet_md(session_dir, packet)
    print(f"relevance: {len(sections)} sections in, {len(kept)} kept, "
          f"{dropped} dropped, ~{packet['token_estimate']} tokens")
    for c in calls:
        print(f"  {c['verdict']}: {c['section']} — {c['reason']}")
    if packet["over_cap"]:
        print(f"STILL OVER CAP after relevance: ~{packet['token_estimate']} tokens "
              f"(hard cap {HARD_CAP_TOKENS}). Narrow the scope or drop a source.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
