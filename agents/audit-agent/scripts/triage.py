#!/usr/bin/env python3
"""triage.py - triage the questions a pause would ask, and the
answers a human gives at a pause.

The pause is the point of the loop: a human decides what the
sources cannot. But findings used to become pause questions with
no check at all, so the human was asked things the built packet
already answers (retention periods stated in the packet's own
regulations), things that are really the name of one of the
organization's own documents or systems (a reference, not a
question), and the same question twice in different words. This
step sits between the findings and the pause, in both modes:

questions task - one model call classifies each candidate gap
question against the packet:
  answered   the packet itself answers it; the verdict must
             quote the packet passage verbatim. The quote is
             verified deterministically below: no verbatim
             quote in the packet, no grounding - the question
             is asked instead. An answered question is not
             shown; the app grounds it in the next revision.
  reference  the answer is a name - one of the organization's
             own procedures, systems, schedules, or record
             locations. The app turns the marker into a
             placeholder naming it; it is not a pause question.
  ask        only the organization can decide it. Duplicates
             share a group key and merge into one question.
Each ask verdict also carries a load-bearing weight (1-5) and a
one-line context naming the requirement it comes from. The
deterministic pass then merges groups and caps the pause at
CAP questions, most load-bearing first; the overflow is
recorded as deferred - it stays flagged in the draft and in
the flag list, it just does not block at this pause.

answers task - one model call classifies each answer the human
gave:
  content    the answer supplies the information (the normal
             case; it is applied as author input, as before).
  sources    the human says the source documents already
             answer it. The verdict must quote the packet
             passage that answers it, verified the same way;
             an unverifiable claim is reported back as
             unverified so the app can re-flag the item -
             the phrase is never treated as authored content
             and never silently dropped.
  reference  the answer names another procedure, document, or
             system; the app turns the marker into a
             placeholder for it.

Deterministic Python does everything except the two
classification calls: bucket enforcement (every candidate and
every answer lands in exactly one outcome), quote verification,
group merging, and the cap. A --verdicts file may supply the
classification as JSON ({"verdicts": [...]}) instead of a model
call - the test hook for fault injection.

Usage:
  triage.py questions --session-dir DIR --round N
      [--model M] [--mode env|vault] [--verdicts FILE]
  triage.py answers   --session-dir DIR --round N
      [--model M] [--mode env|vault] [--verdicts FILE]

Reads (questions):  triage_candidates_N.json -
  [{"marker", "body", "section"}]; source_packet.md.
Writes:             triage_N.json.
Reads (answers):    triage_answers_in_N.json -
  [{"marker", "body", "answer"}]; source_packet.md.
Writes:             triage_answers_N.json.

Exit codes: 0 = done, 2 = blocked (missing input, model
failure, unparsable reply). The app treats a blocked triage as
no triage: the pause proceeds with every candidate asked, as
it did before this step existed.
"""

import argparse
import json
import os
import re
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
MODEL_CALL = os.path.join(BASE, "agents", "model_call.py")
VERSION = "1.0"
CAP = 5

QUESTIONS_SYSTEM = """You classify flagged gap questions for a draft procedure before a human is asked them. The draft was written from a source packet only. For each question, decide one verdict:

- "answered": the source packet itself already answers this question. You MUST copy the answering passage from the packet verbatim into packet_quote (one passage, copied exactly, long enough to stand as evidence - at least a full sentence) and name the source or section it comes from in packet_source. If you cannot quote the packet answering it, the verdict is not "answered".
- "reference": what is being asked for is a name - one of the organization's own procedures, documents, systems, schedules, or record locations (for example the title of the deviation procedure, the system of record, the retention schedule). Give reference_name: the name to put in a placeholder, in the organization's own terms (for example "Deviation and Investigation Procedure"). Do not invent a document number.
- "ask": only the organization can decide this; the packet does not answer it and it is not a name.

For every question also give:
- "group": when two or more questions are the same underlying ask in different words, give them the same short group string (a few words naming the shared ask). Otherwise an empty string.
- "weight": for "ask" verdicts, how load-bearing the question is, 1 to 5. 5 = without an answer a qualified user could plausibly do something unsafe, noncompliant, or irreversible; 1 = a detail that changes little. Judge by what rides on the answer, not by how the question is phrased.
- "context": one short line naming the requirement, regulation, or draft statement the question comes from, so the human can tell what a complete answer looks like.
- "question_text": when the question fuses several asks into one, a tightened version that asks the single main thing. Otherwise repeat the question unchanged.

Return JSON only, exactly: {"verdicts": [{"question": "<the question text, copied exactly, with nothing added before or after it - no section names, no brackets>", "verdict": "answered"|"reference"|"ask", "packet_quote": "...", "packet_source": "...", "reference_name": "...", "group": "...", "weight": 3, "context": "...", "question_text": "..."}]}. One verdict per question, in the order given. Do not answer the questions yourself beyond the packet_quote evidence."""

