#!/usr/bin/env python3
"""Packet check: does the packet answer the purpose, as a whole?

Usage:
  packet_check.py --session test-030 [--mode env|vault]
      [--model google/gemini-2.5-flash]

The packet-builder's deterministic gap list says which template
sections are missing, and the relevance calls judge each section
against the purpose — but nothing re-reads the packet as a whole
against the purpose and says "you asked for X and the packet has
nothing on it" (raised Nov 12, 2026, test-036). This script is
that check, run once after the packet is built (and after the
trim chain, if it ran), before the human "Proceed to drafting?"
gate.

It has three steps, all bounded:

1. Check: one model call reads the purpose/scope and the list of
   sections in the packet (titles plus the first ~150 characters
   of each section — the full text is never re-read, which is the
   whole reason the packet exists) and lists anything the purpose
   needs that no section covers. Each missing topic is a short
   phrase of distinctive words, so the machine can search for it.
   The call also classifies the fit (v24, test-044): DIRECT_FIT
   (the source covers the purpose, including the workflow),
   PARTIAL_REGULATORY_FIT (technical/regulatory criteria present,
   site-specific workflow steps missing — not a failure), or
   UNRELATED_MISMATCH (the source has nothing to do with the
   purpose). For a partial fit it also lists the uncovered
   workflow steps, which go to the drafter to flag inline, not
   to the fetch.
2. Fetch: for each missing topic, search the sources for it and
   pull just those sections — a targeted retrieval, a few KB, not
   the whole document. The fetch reads the same docsrc cache the
   packet-builder used, with the same anchor rules as docsrc
   find/get (section boundaries from the anchors, text from the
   cached lines), and adds the found sections to the packet as
   selection_reason "packet-check: <topic>". A small section is
   taken whole; a large one is taken as a ~2,500-char passage
   around the densest cluster of matching lines. Three outcomes:
   a new section is added; the best section is already in the
   packet (the check only saw titles, and the title did not say
   so — e.g. a running header — so it is recorded as already
   covered, not a gap); or nothing in any source scores enough,
   and the topic stays missing. If adding a section would push
   the packet over the 20,000-token cap, it is left out and stays
   missing.
3. Re-check once: the model reads the updated section list. Any
   missing topics it finds now are recorded as still missing.
   There is no second fetch round.

The result is packet_check.json in the session dir:
  {model, fit, uncovered_steps, round1_missing, fetched, covered,
   round2_missing, still_missing, packet_tokens_after}
and the fetched sections are added to source_packet.json (and
source_packet.md is regenerated). The still-missing topics are
shown at the human gate: the user can add a source, narrow the
scope, or proceed and answer them themself. A PARTIAL fit shows a
non-blocking banner at the gate and the uncovered steps go to the
drafter to flag inline. An UNRELATED fit halts at the gate (with
a "Proceed anyway" override) — the draft is not started on a
source that has nothing to do with the purpose. The
plain-language explanation of the fit is written by a separate
step, lookup.py (v26): it obtains what the relevant guidance
says about each uncovered step and assesses whether that covers
the gap, instead of this check writing an explanation from its
own knowledge.

Modes: env (key from OPENROUTER_API_KEY env — the Streamlit path)
or vault (local testing through the Muse OpenRouter helper).
The model call goes through agents/model_call.py.

Exit 0 on a completed check, even when nothing was missing or
nothing was fetched — that is a valid result. Non-zero only on a
real failure (missing files, model call failure, bad JSON); the
app treats that as "check did not run" and proceeds with the
packet as built.
"""

import argparse
import json
import os
import re
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from relevance import write_packet_md  # noqa: E402

SYSTEM_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "packet-check-system.txt")
MODEL_CALL = os.path.join(BASE, "agents", "model_call.py")
VERSION = "1.1"
HARD_CAP_TOKENS = 20000
CHARS_PER_TOKEN = 4
STOPWORDS = {
    "the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "how",
    "where", "what", "when", "is", "are", "it", "its", "by", "with",
    "from", "as", "at", "be", "do", "does", "can", "should", "that",
    "this", "these", "those", "an", "any", "each", "per", "via",
}


def die(msg):
    print(f"PACKET CHECK BLOCKED: {msg}", file=sys.stderr)
    sys.exit(2)


def strip_fence(text):
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").strip()
        if t.lower().startswith("json"):
            t = t[4:].strip()
    return t


def topic_words(topic):
    """Content words of a topic phrase, for searching the source."""
    words = re.findall(r"[a-z0-9][a-z0-9\-]*", topic.lower())
    return [w for w in words if len(w) > 2 and w not in STOPWORDS]


