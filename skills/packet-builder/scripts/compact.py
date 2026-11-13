#!/usr/bin/env python3
"""Model compaction calls for the packet-builder.

Usage:
  compact.py --session test-021 [--mode env|vault]
      [--model google/gemini-2.5-flash]

Relevance judges whole sections yes/no, but a real guidance
document has sections that are individually too large for the
packet cap — Q1 (Nov 11, 2026): one ANNEXES section is ~88,000
chars, ~22,000 tokens; relevance kept 18 sections and the packet
was still ~63,700 tokens. This script is the third step: one
mid-tier model call per kept section over COMPACT_THRESHOLD chars,
condensing it to ~1,500-2,000 chars. Sections under the threshold
are untouched.

A condensed section is NOT verbatim: it is a model condensation
of the original section, recorded in the packet as
"condensed": true with the original section_id and source, so it
stays traceable (find the original by section, cite it). The
condensation keeps numbers and criteria exact. Non-condensed
sections remain verbatim.

Modes: env (key from OPENROUTER_API_KEY env — the Streamlit path)
or vault (local testing through the Muse OpenRouter helper).
The model call goes through agents/model_call.py.
"""

import argparse
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from relevance import write_packet_md  # noqa: E402

SYSTEM_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "compact-system.txt")
MODEL_CALL = os.path.join(BASE, "agents", "model_call.py")
VERSION = "1.0"
HARD_CAP_TOKENS = 20000
CHARS_PER_TOKEN = 4
# Sections over this many chars are condensed. Target output is
# ~1,500-2,000 chars per section (see compact-system.txt).
COMPACT_THRESHOLD = 8000


def die(msg):
    print(f"COMPACT BLOCKED: {msg}", file=sys.stderr)
    sys.exit(2)


def strip_fence(text):
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").strip()
    return t


def main():
    ap = argparse.ArgumentParser(description="Model compaction calls for a packet.")
    ap.add_argument("--session", help="session id (folder sessions/<id>)")
    ap.add_argument("--session-dir", help="session folder path (overrides --session)")
    ap.add_argument("--model", default="google/gemini-2.5-flash")
    ap.add_argument("--mode", choices=["env", "vault"], default="env")
    ap.add_argument("--version", action="store_true")
    args = ap.parse_args()

    if args.version:
        print(f"compact {VERSION}")
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
    # Two passes. Pass 1 condenses sections over COMPACT_THRESHOLD
    # chars. The model overshoots the ~1,500-2,000 char target
    # (Q1, Nov 11, 2026: first pass left the packet at ~21,241
    # tokens, still over cap), so pass 2 condenses anything still
    # over 2,500 chars down toward ~1,500. A section is never
    # condensed more than twice.
    for pass_no, (threshold, extra) in enumerate(
            ((COMPACT_THRESHOLD, ""),
             (2500, "\nCondense further: at most 1,500 characters. "
                    "Keep only the requirements most central to the "
                    "purpose; drop the rest.")), 1):
        for i, sec in enumerate(sections):
            text = sec.get("text") or ""
            if len(text) <= threshold:
                continue
            label = sec.get("title") or sec.get("section_id") or f"section {i}"
            user = (f"Document type: {doc_type}\nPurpose: {purpose}\n\n"
                    f"Section: {label} (source: {sec.get('source')}, "
                    f"section {sec.get('section_id')}, {len(text)} chars)\n\n"
                    f"Section text:\n{text}{extra}")
            user_file = os.path.join(session_dir, f"compact-user-{i}-p{pass_no}.txt")
            sys_file = os.path.join(session_dir, "compact-system.txt")
            out_file = os.path.join(session_dir, f"compact-raw-{i}-p{pass_no}.json")
            with open(user_file, "w", encoding="utf-8") as f:
                f.write(user)
            with open(sys_file, "w", encoding="utf-8") as f:
                f.write(system)
            # A single failed model call must not discard the whole
            # compaction (test-040, Nov 12, 2026: the run died on
            # section 14 and lost 7 successful pass-1 condensations,
            # because die() exits before the packet is written).
            # Retry once; if it still fails, leave this section
            # uncondensed, record the failure, and continue with
            # the rest. The packet is always written at the end.
            condensed = None
            for _attempt in (1, 2):
                r = subprocess.run(
                    [sys.executable, MODEL_CALL, "--mode", args.mode,
                     "--model", args.model, "--system-file", sys_file,
                     "--user-file", user_file, "--out", out_file],
                    capture_output=True, text=True, timeout=600)
                if r.returncode == 0:
                    break
                print(f"  compact: model call failed for section {i} "
                      f"(attempt {_attempt}): "
                      f"{(r.stdout + r.stderr).strip()[:200]}")
            if r.returncode != 0:
                calls.append({"section": label,
                              "pass": pass_no,
                              "from_chars": len(text),
                              "to_chars": None,
                              "error": "model call failed after 2 attempts; "
                                       "section left uncondensed"})
                continue
            with open(out_file, encoding="utf-8") as f:
                data = json.load(f)
            try:
                condensed = strip_fence(data["choices"][0]["message"]["content"])
            except KeyError:
                calls.append({"section": label,
                              "pass": pass_no,
                              "from_chars": len(text),
                              "to_chars": None,
                              "error": "model reply has no content; "
                                       "section left uncondensed"})
                continue
            if not condensed.strip():
                calls.append({"section": label,
                              "pass": pass_no,
                              "from_chars": len(text),
                              "to_chars": None,
                              "error": "model reply is empty; "
                                       "section left uncondensed"})
                continue
            calls.append({"section": label,
                          "pass": pass_no,
                          "from_chars": len(text),
                          "to_chars": len(condensed)})
            sec["text"] = condensed
            sec["chars"] = len(condensed)
            sec["condensed"] = True
            # Keep the ORIGINAL size: pass 2 condenses a condensation,
            # so do not overwrite it with the pass-1 size.
            if "condensed_from_chars" not in sec:
                sec["condensed_from_chars"] = len(text)
            print(f"  compacted (pass {pass_no}): {label} {len(text)} -> {len(condensed)} chars")
        chars = sum(len(sec.get("text") or "") for sec in sections)
        if max(1, chars // 4) <= HARD_CAP_TOKENS:
            break

    chars = sum(len(sec.get("text") or "") for sec in sections)
    packet["packet_chars"] = chars
    packet["packet_tokens_estimate"] = max(1, chars // 4)
    packet["token_estimate"] = packet["packet_tokens_estimate"]
    packet["over_cap"] = packet["token_estimate"] > HARD_CAP_TOKENS
    packet["model_compaction_calls"] = calls
    with open(packet_path, "w", encoding="utf-8") as f:
        json.dump(packet, f, indent=2)
    write_packet_md(session_dir, packet)
    print(f"compact: {len(calls)} sections condensed, "
          f"~{packet['token_estimate']} tokens")
    if packet["over_cap"]:
        print(f"STILL OVER CAP after compaction: ~{packet['token_estimate']} tokens "
              f"(hard cap {HARD_CAP_TOKENS}). Narrow the scope or drop a source.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