ANSWERS_SYSTEM = """You classify the answers a human gave to flagged gap questions in a draft procedure. The draft was written from a source packet only. For each answer, decide one kind:

- "content": the answer supplies the information asked for. This is the normal case.
- "sources": the answer says, in substance, that the source documents already answer the question ("in the sources", "the packet covers this", "see the regulation", and the like). Then find the answering passage in the packet and copy it verbatim into packet_quote (one passage, copied exactly, at least a full sentence), naming its source or section in packet_source. If you cannot find a passage that answers it, still return "sources" but leave packet_quote empty - the claim will be reported back as unverified and the question will stay flagged; never invent a passage.
- "reference": the answer names another of the organization's procedures, documents, or systems instead of supplying the information (for example "per the Deviation SOP" or "the LIMS"). Give reference_name: the name as the human gave it, cleaned of surrounding words. Do not invent a document number.

Return JSON only, exactly: {"verdicts": [{"marker": "<the marker, copied exactly>", "kind": "content"|"sources"|"reference", "packet_quote": "...", "packet_source": "...", "reference_name": "..."}]}. One verdict per answer, in the order given."""


def die(msg):
    print(f"TRIAGE BLOCKED: {msg}", file=sys.stderr)
    sys.exit(2)


def strip_fence(text):
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`").strip()
        if t.lower().startswith("json"):
            t = t[4:].strip()
    return t


def norm_ws(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def quote_in_packet(quote, packet_norm_lower):
    """The evidence test: a claimed packet answer must be a
    verbatim passage of the packet (whitespace-normalized,
    case-insensitive - extraction artifacts differ, wording
    may not). Too short to stand as evidence does not count."""
    q = norm_ws(quote).lower()
    if len(q) < 25:
        return False
    return q in packet_norm_lower


def call_model(session_dir, tag, system, user, model, mode):
    sys_file = os.path.join(session_dir, "triage-system.txt")
    user_file = os.path.join(session_dir, f"triage-user-{tag}.txt")
    out_file = os.path.join(session_dir, f"triage-raw-{tag}.json")
    with open(sys_file, "w", encoding="utf-8") as f:
        f.write(system)
    with open(user_file, "w", encoding="utf-8") as f:
        f.write(user)
    r = subprocess.run(
        [sys.executable, MODEL_CALL, "--mode", mode,
         "--model", model, "--system-file", sys_file,
         "--user-file", user_file, "--out", out_file],
        capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        die(f"model call failed ({tag}): "
            f"{(r.stdout + r.stderr).strip()[:300]}")
    with open(out_file, encoding="utf-8") as f:
        data = json.load(f)
    try:
        parsed = json.loads(strip_fence(
            data["choices"][0]["message"]["content"]))
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        die(f"model reply ({tag}) is not JSON.")
    verdicts = parsed.get("verdicts")
    if not isinstance(verdicts, list):
        die(f"model reply ({tag}) has no 'verdicts' list.")
    return verdicts


def load_verdicts(args, session_dir, tag, system, user):
    if args.verdicts:
        try:
            with open(args.verdicts, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            die(f"cannot read --verdicts file: {e}")
        verdicts = data.get("verdicts")
        if not isinstance(verdicts, list):
            die("--verdicts file has no 'verdicts' list.")
        return verdicts
    if not args.model:
        die("no --model given and no --verdicts file.")
    return call_model(session_dir, tag, system, user,
                      args.model, args.mode)


def clamp_weight(value):
    try:
        w = int(value)
    except (TypeError, ValueError):
        return 3
    return max(1, min(5, w))


def do_questions(args):
    session_dir = args.session_dir
    cand_path = os.path.join(
        session_dir, f"triage_candidates_{args.round}.json")
    packet_path = os.path.join(session_dir, "source_packet.md")
    if not os.path.exists(cand_path):
        die(f"no candidates file at {cand_path}")
    if not os.path.exists(packet_path):
        die(f"no packet at {packet_path}")
    with open(cand_path, encoding="utf-8") as f:
        candidates = json.load(f)
    with open(packet_path, encoding="utf-8") as f:
        packet_text = f.read()
    packet_norm = norm_ws(packet_text).lower()

    lines = ["Flagged gap questions to classify:"]
    for i, c in enumerate(candidates, 1):
        sec = c.get("section") or "(section not recorded)"
        lines.append(f"{i}. Question: {c.get('body', '')}")
        lines.append(f"   (flagged in draft section: {sec})")
    lines.append("")
    lines.append("SOURCE PACKET:")
    lines.append(packet_text)
    raw = load_verdicts(args, session_dir, f"questions-{args.round}",
                        QUESTIONS_SYSTEM, "\n".join(lines))

    # Match each verdict back to its candidate. Models decorate
    # the echo (a bracketed section prefix, truncation), so
    # matching is layered and deterministic: exact normalized,
    # bracket-prefix-stripped, then containment with the
    # longest candidate body winning.
    lowered = [(norm_ws(c.get("body", "")).lower(), c)
               for c in candidates]

    def resolve(qtext):
        t = norm_ws(qtext).lower()
        if not t:
            return None
        t2 = re.sub(r"^\[[^\]]*\]\s*", "", t)
        for b, c in lowered:
            if b and b in (t, t2):
                return c
        best = None
        for b, c in lowered:
            if b and (b in t or b in t2 or t in b or t2 in b):
                if best is None or len(b) > len(
                        norm_ws(best.get("body", "")).lower()):
                    best = c
        return best

    resolved = {}
    for v in raw:
        if isinstance(v, dict) and v.get("question"):
            c = resolve(v["question"])
            if c is not None:
                resolved.setdefault(id(c), v)

    # One outcome per candidate, in candidate order.
    items = []
    for idx, c in enumerate(candidates):
        body = c.get("body", "")
        v = resolved.get(id(c))
        item = {"marker": c.get("marker", ""), "body": body,
                "section": c.get("section", ""), "index": idx}
        if v is None:
            item.update(outcome="ask", weight=3, context="",
                        display=body,
                        note="unclassified - asked as-is")
        else:
            verdict = str(v.get("verdict", "")).strip().lower()
            item["context"] = str(v.get("context", ""))[:300]
            item["group"] = str(v.get("group", "")).strip()[:80]
            if verdict == "answered" and quote_in_packet(
                    v.get("packet_quote", ""), packet_norm):
                item.update(
                    outcome="grounded",
                    packet_quote=norm_ws(v.get("packet_quote", "")),
                    packet_source=str(v.get("packet_source", ""))[:200])
            elif verdict == "reference" and norm_ws(
                    v.get("reference_name", "")):
                item.update(
                    outcome="placeholder",
                    reference_name=norm_ws(
                        v.get("reference_name", ""))[:160])
            else:
                note = ""
                if verdict == "answered":
                    note = ("claimed packet answer did not verify "
                            "against the packet - asked instead")
                elif verdict == "reference":
                    note = "reference without a name - asked instead"
                item.update(
                    outcome="ask",
                    weight=clamp_weight(v.get("weight")),
                    display=norm_ws(v.get("question_text", "")) or body,
                    note=note)
        items.append(item)

    # Merge duplicate asks: a group key shared by two or more
    # asks makes one question of them; the first in candidate
    # order is the primary, the rest are merged into it.
    groups = {}
    for item in items:
        if item["outcome"] == "ask" and item.get("group"):
            groups.setdefault(item["group"], []).append(item)
    primaries = []
    for item in items:
        if item["outcome"] != "ask":
            continue
        members = groups.get(item.get("group", ""), [])
        if len(members) >= 2 and item is not members[0]:
            item["outcome"] = "merged"
            item["primary"] = members[0]["marker"]
            continue
        item["members"] = [m["marker"] for m in members] \
            if len(members) >= 2 else [item["marker"]]
        if len(members) >= 2:
            # The merged question carries the weight of its
            # most load-bearing member into the cap ranking.
            item["weight"] = max(m["weight"] for m in members)
        primaries.append(item)

    # Cap: most load-bearing first, candidate order breaks ties.
    primaries.sort(key=lambda it: (-it["weight"], it["index"]))
    asked, deferred = primaries[:CAP], primaries[CAP:]
    for item in deferred:
        item["outcome"] = "deferred"
        for m in item.get("members", []):
            for other in items:
                if other["marker"] == m and other is not item:
                    other["outcome"] = "deferred"
                    other["primary"] = item["marker"]

    out = {
        "round": args.round,
        "cap": CAP,
        "questions": [
            {"marker": it["marker"], "body": it["body"],
             "display": it.get("display", it["body"]),
             "context": it.get("context", ""),
             "weight": it["weight"],
             "members": it.get("members", [it["marker"]])}
            for it in asked],
        "grounded": [
            {"marker": it["marker"], "body": it["body"],
             "packet_quote": it["packet_quote"],
             "packet_source": it.get("packet_source", "")}
            for it in items if it["outcome"] == "grounded"],
        "placeholders": [
            {"marker": it["marker"], "body": it["body"],
             "reference_name": it["reference_name"]}
            for it in items if it["outcome"] == "placeholder"],
        "merged": [
            {"marker": it["marker"], "body": it["body"],
             "primary": it.get("primary", "")}
            for it in items if it["outcome"] == "merged"],
        "deferred": [
            {"marker": it["marker"], "body": it["body"],
             "weight": it.get("weight", 3),
             "context": it.get("context", "")}
            for it in items if it["outcome"] == "deferred"],
        "notes": [
            {"marker": it["marker"], "note": it["note"]}
            for it in items if it.get("note")],
    }
    out_path = os.path.join(session_dir, f"triage_{args.round}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"Questions in: {len(candidates)} | asked {len(asked)}, "
          f"grounded {len(out['grounded'])}, "
          f"placeholders {len(out['placeholders'])}, "
          f"merged {len(out['merged'])}, "
          f"deferred {len(out['deferred'])}")
    print(f"Wrote: {out_path}")
    return 0


def do_answers(args):
    session_dir = args.session_dir
    in_path = os.path.join(
        session_dir, f"triage_answers_in_{args.round}.json")
    packet_path = os.path.join(session_dir, "source_packet.md")
    if not os.path.exists(in_path):
        die(f"no answers file at {in_path}")
    if not os.path.exists(packet_path):
        die(f"no packet at {packet_path}")
    with open(in_path, encoding="utf-8") as f:
        answers = json.load(f)
    with open(packet_path, encoding="utf-8") as f:
        packet_text = f.read()
    packet_norm = norm_ws(packet_text).lower()

    lines = ["Answers to classify (question, then the human's answer):"]
    for i, a in enumerate(answers, 1):
        lines.append(f"{i}. Question: {a.get('body', '')}")
        lines.append(f"   Marker: {a.get('marker', '')}")
        lines.append(f"   Answer: {a.get('answer', '')}")
    lines.append("")
    lines.append("SOURCE PACKET:")
    lines.append(packet_text)
    raw = load_verdicts(args, session_dir, f"answers-{args.round}",
                        ANSWERS_SYSTEM, "\n".join(lines))
    by_marker = {}
    for v in raw:
        if isinstance(v, dict) and v.get("marker"):
            by_marker.setdefault(v["marker"], v)

    out = []
    for a in answers:
        marker = a.get("marker", "")
        v = by_marker.get(marker)
        entry = {"marker": marker, "body": a.get("body", ""),
                 "answer": a.get("answer", "")}
        if v is None:
            entry.update(kind="content",
                         note="unclassified - applied as content")
        else:
            kind = str(v.get("kind", "")).strip().lower()
            if kind == "sources":
                quote = norm_ws(v.get("packet_quote", ""))
                entry.update(
                    kind="sources", packet_quote=quote,
                    packet_source=str(v.get("packet_source", ""))[:200],
                    verified=quote_in_packet(quote, packet_norm))
            elif kind == "reference":
                name = norm_ws(v.get("reference_name", "")) or \
                    norm_ws(a.get("answer", ""))
                if name:
                    entry.update(kind="reference",
                                 reference_name=name[:160])
                else:
                    entry.update(kind="content",
                                 note="reference without a name - "
                                      "applied as content")
            else:
                entry.update(kind="content")
        out.append(entry)
    out_path = os.path.join(
        session_dir, f"triage_answers_{args.round}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    kinds = {}
    for e in out:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    print(f"Answers in: {len(answers)} | " +
          ", ".join(f"{k} {n}" for k, n in sorted(kinds.items())))
    print(f"Wrote: {out_path}")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Triage pause questions and pause answers "
                    "against the source packet.")
    ap.add_argument("task", choices=["questions", "answers"])
    ap.add_argument("--session-dir", required=True)
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--model", default=None)
    ap.add_argument("--mode", choices=["env", "vault"], default="env")
    ap.add_argument("--verdicts", default=None,
                    help="JSON file with a 'verdicts' list to use "
                         "instead of a model call (test hook)")
    ap.add_argument("--version", action="store_true")
    args = ap.parse_args()
    if args.version:
        print(f"triage {VERSION}")
        return 0
    if args.task == "questions":
        return do_questions(args)
    return do_answers(args)


if __name__ == "__main__":
    sys.exit(main())