def call_check(model, mode, session_dir, packet, purpose, tag):
    """One check call. Returns (missing, fit, uncovered_steps).

    The section list carries each title plus the first ~150
    characters of the section, so the model judges coverage from
    what the section is about, not just its title (v24, test-044:
    titles alone made a regulatory guideline look like it covered
    a workflow it did not). `fit` is DIRECT_FIT, PARTIAL_REGULATORY_FIT,
    or UNRELATED_MISMATCH; an absent or invalid fit is inferred
    from whether anything is missing (DIRECT when nothing is, PARTIAL
    otherwise) — a banner, never a block, on a confused reply.
    `uncovered_steps` are the operational workflow steps the purpose
    asks for that no section covers; they go to the drafter to flag
    inline, not to the fetch. The plain-language explanation of the
    fit is NOT written here (v26, test-046): the lookup step
    (lookup.py) obtains it from the relevant guidance and assesses
    it, instead of the check writing it from its own knowledge.
    """
    with open(SYSTEM_FILE, encoding="utf-8") as f:
        system = f.read()
    sections = packet.get("relevant_sections", [])
    lines = [
        f"Document type: {packet.get('document_type', 'SOP')}",
        f"Purpose: {purpose.get('purpose', '')}",
        f"In scope: {purpose.get('scope_in', '')}",
        f"Out of scope: {purpose.get('scope_out', '')}",
        f"Intended user: {purpose.get('intended_user', '')}",
        "",
        "Sections in the packet:",
    ]
    for sec in sections:
        snippet = " ".join((sec.get("text") or "").split())[:150]
        lines.append(f"- {sec.get('source')} — {sec.get('title')} "
                     f"(section {sec.get('section_id')}, page {sec.get('page')}): {snippet}")
    lines.append("")
    lines.append("Template sections already listed as missing in the packet "
                 "(do not repeat these):")
    for g in packet.get("gaps", []):
        lines.append(f"- {g.get('what_is_missing', '')}")
    user = "\n".join(lines)
    user_file = os.path.join(session_dir, f"packet-check-user-{tag}.txt")
    sys_file = os.path.join(session_dir, "packet-check-system.txt")
    out_file = os.path.join(session_dir, f"packet-check-raw-{tag}.json")
    with open(user_file, "w", encoding="utf-8") as f:
        f.write(user)
    with open(sys_file, "w", encoding="utf-8") as f:
        f.write(system)
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
    except (KeyError, json.JSONDecodeError):
        die(f"model reply ({tag}) is not JSON.")
    missing = parsed.get("missing", [])
    if not isinstance(missing, list):
        die(f"model reply ({tag}) has no 'missing' list.")
    out = []
    for m in missing:
        if isinstance(m, dict) and m.get("topic"):
            out.append({"topic": str(m["topic"])[:200],
                        "why": str(m.get("why", ""))[:300]})
    fit = parsed.get("fit", "")
    if fit not in ("DIRECT_FIT", "PARTIAL_REGULATORY_FIT", "UNRELATED_MISMATCH"):
        fit = "DIRECT_FIT" if not out else "PARTIAL_REGULATORY_FIT"
    steps = parsed.get("uncovered_steps", [])
    if not isinstance(steps, list):
        steps = []
    steps = [str(s)[:200] for s in steps if s]
    return out, fit, steps


def word_matches(line, w):
    """A content word matches a line as a substring, or by stem.

    Substring covers "safe" in "safety". The stem (first 5 letters)
    covers "operation" in "operate", "operating", "operations" —
    the manual's vocabulary is not the purpose's vocabulary.
    """
    line = line.lower()
    if w in line:
        return True
    if len(w) >= 5:
        pref = w[:5]
        return any(tok.startswith(pref)
                   for tok in re.findall(r"[a-z]+", line))
    return False


def section_of_line(rec, i):
    """Same rule as docsrc: the last anchor at or before line i."""
    cur = None
    for a in rec.get("anchors", []):
        if a.get("line", 0) <= i:
            cur = a
        else:
            break
    return cur


def section_range(rec, anchor):
    """Lines for an anchor, to the next anchor at same-or-higher level."""
    anchors = rec.get("anchors", [])
    n = len(rec.get("lines", []))
    idx = anchors.index(anchor)
    end = n
    for b in anchors[idx + 1:]:
        if b.get("level", 0) <= anchor.get("level", 0):
            end = b.get("line", n)
            break
    return anchor.get("line", 0), end


def section_text(rec, start, end):
    lines = rec.get("lines", [])
    return "\n".join(
        (entry[1] if len(entry) > 1 else "")
        for entry in lines[start:end]).strip()


def section_page(rec, start, end):
    pages = [l[0] for l in rec.get("lines", [])[start:end] if l and l[0]]
    return pages[0] if pages else None


def fetch_topic(topic, cache, packet):
    """Find the best section for a topic across the usable sources.

    Scores each section: a title match is worth 10, each matching
    line is worth 1. A line matches when any of the topic's content
    words matches it (stemmed). The best section needs a score of
    at least 3 — a title hit, or several matching lines.

    Returns (entry, status, existing) where status is one of:
      "added" — a new section to add to the packet;
      "already-covered" — the best section is already in the
          packet (the check only saw titles, and the title did
          not say so — e.g. a running header). `existing` is the
          packet entry it lives in;
      "not-found" — no section in any source scores enough.

    A small section is taken whole. A large one is taken as a
    passage (~2,500 chars) around the densest cluster of matching
    lines — the fetch is targeted, not a whole-document read.
    """
    words = topic_words(topic)
    if not words:
        return None, "not-found", None
    have = {(r.get("source"), r.get("section_id"), r.get("lines", [None])[0])
            for r in packet.get("relevant_sections", [])}
    by_entry = {((r.get("source"), r.get("section_id"),
                  r.get("lines", [None])[0])): r
                for r in packet.get("relevant_sections", [])}
    # Membership by (source, section) as well as by exact range
    # (finding 10): a large section enters the packet as a passage
    # whose start line differs from the section's own start, so
    # the range key above misses it and a second topic matching
    # the same section added it twice.
    have_pair = {(r.get("source"), r.get("section_id"))
                 for r in packet.get("relevant_sections", [])}
    by_pair = {(r.get("source"), r.get("section_id")): r
               for r in packet.get("relevant_sections", [])}
    best = None  # (score, source_name, rec, anchor, [matching lines])
    for name, rec in cache.get("files", {}).items():
        if rec.get("status") not in ("OK", "PARTIAL"):
            continue
        lines = rec.get("lines", [])
        scores = {}
        for i, entry in enumerate(lines):
            text = entry[1] if len(entry) > 1 else ""
            if not any(word_matches(text, w) for w in words):
                continue
            a = section_of_line(rec, i)
            if a is None:
                continue
            key = id(a)
            if key not in scores:
                scores[key] = (a, 0, [])
                title = (a.get("title") or "").lower()
                if any(word_matches(title, w) for w in words):
                    scores[key] = (a, 10, [])
            a2, s, hits = scores[key]
            scores[key] = (a2, s + 1, hits + [i])
        for a, score, hits in scores.values():
            if best is None or score > best[0]:
                best = (score, name, rec, a, hits)
    if best is None or best[0] < 3:
        return None, "not-found", None
    score, name, rec, anchor, hits = best
    section_id = anchor.get("id") or anchor.get("title")
    start, end = section_range(rec, anchor)
    key = (name, section_id, start)
    if key in have:
        return None, "already-covered", by_entry[key]
    if (name, section_id) in have_pair:
        return None, "already-covered", by_pair[(name, section_id)]
    text = section_text(rec, start, end)
    if not text:
        return None, "not-found", None
    if len(text) > 4000 and hits:
        # Passage around the densest cluster of matching lines.
        hits = sorted(hits)
        clusters = [[hits[0]]]
        for h in hits[1:]:
            if h - clusters[-1][-1] <= 15:
                clusters[-1].append(h)
            else:
                clusters.append([h])
        cluster = max(clusters, key=len)
        center = cluster[len(cluster) // 2]
        lo = center
        while lo > start and len(section_text(rec, lo - 1, center)) < 1250:
            lo -= 1
        hi = center + 1
        while hi < end and len(section_text(rec, center, hi + 1)) < 1250:
            hi += 1
        start, end = lo, hi
        text = section_text(rec, start, end)
    return {
        "source": name,
        "section_id": section_id,
        "title": anchor.get("title") or section_id,
        "page": section_page(rec, start, end),
        "lines": [start, end],
        "text": text,
        "chars": len(text),
        "selection_reason": f"packet-check: {topic}",
    }, "added", None


def main():
    ap = argparse.ArgumentParser(description="Check a packet against its purpose.")
    ap.add_argument("--session", help="session id (folder sessions/<id>)")
    ap.add_argument("--session-dir", help="session folder path (overrides --session)")
    ap.add_argument("--model", default="google/gemini-2.5-flash")
    ap.add_argument("--mode", choices=["env", "vault"], default="env")
    ap.add_argument("--version", action="store_true")
    args = ap.parse_args()

    if args.version:
        print(f"packet_check {VERSION}")
        return 0
    if not args.session and not args.session_dir:
        die("--session or --session-dir is required.")

    session_dir = args.session_dir or os.path.join("sessions", args.session)
    packet_path = os.path.join(session_dir, "source_packet.json")
    purpose_path = os.path.join(session_dir, "purpose_scope.json")
    cache_path = os.path.join(session_dir, "docsrc_cache.json")
    for p, what in ((packet_path, "source_packet.json"),
                    (purpose_path, "purpose_scope.json"),
                    (cache_path, "docsrc_cache.json")):
        if not os.path.exists(p):
            die(f"Missing {what}: {p}. Build the packet first.")
    with open(packet_path, encoding="utf-8") as f:
        packet = json.load(f)
    with open(purpose_path, encoding="utf-8") as f:
        purpose = json.load(f)
    with open(cache_path, encoding="utf-8") as f:
        cache = json.load(f)

    # 1. Check.
    round1, fit, uncovered_steps = call_check(
        args.model, args.mode, session_dir, packet, purpose, "round1")

    # 2. Fetch what the check named, within the token cap.
    fetched = []
    covered = []
    still_missing = []
    chars = sum(len(r.get("text") or "") for r in packet.get("relevant_sections", []))
    for m in round1:
        topic = m["topic"]
        entry, status, existing = fetch_topic(topic, cache, packet)
        if status == "already-covered":
            # The check only saw titles, and the title did not say
            # so — the content was in the packet all along, under
            # an uninformative title (e.g. a running header). That
            # is not a gap; record where it lives.
            covered.append({**m,
                            "section": (existing or {}).get("title"),
                            "source": (existing or {}).get("source"),
                            "lines": (existing or {}).get("lines")})
            continue
        if status == "not-found" or entry is None:
            still_missing.append(m)
            continue
        if max(1, (chars + entry["chars"]) // CHARS_PER_TOKEN) > HARD_CAP_TOKENS:
            still_missing.append({**m, "why": m.get("why", "") +
                                  " (not fetched: adding it would exceed the packet cap)"})
            continue
        packet.setdefault("relevant_sections", []).append(entry)
        chars += entry["chars"]
        fetched.append({**m, "source": entry["source"],
                        "section_id": entry["section_id"],
                        "title": entry["title"]})
    if fetched:
        packet["packet_chars"] = chars
        packet["packet_tokens_estimate"] = max(1, chars // CHARS_PER_TOKEN)
        packet["token_estimate"] = packet["packet_tokens_estimate"]
        packet["over_cap"] = packet["token_estimate"] > HARD_CAP_TOKENS
        with open(packet_path, "w", encoding="utf-8") as f:
            json.dump(packet, f, indent=2)
        write_packet_md(session_dir, packet)

    # 3. Re-check once on the updated packet. No second fetch: a
    # round-2 topic that would need a NEW section stays missing.
    # But a round-2 topic is still verified against the packet —
    # the check only sees titles, so it can flag something whose
    # content is already in the packet under an uninformative
    # title. Run the fetch's lookup for that case only: if the
    # best section is already in the packet, it is covered, not
    # a gap. The fit and uncovered steps are re-read too — a fetch
    # that added the missing content can move the fit to DIRECT.
    round2 = []
    if fetched:
        round2, fit, uncovered_steps = call_check(
            args.model, args.mode, session_dir, packet, purpose, "round2")
    for m in round2:
        if m["topic"] in {s["topic"] for s in still_missing}:
            continue
        _, status, existing = fetch_topic(m["topic"], cache, packet)
        if status == "already-covered":
            covered.append({**m,
                            "section": (existing or {}).get("title"),
                            "source": (existing or {}).get("source"),
                            "lines": (existing or {}).get("lines")})
        else:
            still_missing.append(m)

    result = {
        "model": args.model,
        "fit": fit,
        "uncovered_steps": uncovered_steps,
        "round1_missing": round1,
        "fetched": fetched,
        "covered": covered,
        "round2_missing": round2,
        "still_missing": still_missing,
        "packet_tokens_after": packet.get("packet_tokens_estimate"),
    }
    with open(os.path.join(session_dir, "packet_check.json"), "w",
              encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"packet-check: fit {fit}, {len(round1)} missing in round 1, "
          f"{len(fetched)} fetched, {len(covered)} already covered, "
          f"{len(still_missing)} still missing, "
          f"{len(uncovered_steps)} uncovered step(s), "
          f"~{result['packet_tokens_after']} tokens")


if __name__ == "__main__":
    main()
