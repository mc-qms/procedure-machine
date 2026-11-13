"""The Procedure Machine — Streamlit demo, v1.

Public demo, SOPs and Test Methods. The pipeline view shows which agent is
on, what step it is on, and what it took in and produced. It does
NOT show model thoughts, live drafting text, or raw instructions.
Polished instructions live in Streamlit Secrets, not in this repo.
The OpenRouter key comes from st.secrets["OPENROUTER_API_KEY"];
it is never printed, logged, or shown in the UI.

Pipeline, in order:
  purpose-scope (describe in plain words) -> fetch-link -> source-intake
  -> packet-builder (confirm: Proceed to drafting?)
  -> drafting -> HFE -> drafting fixes
  -> cold read -> dedup.py -> drafting fixes -> human-input pause
  -> cold read again -> dedup.py -> drafting fixes -> human-input pause
  -> audit-output check -> download

Human gates are buttons in the pipeline view. The run pauses at
each gate; it does not auto-advance past them. Flagged gaps are
OK at demo conclusion: the final draft is a Discussion Draft,
markers included, downloadable as it stands. When the draft has
flagged gaps, section 3 gives the human a field per gap to answer
them; applying the answers runs one more drafting pass.

Run locally: streamlit run app.py
Deploy: Streamlit Community Cloud, public repo, key in Settings
-> Secrets as OPENROUTER_API_KEY.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from urllib.parse import urlparse

import streamlit as st

BASE = os.path.dirname(os.path.abspath(__file__))
SESSIONS = os.path.join(BASE, "sessions")

def _strip_prompt_echoes(draft_text):
    """Remove prompt-instruction echoes from a revised draft
    (test-048). The uncovered-steps text is passed to the drafting
    model as an instruction in the middle block; in the Cary 60
    live run the model echoed the whole block — header and step
    list — into the bottom of draft_v2.md, so an internal prompt
    instruction shipped inside the SOP. Prompt text is never
    document content: drop the header line and its step list.
    """
    out = []
    lines = draft_text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("UNCOVERED WORKFLOW STEPS"):
            i += 1
            while i < len(lines) and (lines[i].startswith("- ")
                                      or not lines[i].strip()):
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out).rstrip() + "\n"


def _refresh_unresolved_items(draft_text, session_dir):
    """Rebuild the draft's '## Unresolved items' list from the
    draft's actual state (test-048). draft.py appends the packet's
    title-matching gaps at v1; deterministic fills and model
    revisions then fill sections, and the stale list survived —
    in the Cary 60 run it listed all 8 required sections as
    missing in a draft where every one was present and filled.
    Strip whatever list is there and re-append one listing only
    the required sections whose body is still empty or nothing
    but a whole-section gap marker. A section with content plus
    inline markers is resolved as a section — the markers flag
    the specifics in place. If nothing is unresolved, the section
    is omitted. A packet that cannot be read means no refresh,
    not a failed revision.
    """
    text = re.sub(r"(?ms)^## Unresolved items\s*\n.*?(?=^## |\Z)", "",
                  draft_text).rstrip()
    try:
        packet = json.load(open(os.path.join(session_dir, "source_packet.json")))
    except (OSError, json.JSONDecodeError):
        return text + "\n"
    unresolved = []
    for rs in packet.get("required_sections", []):
        title = rs.get("title", "")
        if not title:
            continue
        m = re.search(rf"(?ms)^##\s+\d+\.\s*{re.escape(title)}\s*\n(.*?)(?=^##\s+|\Z)",
                      text)
        body = m.group(1) if m else ""
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        marker_only = bool(lines) and all(
            re.match(r"\[AUTHOR INPUT REQUIRED:.*\]\s*$", ln) for ln in lines)
        if not lines or marker_only:
            unresolved.append(title)
    if unresolved:
        text += "\n\n## Unresolved items\n\n" + "\n".join(
            f"- Required section: {t}: Template requires this section; "
            f"the draft cannot be complete without it." for t in unresolved)
    return text + "\n"


def _ensure_section_content(draft_text, session_dir):
    """Backstop (test-044): after the drafting model runs, a required
    section still empty gets the gap marker, so a section never
    silently vanishes. This is Python scanning AFTER the model —
    the opposite of the old skeleton priming (draft.py used to
    pre-fill the marker before the model ran). Reads the template's
    required titles from source_packet.json; a packet that cannot
    be read means no backstop, not a failed revision.
    """
    try:
        packet = json.load(open(os.path.join(session_dir, "source_packet.json")))
    except (OSError, json.JSONDecodeError):
        return draft_text
    for rs in packet.get("required_sections", []):
        title = rs.get("title", "")
        if not title:
            continue
        m = re.search(rf"(?m)^##\s+\d+\.\s+{re.escape(title)}\s*$", draft_text)
        if not m:
            continue
        start = m.end()
        nxt = re.search(r"(?m)^##\s+", draft_text[start:])
        body = draft_text[start:start + nxt.start()] if nxt else draft_text[start:]
        if body.strip():
            continue
        marker = (f"[AUTHOR INPUT REQUIRED: {title} - required section, "
                  f"not present in any OK source. Do not invent.]")
        draft_text = draft_text[:start] + "\n" + marker + "\n" + draft_text[start:]
    return draft_text


# Model-call record prefixes (test-042, Nov 12, 2026): the trim
# chain and the packet check write one record file per model call
# into the session folder (relevance-user-0.txt, compact-user-0-p2.txt,
# packet-check-user-round1.txt, plus -system- and -raw- variants).
# The source filter used to exclude only files ending in -user.txt /
# -system.txt / _raw.json, so these slipped through and were read as
# sources on the next build in the same session — and listed as
# "stored sources". They are never sources.
_MODEL_RECORD_PREFIXES = ("relevance-", "compact-", "packet-check-", "lookup-")

# The loop, in order, as the user sees it. Drafting and cold read
# repeat — that is the loop, not a display bug (Nov 12, 2026:
# the flat list hid the repeats, so drafting after HFE looked
# like it never happened). Each entry is (key, label, role,
# description). Descriptions are plain language: no model names,
# no "mid-tier", no "LLM" — none of that means anything to a
# user. Dedup is not listed: it is a back-end step that makes
# the loop work, not a step a user needs to see. The two
# conditional drafting steps (after each pause) run only when
# the human answered something; otherwise they are marked done
# with "no answers to apply", the same way a pause with nothing
# to ask is marked done.
STAGES = [
    ("purpose-scope", "purpose-scope", "Intake", "Describe the document in plain words; the machine reads out purpose, scope, and audience."),
    ("fetch-link", "fetch-link", "Intake", "Fetch the public links you gave."),
    ("source-intake", "source-intake", "Intake", "Read the source documents into text the machine can work with."),
    ("packet-builder", "packet-builder", "Intake", "Pick the parts of the sources that matter for this document, and condense them into a packet."),
    ("drafting-1", "drafting", "Drafting", "Write the first draft from the packet."),
    ("human-factors", "human-factors", "HFE", "Check whether a qualified user can actually follow the draft in order."),
    ("drafting-2", "drafting", "Drafting", "Revise the draft from the HFE findings."),
    ("cold-read-1", "cold-read", "Audit", "Read the draft cold, as a qualified user who has never seen it, and list what could go wrong — most load-bearing first."),
    ("drafting-3", "drafting", "Drafting", "Revise the draft from the cold-read findings."),
    ("human-input-1", "human-input-1", "Human input", "Pause after cold read 1: questions the drafting agent could not resolve. Only when there is something to ask."),
    ("drafting-4", "drafting", "Drafting", "Revise the draft from your answers."),
    ("cold-read-2", "cold-read", "Audit", "Read the draft cold again, including your answers, and list what could go wrong — most load-bearing first."),
    ("drafting-5", "drafting", "Drafting", "Revise the draft from the second cold-read findings."),
    ("human-input-2", "human-input-2", "Human input", "Pause after cold read 2: questions the drafting agent could not resolve. Only when there is something to ask."),
    ("drafting-6", "drafting", "Drafting", "Final drafting: revise the draft from your answers."),
    ("audit-output", "audit-output", "Audit", "Final check: numbering, cross-references, and any gap markers left in the draft."),
]

# ---------------------------------------------------------------- helpers
def run(cmd, cwd=BASE, env=None, timeout=300):
    """Run a script. Returns (exit_code, stdout). No secrets in args.
    env, when given, is merged over os.environ (for passing a key
    to a subprocess that reads it from the environment). A timeout
    returns exit code 124 with a plain message instead of raising
    subprocess.TimeoutExpired into the UI (finding 7); callers
    that run multi-call scripts (the trim chain) pass a larger
    budget, because one slow model call inside them may itself
    run for minutes.
    A leading "python3" is replaced with sys.executable — the
    interpreter running this app, which is the one with the
    project's libraries (pypdf). The bare "python3" on PATH can be
    a system Python without them, which made docsrc report every
    PDF UNREADABLE while still exiting 0 (found Nov 11, 2026,
    test-025: the live app's Q1 packet came back empty, 0 relevant,
    ~1 token, whether the PDF was linked or uploaded)."""
    if cmd and cmd[0] == "python3":
        cmd = [sys.executable] + list(cmd[1:])
    full_env = dict(os.environ, **env) if env else None
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=full_env)
    except subprocess.TimeoutExpired:
        return 124, f"Timed out after {timeout}s running: {' '.join(str(c) for c in cmd[:4])}"
    return r.returncode, r.stdout + r.stderr


def _stored_sources(session_dir):
    """Source files already in this session (from an earlier use).

    The same filter the intake uses: a real source file in the
    session folder, not a packet, a draft, a cache, or a model
    call record. A new build includes these unless the user
    clears them — that is how a second document tried in the
    same session silently joined the first one (test-040).
    """
    exclude = {"purpose_scope.json", "source_packet.json", "source_packet.md",
               "docsrc_cache.json", "custom-template.json"}
    if not os.path.isdir(session_dir):
        return []
    return sorted(
        f for f in os.listdir(session_dir)
        if f.endswith((".txt", ".md", ".pdf", ".docx"))
        and f not in exclude
        and not f.startswith(("draft_", "source_packet") + _MODEL_RECORD_PREFIXES)
        and not f.endswith(("_raw.json", "-system.txt", "-user.txt")))


def _clear_session_files(session_dir):
    """Delete the stored source files from this session.

    Derived outputs are cleared separately by _clear_derived
    (which also resets the stage statuses). Returns the names
    of the source files deleted. The files are the user's own
    documents — clearing only removes the server's copy; they
    would need to be uploaded or fetched again.
    """
    deleted = []
    for name in _stored_sources(session_dir):
        path = os.path.join(session_dir, name)
        if os.path.exists(path):
            os.remove(path)
            deleted.append(name)
    # The intake cache and fetch record describe the deleted
    # sources; leaving them would let a rebuild read stale
    # records. Delete them too.
    for name in ("docsrc_cache.json", "fetch_record.json", "packet_check.json",
                 "lookup.json"):
        path = os.path.join(session_dir, name)
        if os.path.exists(path):
            os.remove(path)
    return deleted


def _reset_session_files(session_dir):
    """Delete EVERY file in the session folder (test-060).

    The complete reset Manuel asked for (Nov 13, 2026): the v21
    clear removed stored sources, but the packet, drafts,
    findings, model-call records, purpose, and any custom
    template all stayed, so one test's leftovers could follow
    the user into the next document. A reset leaves the session
    folder empty — nothing from a previous document can leak
    into the next one. Everything in the folder is per-session
    work product; the user's originals live on their own device.
    Returns the number of files deleted.
    """
    deleted = 0
    if os.path.isdir(session_dir):
        for name in os.listdir(session_dir):
            path = os.path.join(session_dir, name)
            if os.path.isfile(path):
                os.remove(path)
                deleted += 1
    return deleted


def _clear_derived(session_dir):
    """Delete derived outputs from an earlier run in this session.

    A new build starts clean. Without this, a failed build leaves a
    stale packet behind and the app offers drafting on data from the
    previous run (found Nov 11, 2026: a Q1 packet build failed over
    cap, the old packet stayed, and drafting ran on it — so nothing
    was pulled and the draft came out all gaps). Inputs are never
    touched: uploaded and fetched source files stay.
    """
    derived = ("packet_check.json", "lookup.json",
               "source_packet.json", "source_packet.md",
               "draft_v1.md", "draft_v1.txt", "draft_v1_summary.json",
               "draft_v2.md", "draft_v2.txt",
               "draft_v3.md", "draft_v3.txt",
               "draft_final.md", "draft_final.txt",
               "hfe_findings.json",
               "cold_read_findings_1.json", "cold_read_findings_2.json",
               "cold_read_filtered_1.json", "cold_read_filtered_2.json")
    for name in derived:
        path = os.path.join(session_dir, name)
        if os.path.exists(path):
            os.remove(path)
    for name in os.listdir(session_dir):
        if (name.endswith("_raw.json")
                or name.startswith(_MODEL_RECORD_PREFIXES)
                or name.endswith(("-user.txt", "-system.txt"))):
            os.remove(os.path.join(session_dir, name))
    for name in list(st.session_state.get("stage_status", {})):
        st.session_state.stage_status[name] = "waiting"


def _run_exists(session_dir):
    """True when this session already holds a run worth discarding:
    any draft on disk, or a loop in progress. A packet alone does not
    count — rebuilding over a packet that was never drafted loses
    nothing the rebuild does not recreate."""
    if st.session_state.get("loop_step"):
        return True
    for name in ("draft_v1.md", "draft_v2.md", "draft_v3.md",
                 "draft_final.md"):
        if os.path.exists(os.path.join(session_dir, name)):
            return True
    return False



def _secret(name):
    """A Streamlit Secret, or None when it is not set."""
    try:
        return st.secrets[name]
    except Exception:
        return None


# Prompt currency anchors (v35): each polished prompt in Secrets
# carries a version tag on its first line. The instructions used
# to be patched at runtime by rules appended in code whenever the
# Secrets copy lagged; v35 retired the appends and folded every
# rule into the Secrets texts themselves, so a lagging Secrets
# copy must now fail loudly instead of silently losing the folded
# rules. The check is a plain substring test at each prompt's
# existing missing-prompt gate.
_PROMPT_ANCHORS = {
    "DRAFTING_SYSTEM_PROMPT": "PM-DRAFTING-V35",
    "HFE_SYSTEM_PROMPT": "PM-HFE-V35",
    "COLD_READ_SYSTEM_PROMPT": "PM-COLDREAD-V35",
}


def _prompt_outdated(name, prompt):
    """An error message when the Secrets prompt predates the
    current instruction set, else None. `prompt` is the value
    already fetched (and already known non-empty)."""
    anchor = _PROMPT_ANCHORS.get(name)
    if anchor and anchor not in prompt:
        return (f"{name} in Streamlit Secrets is out of date — it predates the "
                f"current instructions, so the run stops here instead of "
                f"drafting without them. Update that one value in "
                f"Settings → Secrets with the current prompt text and "
                f"reboot the app.")
    return None


def _model_call(session_dir, name, system_prompt, user_text, model):
    """Run agents/model_call.py --mode env with the Secrets key.

    Returns (ok, content, usage). The key comes from st.secrets and
    is passed only as an env var to the subprocess; it is never
    printed or logged.
    """
    sys_file = os.path.join(session_dir, name + "-system.txt")
    user_file = os.path.join(session_dir, name + "-user.txt")
    out_file = os.path.join(session_dir, name + "_raw.json")
    with open(sys_file, "w") as f:
        f.write(system_prompt)
    with open(user_file, "w") as f:
        f.write(user_text)
    key = _secret("OPENROUTER_API_KEY")
    if not key:
        return False, "No OPENROUTER_API_KEY in Streamlit Secrets. Add it in Settings → Secrets.", ""
    r = subprocess.run([sys.executable, os.path.join(BASE, "agents", "model_call.py"),
                        "--mode", "env", "--model", model,
                        "--system-file", sys_file, "--user-file", user_file,
                        "--out", out_file],
                       cwd=BASE, capture_output=True, text=True, timeout=300,
                       env=dict(os.environ, OPENROUTER_API_KEY=key))
    if r.returncode != 0:
        return False, (r.stdout + r.stderr).strip()[:500], ""
    data = json.load(open(out_file))
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    cost = usage.get("cost")
    usage_str = f"{usage.get('total_tokens', '?')} tokens"
    if isinstance(cost, (int, float)):
        usage_str += f", ${cost:.4f}"
    return True, content, usage_str


def _strip_fence(text):
    """Strip a ```json code fence from a model reply, if present."""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").strip()
        if t.lower().startswith("json"):
            t = t[4:].strip()
    return t


def _split_draft(reply):
    """Draft portion is everything before a 'Revision Summary:' line."""
    lines = reply.split("\n")
    for i, line in enumerate(lines):
        # The model writes the heading as "Revision Summary:" or
        # "## Revision Summary" — match either (test-013 wrote ##).
        if line.strip().lstrip("#").strip().lower().startswith("revision summary"):
            return "\n".join(lines[:i]).rstrip() + "\n", "\n".join(lines[i:]).strip()
    return reply, ""


_EXTRACT_SYSTEM = """Extract the purpose, scope, and audience of a document from the user's plain-words description, and say what kind of document it is. Return JSON only, exactly these keys: purpose, scope_in, scope_out, intended_user, document_type, template, template_reason, template_description. document_type is "SOP" or "Test Method". template is one of "sop-default", "equipment-sop", "test-method-default", or "custom": sop-default for a plain process SOP; equipment-sop when the description is about operating, maintaining, or troubleshooting a piece of equipment or an instrument; test-method-default when it is a bench-level analytical test method; custom only when none of those fit, and then template_description says in plain words what sections the template needs. document_type must agree with the template: test-method-default is a Test Method, the other three are SOPs. template_reason is one short sentence saying why that template fits. scope_out may be an empty string when the description does not state anything out of scope. Do not invent details that are not in the description; if the intended user is not stated, use an empty string. Write purpose and scope in the document's own voice, as they will appear in the finished document: the user wrote a request, not document text, so rephrase their wording into document language rather than copying it. Never carry over references to the source material or to the request itself — no chapter or page ranges, no mention of a manual or of what the description asks for. scope_in states what the document governs — the activities, the equipment, and the setting — in those terms only. When the description names source structure (for example that it covers certain chapters of a manual), translate that into the activity it describes, which belongs in scope_in; the structural reference itself does not."""


_TEMPLATES = ("sop-default", "equipment-sop", "test-method-default")


def _pick_template(user_choice, extracted):
    """Resolve which template the packet is built with.

    The user leaves the picker on Auto by default: the
    extraction call reads the description and picks the
    template. An explicit user choice wins. Returns (template,
    reason, custom_description): template is a preset id or
    "custom"; custom_description is set only when the machine
    picked custom and described the template it needs.
    """
    if user_choice != "Auto (from your description)":
        return user_choice, "", None
    t = (extracted or {}).get("template") or "sop-default"
    if t not in _TEMPLATES and t != "custom":
        t = "sop-default"
    reason = (extracted or {}).get("template_reason") or ""
    desc = (extracted or {}).get("template_description") or "" if t == "custom" else None
    return t, reason, desc


def _extract_purpose_scope(session_dir, description):
    """Read purpose/scope/audience out of one free-text description.

    Small Flash call, structured JSON. Also reads what kind of
    document the description asks for and which template fits —
    that is the intake knowing the shape, not the user picking
    it first. Returns (fields, read_ok). When there is no key,
    falls back to the description as the purpose with the rest
    blank, so the user fills the fields in by hand.
    """
    model = _secret("MODEL_EXTRACTION") or "google/gemini-2.5-flash"
    ok, content, _usage = _model_call(session_dir, "extract", _EXTRACT_SYSTEM,
                                      f"DESCRIPTION:\n{description}", model)
    blank = {"purpose": description.strip(), "scope_in": "", "scope_out": "",
             "intended_user": "", "document_type": "SOP", "template": "sop-default",
             "template_reason": "", "template_description": ""}
    if not ok:
        return blank, False
    try:
        data = json.loads(_strip_fence(content))
        fields = {k: (data.get(k) or "") for k in
                  ("purpose", "scope_in", "scope_out", "intended_user",
                   "template_reason", "template_description")}
        fields["document_type"] = data.get("document_type") or "SOP"
        if fields["document_type"] not in ("SOP", "Test Method"):
            fields["document_type"] = "SOP"
        fields["template"] = data.get("template") or "sop-default"
        if fields["template"] not in _TEMPLATES and fields["template"] != "custom":
            fields["template"] = "sop-default"
        return fields, True
    except (json.JSONDecodeError, AttributeError):
        return blank, False


def _deterministic_fills(session_dir):
    """The deterministic section fills, same text as draft.py
    builds. Returns {title: fill_text}. Records and References
    come from the packet's source list; Responsibilities comes
    from the packet's intended_user. Returns {} when the packet
    has neither."""
    try:
        packet = json.load(open(os.path.join(session_dir, "source_packet.json")))
    except (OSError, json.JSONDecodeError):
        return {}
    fills = {}
    # OK or PARTIAL: a source that was read, even partly, is still a
    # source the procedure was built from. (Test-029: the Cary 60
    # manual read PARTIAL and Records/References asked the human
    # for what the packet already answered.)
    srcs = [s.get("name", "?") for s in packet.get("sources", [])
            if s.get("status") in ("OK", "PARTIAL")]
    if srcs:
        fills["Records"] = ("Records: the source documents this procedure was built "
                            "from: " + "; ".join(srcs) + ".")
        fills["References"] = ("References: the source documents this procedure was built "
                               "from: " + "; ".join(srcs) + ".")
    who = (packet.get("intended_user") or "").strip()
    if who:
        fills["Responsibilities"] = f"Responsibilities: {who}"
    return fills


def _restore_deterministic_fills(draft_text, session_dir):
    """Re-apply the deterministic fills after a model revision.

    draft.py fills Records and References from the packet's
    sources and Responsibilities from the packet's intended_user,
    but a revision model can re-flag one ("no records specified",
    "no roles defined") — the finding is fair as a review point,
    but the fill is a design rule, so the code restores it. Only
    the loop's revision calls use this; the section-3 Apply step
    does not, because a blank answer there means "leave it
    flagged" and a given answer is the author's own text.
    """
    fills = _deterministic_fills(session_dir)
    if not fills:
        return draft_text
    lines = draft_text.splitlines()
    for title, fill in fills.items():
        head_re = re.compile(rf"^## \d+(\.\d+)?\. {re.escape(title)}\s*$")
        start = next((i for i, ln in enumerate(lines) if head_re.match(ln.strip())), None)
        if start is None:
            continue
        end = next((i for i in range(start + 1, len(lines))
                    if lines[i].startswith("## ")), len(lines))
        body = "\n".join(lines[start + 1:end])
        if "[AUTHOR INPUT REQUIRED" not in body:
            continue
        lines = lines[:start + 1] + ["", fill, ""] + lines[end:]
    return "\n".join(lines)


def _draft_first(session_dir, packet_md, model, drafting_prompt):
    """The model writes the first draft (v29, test-049).

    Until v28, draft.py assembled draft v1 in Python — packet
    sections title-matched to template headings and stitched in
    verbatim — and the model spent the loop revising that stitched
    draft with its domain knowledge walled off. Manuel, on the
    Cary 60 atrocity: "We built it wrong. Make the model write
    the first draft." Now the drafting model writes v1 from the
    template headings, the purpose, and the packet: structure and
    standard practice from its knowledge, facts and values from
    the packet only, gaps marked inline. Python keeps what it
    does well — the packet, the deterministic header and fills,
    the marker backstop, the unresolved-items refresh. Returns
    (ok, draft_text_or_error); on failure the caller retries
    once, then stops the run — there is no skeleton fallback
    (v30, test-050).
    """
    try:
        packet = json.load(open(os.path.join(session_dir, "source_packet.json")))
    except (OSError, json.JSONDecodeError):
        return False, "source_packet.json could not be read."
    doc_type = packet.get("document_type", "SOP")
    required = [rs.get("title", "") for rs in packet.get("required_sections", [])
                if rs.get("title")]
    if not required:
        return False, "The packet lists no required sections."
    headings = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(required))
    lines = [
        f"Write the FIRST draft of this {doc_type}. There is no prior draft "
        "and there are no findings — you are the drafter, not a reviser.",
        "",
        f"Purpose: {packet.get('purpose', '')}",
        f"In scope: {packet.get('scope_in', '')}",
    ]
    if packet.get("scope_out"):
        lines.append(f"Out of scope: {packet.get('scope_out')}")
    lines += [
        f"Intended user: {packet.get('intended_user', '')}",
        "",
        "Use exactly these section headings, in this order:",
        headings,
        "",
        "Write the draft the way a competent author in this field would: "
        "use your knowledge of how this kind of document and this setting "
        "work for the structure, the responsibilities, and standard "
        "practice; use the source packet for the facts, values, and "
        "specifics. Facts and values come from the packet only — where "
        "the packet does not cover something a section needs, mark it "
        "inline with [AUTHOR INPUT REQUIRED: ...]. Begin at the first "
        "section heading — the document header is added by the machine. "
        "After the full draft, add a line 'Revision summary' and one "
        "short line on what you did.",
        "",
    ]
    steps = _uncovered_steps_text(session_dir)
    if steps:
        lines.append(steps)
    lines.append(f"SOURCE PACKET:\n{packet_md}")
    user = "\n".join(lines)
    ok, reply, _usage = _model_call(
        session_dir, "draft-first", drafting_prompt, user, model)
    if not ok:
        return False, reply
    draft_text, _summary = _split_draft(reply)
    # Canonicalize the section headings (Python owns the schema):
    # the model does not reliably emit '## N. Title' — in testing
    # it used '## Discussion Draft' as a title with the sections
    # at '### N.', which every downstream section check would
    # miss. Find each required section's heading and rewrite it
    # to the canonical form; drop anything before the first
    # required section (the model's own title lines). A required
    # section with no heading fails the draft — the caller
    # retries once, then stops the run (v30: no skeleton
    # fallback). The match accepts the heading forms models
    # actually emit — markdown at any level, bold, a numbered
    # plain line, or the bare title on its own line (v33,
    # test-057: Luna wrote plain numbered headings in 3 of 6
    # first-draft attempts, DeepSeek in both of its; the
    # content was fine, only the heading style differed, and
    # recognizing a numbered or bold heading is the same
    # schema normalization as rewriting its level).
    raw_lines = draft_text.splitlines()
    positions = []
    for i, title in enumerate(required):
        pat = re.compile(
            rf"^(?:#{{2,4}}\s+|\*\*\s*)?(?:\d+\.?\s+)?"
            rf"{re.escape(title)}\s*(?:\*\*)?$")
        idx = next((j for j, ln in enumerate(raw_lines)
                    if pat.match(ln.strip())), None)
        if idx is None:
            return False, f"The drafting model returned no '{title}' section."
        positions.append((idx, i, title))
    positions.sort()
    # Reassemble in template order (finding 12): renumbering the
    # headings in emitted order used to leave a draft whose
    # sections ran 3, 2, 1 when the model wrote them out of
    # order — the numbers matched the titles but not the
    # sequence, and nothing downstream flagged it. Each found
    # heading's segment runs to the next found heading; the
    # segments are then emitted in template order.
    segments = {}
    for k, (idx, i, title) in enumerate(positions):
        end = positions[k + 1][0] if k + 1 < len(positions) else len(raw_lines)
        segments[i] = raw_lines[idx:end]
    body_lines = []
    for i in range(len(required)):
        seg = segments[i]
        seg[0] = f"## {i + 1}. {required[i]}"
        body_lines.extend(seg)
    # The header is deterministic (Python owns it): the same
    # header draft.py writes, prepended to the model's sections.
    header_lines = [
        f"# {doc_type} — Discussion Draft",
        "",
        "Status: Discussion Draft. Not a clean copy. Formal appearance "
        "does not imply approval.",
        f"Packet: {packet.get('packet_id')}  Template: {packet.get('template_id')}",
        f"Authority route: {packet.get('authority_route')}  "
        f"Work mode: {packet.get('work_mode')}",
        f"Purpose: {packet.get('purpose')}",
        f"Scope: {packet.get('scope_in')}",
    ]
    if packet.get("scope_out"):
        header_lines.append(f"Out of scope: {packet.get('scope_out')}")
    header_lines.append("")
    draft_text = "\n".join(header_lines + body_lines) + "\n"
    # Same post-processing as a revision: no prompt echoes, one
    # marker kind, deterministic fills, the empty-section
    # backstop, and an unresolved list that matches the draft.
    draft_text = _strip_prompt_echoes(draft_text)
    draft_text = _normalize_markers(draft_text)
    draft_text = _restore_deterministic_fills(draft_text, session_dir)
    draft_text = _ensure_section_content(draft_text, session_dir)
    draft_text = _refresh_unresolved_items(draft_text, session_dir)
    return True, draft_text


def _revise(session_dir, packet_md, model, drafting_prompt, current_file, middle, label, restore_fills=False):
    """One drafting revision call. Returns (ok, draft_text_or_error).

    `middle` is the findings or the author input, between the draft
    and the packet. The model sees draft + middle + packet only.
    With restore_fills, the deterministic fills (Records and
    References from sources, Responsibilities from intended_user)
    are re-applied if the revision re-flagged them (see
    _restore_deterministic_fills). The section-3 Apply step leaves
    it off, so a blank answer stays flagged.
    """
    draft_md = _draft_text(session_dir, current_file)
    user = f"DRAFT {label}:\n{draft_md}\n\n{middle}\n\nSOURCE PACKET:\n{packet_md}"
    ok, reply, _usage = _model_call(session_dir, "draft-revise", drafting_prompt, user, model)
    if not ok:
        return False, reply
    draft_text, _summary = _split_draft(reply)
    # Prompt text is never document content (test-048): the model
    # echoed the uncovered-steps instruction block into the bottom
    # of a live draft. Strip any echo before anything else reads
    # the draft.
    draft_text = _strip_prompt_echoes(draft_text)
    # One marker kind: every gap is author input. The four kinds
    # come from the work design, where different people handle
    # different markers; in the demo there is one human. Normalize
    # here, before the fills check, so a marker the model wrote
    # with an old kind still counts as the same question (the
    # re-ask found live Nov 12, 2026, test-034: the same question
    # with a different prefix counted as new). The drafting prompt
    # in Secrets may lag; the saved draft always has one kind.
    draft_text = _normalize_markers(draft_text)
    if restore_fills:
        draft_text = _restore_deterministic_fills(draft_text, session_dir)
    # Backstop (test-044): a required section the model left empty
    # gets the gap marker, so it never silently vanishes. This runs
    # after the model, not before it — the opposite of priming.
    draft_text = _ensure_section_content(draft_text, session_dir)
    # Unresolved-items refresh (test-048): rebuild the list from
    # the draft's actual state, so sections the fills or the model
    # resolved drop off it. Runs last, on the final text.
    draft_text = _refresh_unresolved_items(draft_text, session_dir)
    return True, draft_text


_MARKER_RE = re.compile(r"\[(AUTHOR INPUT REQUIRED|TECHNICAL PARAMETER REQUIRED|QA REVIEW REQUIRED|REFERENCE CONFLICT):([^\]]+)\]")


def _normalize_markers(draft_text):
    """Rewrite every gap marker to the single kind, AUTHOR INPUT
    REQUIRED. The regex still matches the older kinds (old drafts
    and a lagging drafting prompt may carry them); the saved draft
    always has one kind."""
    return _MARKER_RE.sub(r"[AUTHOR INPUT REQUIRED:\2]", draft_text)


def _marker_body(marker):
    """The question text inside a marker, without its kind prefix.
    Two markers with the same body are the same question, whatever
    kind prefix the model put on them."""
    m = _MARKER_RE.match(marker)
    return m.group(2).strip() if m else marker


def _find_markers(draft_text):
    """Unique gap markers in a draft, in order of first appearance."""
    seen = []
    for kind, body in _MARKER_RE.findall(draft_text):
        marker = f"[{kind}: {body.strip()}]"
        if marker not in seen:
            seen.append(marker)
    return seen


def _draft_text(session_dir, fname):
    with open(os.path.join(session_dir, fname)) as f:
        return f.read()


def _packet_text(session_dir):
    return _draft_text(session_dir, "source_packet.md")


def _pause_questions(session_dir, current):
    """Markers in the current draft the human has not been shown at a
    pause yet. The drafting agent gets first crack: this runs after
    the drafting correction that follows a cold read, so a marker
    here is one drafting could not resolve — that is what "really
    needed" means. A marker shown at an earlier pause is not
    asked again; it stays flagged and shows up in section 3 at
    the end if it is still there. Compared by question text
    (body), not by full marker: the same question with a
    different kind prefix is the same question."""
    shown_bodies = {_marker_body(s) for s in st.session_state.get("pause_shown", [])}
    markers = _find_markers(_draft_text(session_dir, current))
    return [m for m in markers if _marker_body(m) not in shown_bodies]


def _apply_pause_answers(session_dir, current, answers):
    """Apply the human's pause answers to the current draft, one
    drafting revision with the answers as AUTHOR INPUT. Returns
    (ok, remaining_markers, error). Same shape as the section-3
    Apply, but on the loop's current draft instead of the final."""
    packet_md = _packet_text(session_dir)
    model = _secret("MODEL_DRAFTING") or "openai/gpt-6-luna"
    drafting_prompt = _secret("DRAFTING_SYSTEM_PROMPT")
    if not drafting_prompt:
        return False, 0, "DRAFTING_SYSTEM_PROMPT is not in Streamlit Secrets."
    _od = _prompt_outdated("DRAFTING_SYSTEM_PROMPT", drafting_prompt)
    if _od:
        return False, 0, _od
    author_text = "\n".join(f"- {m}\n  Answer: {a}" for m, a in answers.items())
    ok, new_draft = _revise(session_dir, packet_md, model, drafting_prompt,
                            current,
                            "AUTHOR INPUT — answers supplied by the human for the flagged gaps. "
                            "These are author decisions, not source-packet facts. Use them to replace "
                            "the gap markers they answer. Do not invent anything beyond what is written here.\n\n" + author_text,
                            "pause", restore_fills=True)
    if not ok:
        return False, 0, new_draft
    with open(os.path.join(session_dir, current), "w") as f:
        f.write(new_draft)
    with open(os.path.join(session_dir, current.replace(".md", ".txt")), "w") as f:
        f.write(new_draft)
    code, out = run(["python3", os.path.join(BASE, "skills/source-intake/scripts/docsrc.py"),
                     "check", os.path.join(session_dir, current.replace(".md", ".txt"))],
                    cwd=session_dir)
    if code != 0:
        return False, 0, f"Delivery check failed: {out.strip()[:300]}"
    return True, len(_find_markers(new_draft)), ""


def _uncovered_steps_text(session_dir):
    """Uncovered workflow steps from the packet check (v24), as text
    for the drafter. A partial fit means the source has the technical
    rules but not the site-specific workflow steps; the drafter flags
    those inline in the relevant Procedure subsection instead of
    leaving the whole section as a gap. Returns "" when there is no
    check, no partial fit, or no uncovered steps. Read from disk —
    session state does not survive a page reload.
    """
    try:
        check = json.load(open(os.path.join(session_dir, "packet_check.json")))
    except (OSError, json.JSONDecodeError):
        return ""
    if check.get("fit") != "PARTIAL_REGULATORY_FIT":
        return ""
    steps = check.get("uncovered_steps", [])
    if not steps:
        return ""
    return ("UNCOVERED WORKFLOW STEPS (from the packet check — the source does not cover "
            "these; they are gaps to flag, NOT the document's structure and NOT the user's "
            "workflow): never use them as section or sub-section headings and do not "
            "organize the document around them — the structure comes from the user's "
            "purpose and the template. Place each one as an inline marker inside the "
            "section whose subject it belongs to; if no section fits, one marker in the "
            "Procedure under the closest existing sub-heading. Do not leave a whole "
            "section as a gap for their sake:\n" +
            "\n".join(f"- {s}" for s in steps) + "\n")


def _run_packet_check(session_dir):
    """Packet check after a packet build (v18).

    One model call reads the purpose/scope and the packet's section
    list, then a targeted fetch pulls just the sections it names
    (a few KB, not the whole document), then one re-check. Returns
    the check dict, or None if the check did not run (no key, model
    failure). A failed check never blocks the build — the packet is
    still usable.
    """
    check_path = os.path.join(session_dir, "packet_check.json")
    key = _secret("OPENROUTER_API_KEY")
    if not key:
        if os.path.exists(check_path):
            os.remove(check_path)
        return None
    code, out = run(["python3", "skills/packet-builder/scripts/packet_check.py",
                     "--session-dir", session_dir,
                     "--mode", "env",
                     "--model", _secret("MODEL_PACKET_CHECK") or "google/gemini-2.5-flash"],
                    env={"OPENROUTER_API_KEY": key})
    if code != 0 or not os.path.exists(check_path):
        if os.path.exists(check_path):
            os.remove(check_path)
        return None
    try:
        return json.load(open(check_path))
    except (json.JSONDecodeError, OSError):
        if os.path.exists(check_path):
            os.remove(check_path)
        return None


def _run_lookup(session_dir):
    """Lookup after a packet check (v26).

    For each uncovered workflow step the packet check found, one
    cheap model call obtains what the relevant guidance says about
    it and assesses whether that covers the gap — the agent doing
    what the user did with a search AI, instead of writing an
    explanation from its own knowledge (v25, removed). Runs only
    for a partial fit with uncovered steps; otherwise writes an
    empty lookup.json. Returns the lookup dict, or None if it did
    not run (no key, script failure). A failed lookup never blocks
    the build — the gate shows what was found, or that the lookup
    did not run.
    """
    lookup_path = os.path.join(session_dir, "lookup.json")
    key = _secret("OPENROUTER_API_KEY")
    if not key:
        if os.path.exists(lookup_path):
            os.remove(lookup_path)
        return None
    code, out = run(["python3", "skills/packet-builder/scripts/lookup.py",
                     "--session-dir", session_dir,
                     "--mode", "env",
                     "--model", _secret("MODEL_LOOKUP") or "google/gemini-2.5-flash-lite"],
                    env={"OPENROUTER_API_KEY": key})
    if code != 0 or not os.path.exists(lookup_path):
        if os.path.exists(lookup_path):
            os.remove(lookup_path)
        return None
    try:
        return json.load(open(lookup_path))
    except (json.JSONDecodeError, OSError):
        if os.path.exists(lookup_path):
            os.remove(lookup_path)
        return None


def _docsrc_check_summary(session_dir, txt_name):
    """Run docsrc `check` on a draft and compress its output to a
    one-line summary (finding 2: the check used to be computed at
    three call sites and discarded by all of them, so the
    audit-output stage showed done regardless of what it found).
    Returns (summary, error): summary is None when the check
    itself crashed — findings never make it fail; the check
    reports facts and the human judges them. Non-blocking by
    design, consistent with the delivery-gate philosophy: the
    numbers are shown, not enforced."""
    code, out = run(["python3", os.path.join(BASE, "skills/source-intake/scripts/docsrc.py"),
                     "check", os.path.join(session_dir, txt_name)],
                    cwd=session_dir)
    if code != 0:
        return None, f"Delivery check failed: {out.strip()[:300]}"

    def _bullets(header):
        m = re.search(re.escape(header) + r"[^\n]*\n((?:- .*\n?)*)", out)
        return [ln[2:].strip() for ln in (m.group(1).splitlines() if m else []) if ln.strip()]

    numbering = _bullets("Numbering sequence:")
    xrefs = _bullets("Internal cross-references:")
    mm = re.search(r"Unresolved markers: (\d+)", out)
    ph = re.search(r"Placeholders \(TBD/XX/insert\): (\d+)", out)
    parts = [
        "numbering: " + ("; ".join(numbering) if numbering else "no gaps"),
        "cross-references: " + (f"{len(xrefs)} unresolved" if xrefs else "all resolve"),
        f"gap markers left: {mm.group(1) if mm else '?'}",
        f"placeholders left: {ph.group(1) if ph else '?'}",
    ]
    return "Delivery check — " + "; ".join(parts) + ".", None


def _run_loop_chunk(session_dir):
    """Advance the drafting loop until a pause is needed or it finishes.

    The loop is a state machine in st.session_state.loop_step, so it
    can stop after a cold read, ask the human, and resume on the
    next press. Steps: start (draft v1, HFE, draft v2) -> cold1 ->
    pause1 -> cold2 -> pause2 -> finish (final draft + delivery
    check) -> done. A pause only happens when there is something
    to ask: the drafting correction runs first, and the pause
    decision looks at what drafting could not resolve. When there
    is nothing to ask, the stage is marked done ("nothing to
    ask") and the loop moves on without stopping.
    Returns "" when it stopped at a pause or finished, or an
    error message. The caller shows the error and stops."""
    model = _secret("MODEL_DRAFTING") or "openai/gpt-6-luna"
    model_hfe = _secret("MODEL_HFE") or model
    model_cold = _secret("MODEL_COLD_READ") or model
    packet_md = _packet_text(session_dir)
    drafting_prompt = _secret("DRAFTING_SYSTEM_PROMPT")
    if not drafting_prompt:
        return "DRAFTING_SYSTEM_PROMPT is not in Streamlit Secrets. Add the polished instructions in Settings → Secrets."
    _od = _prompt_outdated("DRAFTING_SYSTEM_PROMPT", drafting_prompt)
    if _od:
        return _od
    while True:
        step = st.session_state.get("loop_step", "idle")
        if step == "start":
            # drafting 1 -> draft v1, written by the drafting
            # model (v29, test-049). One retry on failure — model
            # failures are often transient. There is NO skeleton
            # fallback: after seeing what the Python-assembled
            # draft makes, Manuel rejected it outright (v30,
            # test-050). If the model cannot write the first
            # draft, the run stops here with a clear message
            # instead of producing that draft.
            st.session_state.stage_status["drafting-1"] = "running"
            ok, draft_v1 = _draft_first(session_dir, packet_md, model, drafting_prompt)
            if not ok:
                ok, draft_v1 = _draft_first(session_dir, packet_md, model, drafting_prompt)
            if not ok:
                st.session_state.stage_status["drafting-1"] = "failed"
                return (f"The drafting model could not write the first draft "
                        f"({draft_v1}). Nothing was drafted — run the loop again.")
            with open(os.path.join(session_dir, "draft_v1.md"), "w") as f:
                f.write(draft_v1)
            with open(os.path.join(session_dir, "draft_v1.txt"), "w") as f:
                f.write(draft_v1)
            st.session_state.setdefault("loop_detail", {})["drafting-1"] = "Draft v1 ready (Discussion Draft) — written by the drafting model."
            st.session_state.stage_status["drafting-1"] = "done"
            # human-factors
            st.session_state.stage_status["human-factors"] = "running"
            hfe_prompt = _secret("HFE_SYSTEM_PROMPT")
            if not hfe_prompt:
                st.session_state.stage_status["human-factors"] = "failed"
                return "HFE_SYSTEM_PROMPT is not in Streamlit Secrets. Add the polished instructions in Settings → Secrets."
            _od = _prompt_outdated("HFE_SYSTEM_PROMPT", hfe_prompt)
            if _od:
                st.session_state.stage_status["human-factors"] = "failed"
                return _od
            user = f"DRAFT v1:\n{_draft_text(session_dir, 'draft_v1.md')}\n\nSOURCE PACKET:\n{packet_md}"
            ok, content, usage = _model_call(session_dir, "hfe", hfe_prompt, user, model_hfe)
            if not ok:
                st.session_state.stage_status["human-factors"] = "failed"
                return f"HFE failed: {content}"
            try:
                hfe_findings = json.loads(_strip_fence(content))
            except json.JSONDecodeError:
                st.session_state.stage_status["human-factors"] = "failed"
                return "HFE did not return JSON findings."
            with open(os.path.join(session_dir, "hfe_findings.json"), "w") as f:
                json.dump(hfe_findings, f, indent=2)
            _n_hfe = len(hfe_findings.get("findings", [])) if isinstance(hfe_findings, dict) else len(hfe_findings)
            st.session_state.stage_status["human-factors"] = "done"
            st.session_state.setdefault("loop_detail", {})["human-factors"] = f"{_n_hfe} finding(s)."
            # drafting 2 -> draft v2 (HFE fixes)
            st.session_state.stage_status["drafting-2"] = "running"
            _middle = f"FINDINGS:\n{json.dumps(hfe_findings, indent=2)}"
            _steps = _uncovered_steps_text(session_dir)
            if _steps:
                _middle = _steps + "\n" + _middle
            ok, draft_v2 = _revise(session_dir, packet_md, model, drafting_prompt,
                                   "draft_v1.md", _middle, "v1",
                                   restore_fills=True)
            if not ok:
                st.session_state.stage_status["drafting-2"] = "failed"
                return f"Drafting revision failed: {draft_v2}"
            with open(os.path.join(session_dir, "draft_v2.md"), "w") as f:
                f.write(draft_v2)
            with open(os.path.join(session_dir, "draft_v2.txt"), "w") as f:
                f.write(draft_v2)
            st.session_state.stage_status["drafting-2"] = "done"
            st.session_state.setdefault("loop_detail", {})["drafting-2"] = "Draft v2 ready (Discussion Draft)."
            st.session_state.loop_current = "draft_v2.md"
            st.session_state.loop_step = "cold1"
        elif step in ("cold1", "cold2"):
            # cold read, with dedup + drafting corrections after.
            # The audit sees draft + packet only — no HFE reasoning,
            # no drafting history. That coldness is enforced by the
            # inputs. Dedup runs here in code but is not a displayed
            # stage: it is a back-end step that makes the loop work.
            round_no = 1 if step == "cold1" else 2
            _cold_key = f"cold-read-{round_no}"
            _draft_key = "drafting-3" if round_no == 1 else "drafting-5"
            current = st.session_state.get("loop_current", "draft_v2.md")
            cold_prompt = _secret("COLD_READ_SYSTEM_PROMPT")
            if not cold_prompt:
                st.session_state.stage_status[_cold_key] = "failed"
                return "COLD_READ_SYSTEM_PROMPT is not in Streamlit Secrets."
            _od = _prompt_outdated("COLD_READ_SYSTEM_PROMPT", cold_prompt)
            if _od:
                st.session_state.stage_status[_cold_key] = "failed"
                return _od
            st.session_state.stage_status[_cold_key] = "running"
            user = (f"DRAFT (cold read input only - draft + packet, no HFE, no drafting history):\n"
                    f"{_draft_text(session_dir, current)}\n\nSOURCE PACKET:\n{packet_md}")
            ok, content, usage = _model_call(session_dir, "cold-read", cold_prompt, user, model_cold)
            if not ok:
                st.session_state.stage_status[_cold_key] = "failed"
                return f"Cold read failed: {content}"
            try:
                cold_findings = json.loads(_strip_fence(content))
            except json.JSONDecodeError:
                st.session_state.stage_status[_cold_key] = "failed"
                return "Cold read did not return JSON findings."
            with open(os.path.join(session_dir, f"cold_read_findings_{round_no}.json"), "w") as f:
                json.dump(cold_findings, f, indent=2)
            # dedup (code): drop findings that only restate a flagged gap.
            code, out = run(["python3", "agents/audit-agent/scripts/dedup.py",
                             "--draft", os.path.join(session_dir, current),
                             "--findings", os.path.join(session_dir, f"cold_read_findings_{round_no}.json"),
                             "--out", os.path.join(session_dir, f"cold_read_filtered_{round_no}.json")])
            if code != 0:
                st.session_state.stage_status[_cold_key] = "failed"
                return f"Dedup failed: {out.strip()[:300]}"
            filtered = json.load(open(os.path.join(session_dir, f"cold_read_filtered_{round_no}.json")))
            kept = filtered.get("findings", [])
            _n_raw = len(cold_findings.get("findings", [])) if isinstance(cold_findings, dict) else len(cold_findings)
            st.session_state.stage_status[_cold_key] = "done"
            st.session_state.setdefault("loop_detail", {})[_cold_key] = f"{_n_raw} finding(s), {len(kept)} kept after dedup."
            if kept:
                # drafting corrections -> next draft version
                st.session_state.stage_status[_draft_key] = "running"
                label = current.replace("draft_", "").replace(".md", "")
                ok, new_draft = _revise(session_dir, packet_md, model, drafting_prompt,
                                        current, f"FINDINGS:\n{json.dumps(kept, indent=2)}", label,
                                        restore_fills=True)
                if not ok:
                    st.session_state.stage_status[_draft_key] = "failed"
                    return f"Drafting corrections failed: {new_draft}"
                nxt = "draft_v3.md" if round_no == 1 else "draft_final.md"
                with open(os.path.join(session_dir, nxt), "w") as f:
                    f.write(new_draft)
                with open(os.path.join(session_dir, nxt.replace(".md", ".txt")), "w") as f:
                    f.write(new_draft)
                current = nxt
                st.session_state.loop_current = current
                st.session_state.stage_status[_draft_key] = "done"
                st.session_state.setdefault("loop_detail", {})[_draft_key] = (
                    "Draft v3 ready (Discussion Draft)." if round_no == 1
                    else "Final draft ready (Discussion Draft).")
            else:
                # Nothing new to fix; the current draft stands.
                st.session_state.stage_status[_draft_key] = "done"
                st.session_state.setdefault("loop_detail", {})[_draft_key] = "Nothing to fix — the cold read found nothing new."
            st.session_state.loop_step = "pause1" if round_no == 1 else "pause2"
        elif step in ("pause1", "pause2"):
            stage_name = "human-input-1" if step == "pause1" else "human-input-2"
            # The drafting step after this pause runs only when the
            # human answers something. With nothing to ask, there
            # is nothing to apply either — mark it done so it does
            # not sit at "waiting" forever.
            _after_key = "drafting-4" if step == "pause1" else "drafting-6"
            qs = _pause_questions(session_dir, st.session_state.get("loop_current", "draft_v2.md"))
            if not qs:
                # Nothing to ask: the drafting agent resolved
                # everything the cold read found. Account for it
                # and move on — no pause.
                st.session_state.stage_status[stage_name] = "done"
                st.session_state.setdefault("loop_detail", {})[stage_name] = "Nothing to ask — the drafting agent resolved everything."
                st.session_state.stage_status[_after_key] = "done"
                st.session_state.setdefault("loop_detail", {})[_after_key] = "No answers to apply — nothing to ask."
                st.session_state.loop_step = "cold2" if step == "pause1" else "finish"
                continue
            st.session_state.stage_status[stage_name] = "needs-you"
            st.session_state.setdefault("loop_detail", {})[stage_name] = f"{len(qs)} question(s) for the human."
            st.session_state.pause_questions = qs
            st.session_state.pause_shown = list(set(st.session_state.get("pause_shown", [])) | set(qs))
            return ""  # STOP — the pause UI renders
        elif step == "finish":
            # final draft: the current draft after both cold-read rounds.
            current = st.session_state.get("loop_current", "draft_v2.md")
            if current != "draft_final.md":
                import shutil
                shutil.copy(os.path.join(session_dir, current),
                            os.path.join(session_dir, "draft_final.md"))
                shutil.copy(os.path.join(session_dir, current.replace(".md", ".txt")),
                            os.path.join(session_dir, "draft_final.txt"))
            # audit-output: deterministic delivery checks (docsrc
            # check). The results are surfaced in the stage detail
            # (finding 2) — facts for the human, non-blocking.
            st.session_state.stage_status["audit-output"] = "running"
            _summary, _err = _docsrc_check_summary(session_dir, "draft_final.txt")
            if _err:
                st.session_state.stage_status["audit-output"] = "failed"
                return _err
            st.session_state.stage_status["audit-output"] = "done"
            st.session_state.setdefault("loop_detail", {})["audit-output"] = _summary
            st.session_state.stage_status["packet-builder"] = "done"
            st.session_state.loop_step = "done"
            return ""
        else:
            # idle, done, failed, or unknown — nothing to run.
            return ""


def stage_box(number, label, role, desc, status, detail=""):
    icon = {"waiting": "⏳", "running": "▶️", "done": "✅", "needs-you": "✋", "failed": "❌"}.get(status, "⏳")
    st.markdown(f"**{number}. {icon} {label}** — {role} — {status}")
    st.caption(desc)
    if detail:
        st.caption(detail)


def main():
    st.title("The Procedure Machine")
    # No public version caption (removed Nov 12, 2026): the app is
    # pre-release, more like 0.15 than 15, and a "Version N" label
    # overstates it. The live check is the Pipeline view instead —
    # the stages it shows are the deployed build's fingerprint
    # (v15: the two Human input stages).
    st.write("A public multi-agent demo: intake, drafting, HFE review, "
             "and cold-read audit — SOPs and Test Methods. Python owns what must be "
             "true; the LLM owns what should feel human.")
    secret_names = ["OPENROUTER_API_KEY", "MODEL_HFE", "MODEL_DRAFTING", "MODEL_COLD_READ",
                    "MODEL_COMPACTION", "MODEL_LOOKUP", "MODEL_PACKET_CHECK", "MODEL_EXTRACTION",
                    "HFE_SYSTEM_PROMPT", "DRAFTING_SYSTEM_PROMPT", "COLD_READ_SYSTEM_PROMPT"]
    _seen = [n for n in secret_names if _secret(n)]
    _missing = [n for n in secret_names if n not in _seen]
    # The "Secrets this app can see" caption used to be shown here.
    # It was a diagnostic from the Nov 11, 2026 secrets debugging
    # (the "all 7 secrets missing" bug) and it served its purpose;
    # it does not belong in the UI. Only the missing-key warning
    # below is kept.
    if "OPENROUTER_API_KEY" in _missing:
        st.warning("No OpenRouter key visible to the app. Check the spelling in Settings → Secrets, and reboot the app (⋮ → Reboot app) — Streamlit Cloud only picks up new secrets on reboot.")
    if "stage_status" not in st.session_state:
        st.session_state.stage_status = {key: "waiting" for key, _, _, _ in STAGES}
    # A session started before a version added stages lacks those
    # keys; the pipeline view reads them all, so fill any gap.
    for _key, _, _, _ in STAGES:
        st.session_state.stage_status.setdefault(_key, "waiting")
    if "session_id" not in st.session_state:
        st.session_state.session_id = "demo-" + uuid.uuid4().hex[:8]

    # --- Step 0: purpose + scope, with confirm gate
    # Intake starts with "describe what you want." The description
    # comes first; the kind of document and the template are read
    # out of it by the extraction call at Build time. Both pickers
    # default to Auto and are only there to override a wrong pick.
    st.header("1. Purpose and scope")
    st.write("Start by describing what you want, in plain words — what it should do, what it covers, what it does not cover, and who it is for. The machine reads the kind of document and the template out of that, and shows you what it picked below. Change the pickers only if it picks wrong.")
    description = st.text_area(
        "Describe what you want",
        "An SOP for cleaning the commercial espresso machine at closing time, so the first shot tomorrow tastes right. It covers the countertop machine and grinder at the café. It does not cover plumbing, descaling, or the dishwasher. It is for the staff member closing the shop.",
        height=120)
    doc_type = st.radio("Document type", ["Auto (from your description)", "SOP", "Test Method"], index=0,
                        help="Auto is the default: the machine reads the kind out of your description. Pick SOP or Test Method only to override it. Demo scope is SOPs and Test Methods. Other types are flagged, not built.")
    doc_label = "SOP" if doc_type != "Test Method" else "test method"
    template_id = st.selectbox("Template", ["Auto (from your description)", "sop-default", "equipment-sop", "test-method-default", "custom — describe it"],
                               index=0,
                               help="Auto is the default: the machine reads your description and picks the template — plain SOP, equipment SOP, or Test Method. Pick one yourself only to override it. custom: describe the template in plain words and the machine builds it.")
    if template_id == "custom — describe it":
        st.write("Describe the template in plain words. Only what you describe gets added — a required section with no packet content becomes a question to you, so keep it to what you actually need.")
        desc = st.text_input("Template description", f"a {doc_label} with subsections under Procedure for setup, daily use, and shutdown")
        if st.button("Build template from description"):
            try:
                key = st.secrets["OPENROUTER_API_KEY"]
            except Exception:
                st.error("No OpenRouter key in Streamlit Secrets yet. Add OPENROUTER_API_KEY in Settings → Secrets.")
                key = None
            if key:
                session_dir = os.path.join(SESSIONS, st.session_state.session_id)
                os.makedirs(session_dir, exist_ok=True)
                r = subprocess.run([sys.executable,
                                    os.path.join(BASE, "templates", "build_template.py"),
                                    "--mode", "env", "--description", desc,
                                    "--model", _secret("MODEL_DRAFTING") or "openai/gpt-6-luna",
                                    "--out", os.path.join(session_dir, "custom-template.json")],
                                   cwd=BASE, capture_output=True, text=True, timeout=180,
                                   env=dict(os.environ, OPENROUTER_API_KEY=key))
                if r.returncode == 0:
                    st.session_state.template_id = "custom-template.json"
                    st.success("Template built. Sections:")
                    st.code(r.stdout)
                else:
                    st.error(f"Could not build the template: {(r.stdout + r.stderr).strip()[:300]}")
    if template_id in _TEMPLATES:
        with st.expander("Alter this template"):
            st.write("Edit the section list below, then save. The template drives the draft: every required section is either filled from the packet or marked as a gap, never invented.")
            tpl_path = os.path.join(BASE, "templates", template_id + ".json")
            with open(tpl_path) as _f:
                tpl_text = _f.read()
            edited = st.text_area("Template JSON", tpl_text, height=220, key="template-editor")
            if st.button("Save altered template"):
                try:
                    altered = json.loads(edited)
                    altered["template_id"] = "custom-template.json"
                    session_dir = os.path.join(SESSIONS, st.session_state.session_id)
                    os.makedirs(session_dir, exist_ok=True)
                    with open(os.path.join(session_dir, "custom-template.json"), "w") as _f:
                        json.dump(altered, _f, indent=2)
                    st.session_state.template_id = "custom-template.json"
                    st.success("Altered template saved for this session.")
                except json.JSONDecodeError as e:
                    st.error(f"Not valid JSON: {e}")
    links = st.text_area("Source links (one per line, public only)",
                         "https://example.com")
    uploads = st.file_uploader("Or upload source files (stored in this session on the server, kept until you clear or reset the session)",
                               accept_multiple_files=True)

    # Stored sources from an earlier use (test-041, Nov 12, 2026):
    # source files stay in the session folder after a build, so a
    # second document tried in the same session silently joins the
    # first one in the next packet. Show what is already here, and
    # offer a way to clear it, before the user builds again.
    _session_dir = os.path.join(SESSIONS, st.session_state.session_id)
    _stored = _stored_sources(_session_dir)
    if _stored:
        st.write("Already in this session: " + ", ".join(_stored) +
                 ". A new build includes these unless you clear them.")
        if st.session_state.get("confirm_clear"):
            st.write("This deletes " + str(len(_stored)) + " source file(s) (" +
                     ", ".join(_stored) + ") and the packet and drafts from this session. "
                     "The files are yours — you would need to upload or fetch them again.")
            _yes, _no = st.columns(2)
            with _yes:
                if st.button("Yes, clear them"):
                    _deleted = _clear_session_files(_session_dir)
                    _clear_derived(_session_dir)
                    for _k in ("loop_step", "loop_current", "pause_shown",
                               "pause_questions", "loop_detail", "loop_result",
                               "pause_result", "download_unlocked", "packet_check",
                               "extracted", "purpose_scope", "template_pick",
                               "save_result", "ps-purpose", "ps-scope-in",
                               "ps-scope-out", "ps-user"):
                        st.session_state.pop(_k, None)
                    st.session_state.pop("confirm_clear", None)
                    st.session_state.clear_result = (
                        f"Cleared {len(_deleted)} source file(s). This session is empty — "
                        "upload or fetch a source to start a new build.")
                    st.rerun()
            with _no:
                if st.button("Cancel"):
                    st.session_state.pop("confirm_clear", None)
                    st.rerun()
        elif st.button("Clear stored sources"):
            st.session_state.confirm_clear = True
            st.rerun()
    if st.session_state.get("clear_result"):
        st.success(st.session_state.pop("clear_result"))

    # Complete reset (test-060, Nov 13, 2026): the clear above
    # removes stored sources, but a user trying several documents
    # in one session needs everything gone — packet, drafts,
    # findings, purpose, all of it — so nothing from one document
    # can follow them into the next. Shown whenever the session
    # folder holds anything at all.
    _has_anything = (os.path.isdir(_session_dir)
                     and bool(os.listdir(_session_dir)))
    if _has_anything:
        if st.session_state.get("confirm_reset"):
            st.write("This deletes EVERYTHING in this session: the source "
                     "files, the packet, every draft, and all findings. "
                     "Nothing is kept. Your original files on your own "
                     "device are not touched.")
            _ryes, _rno = st.columns(2)
            with _ryes:
                if st.button("Yes, reset everything"):
                    _clear_derived(_session_dir)
                    _n_reset = _reset_session_files(_session_dir)
                    for _k in ("loop_step", "loop_current", "pause_shown",
                               "pause_questions", "loop_detail", "loop_result",
                               "pause_result", "download_unlocked", "packet_check",
                               "extracted", "purpose_scope", "template_pick",
                               "save_result", "ps-purpose", "ps-scope-in",
                               "ps-scope-out", "ps-user", "confirm_clear"):
                        st.session_state.pop(_k, None)
                    st.session_state.pop("confirm_reset", None)
                    st.session_state.clear_result = (
                        f"Reset complete — {_n_reset} file(s) deleted. This "
                        "session is empty: describe a document and add a "
                        "source to start fresh.")
                    st.rerun()
            with _rno:
                if st.button("Cancel reset"):
                    st.session_state.pop("confirm_reset", None)
                    st.rerun()
        elif st.button("Reset everything (clear this session)"):
            st.session_state.confirm_reset = True
            st.rerun()

    # Rebuild guard (Nov 13, 2026): building again discards the
    # current run's drafts and pause answers — silently, before this
    # guard, and a stray second press paid for a whole rebuild.
    # When a run exists, the first press only arms a confirm and no
    # model call is made; the rebuild happens on the explicit Yes.
    # Mirrors the clear/reset two-step confirms above.
    if st.session_state.get("confirm_rebuild"):
        st.write("A build already exists in this session. Building "
                 "again discards its drafts and any pause answers "
                 "and starts over. Your sources stay — only the "
                 "run's work is discarded.")
        _byes, _bno = st.columns(2)
        with _byes:
            if st.button("Yes, rebuild and start over"):
                st.session_state.rebuild_go = True
                st.session_state.pop("confirm_rebuild", None)
                st.rerun()
        with _bno:
            if st.button("Cancel rebuild"):
                st.session_state.pop("confirm_rebuild", None)
                st.rerun()
    _build_pressed = st.button("Build the packet")
    _build_go = st.session_state.pop("rebuild_go", False)
    if _build_pressed or _build_go:
        if _build_pressed and not _build_go and _run_exists(_session_dir):
            st.session_state.confirm_rebuild = True
            st.rerun()
        if not description.strip():
            st.error("Describe the document first — one or two sentences is enough.")
            st.stop()
        session_dir = os.path.join(SESSIONS, st.session_state.session_id)
        os.makedirs(session_dir, exist_ok=True)
        # A new build starts clean: delete the previous run's packet,
        # drafts, and findings, so a failed build can never leave a
        # stale packet behind for drafting to pick up.
        _clear_derived(session_dir)
        # A new build re-locks the downloads: the previous run's
        # "download as it stands" choice does not carry over.
        st.session_state.pop("download_unlocked", None)
        # And resets the loop state machine: a new build starts
        # the loop from the beginning, with no pause left over.
        for _k in ("loop_step", "loop_current", "pause_shown",
                   "pause_questions", "loop_detail", "loop_result",
                   "pause_result"):
            st.session_state.pop(_k, None)
        with st.spinner("Reading your description…"):
            extracted, read_ok = _extract_purpose_scope(session_dir, description)
        # The description drives the kind: when the pickers are on
        # Auto, the extraction call says what document this is and
        # which template fits. An explicit user choice wins; a
        # user-built custom template (from "Build template" or
        # "Alter") wins over both.
        pick_reason = ""
        if st.session_state.get("template_id") == "custom-template.json":
            template_resolved = "custom-template.json"
        elif template_id == "custom — describe it":
            template_resolved = "sop-default"
        else:
            template_resolved, pick_reason, custom_desc = _pick_template(template_id, extracted)
            if template_resolved == "custom":
                if custom_desc:
                    # The machine described the template it needs;
                    # build it the same way the manual custom flow
                    # does, then use it for this run.
                    try:
                        key = st.secrets["OPENROUTER_API_KEY"]
                    except Exception:
                        key = None
                    if key:
                        r = subprocess.run([sys.executable,
                                            os.path.join(BASE, "templates", "build_template.py"),
                                            "--mode", "env", "--description", custom_desc,
                                            "--model", _secret("MODEL_DRAFTING") or "openai/gpt-6-luna",
                                            "--out", os.path.join(session_dir, "custom-template.json")],
                                           cwd=BASE, capture_output=True, text=True, timeout=180,
                                           env=dict(os.environ, OPENROUTER_API_KEY=key))
                        if r.returncode == 0:
                            template_resolved = "custom-template.json"
                            st.session_state.template_id = "custom-template.json"
                        else:
                            st.warning("The machine asked for a custom template but it could not be built — falling back to the plain SOP template.")
                            template_resolved = "sop-default"
                    else:
                        template_resolved = "sop-default"
                else:
                    template_resolved = "sop-default"
        doc_type_resolved = (extracted.get("document_type") if doc_type == "Auto (from your description)"
                             else doc_type)
        if doc_type_resolved not in ("SOP", "Test Method"):
            doc_type_resolved = "SOP"
        purpose_scope = {"document_type": doc_type_resolved, "purpose": extracted["purpose"],
                         "scope_in": extracted["scope_in"], "scope_out": extracted["scope_out"],
                         "intended_user": extracted["intended_user"],
                         "authority_route": "Unsupported",
                         "work_mode": "Draft/Format",
                         "template": template_resolved}
        with open(os.path.join(session_dir, "purpose_scope.json"), "w") as f:
            json.dump(purpose_scope, f, indent=2)
        st.session_state.purpose_scope = purpose_scope
        st.session_state.extracted = extracted
        # What the machine picked, and why — shown with the read-back
        # below, so the pick is visible and checkable, not silent.
        if pick_reason:
            st.session_state.template_pick = f"Picked the {template_resolved} template — {pick_reason}"
        else:
            st.session_state.pop("template_pick", None)
        for k in ("ps-purpose", "ps-scope-in", "ps-scope-out", "ps-user"):
            st.session_state.pop(k, None)
        for up in uploads:
            with open(os.path.join(session_dir, up.name), "wb") as f:
                f.write(up.getbuffer())
        st.session_state.stage_status["purpose-scope"] = "done"
        if not read_ok:
            st.warning("No key to read your description with — the packet is built from the description as written. Fix the fields below by hand and save, and the packet rebuilds.")
        # Intake runs in the same press now (merged Nov 11, 2026 — the
        # separate "Proceed to intake" button was a second press for
        # one step). Fetch the links, read the sources, build the packet.
        st.session_state.stage_status["fetch-link"] = "running"
        urls = [u.strip() for u in links.splitlines() if u.strip()]
        # The links box is prefilled with https://example.com as a
        # format example. Those are reserved placeholder domains
        # with no real content — if one is left in the box it gets
        # fetched and treated as a real source, and its junk text
        # can keyword-match into the packet (and "fetched.txt" into
        # the Records list). Skip them, and say so.
        _EXAMPLE_HOSTS = {"example.com", "example.org", "example.net", "example.edu"}
        _skipped = [u for u in urls
                    if (urlparse(u).hostname or "").lower().rstrip(".") in _EXAMPLE_HOSTS]
        urls = [u for u in urls if u not in _skipped]
        if _skipped:
            st.info("Skipped example.com — it is a placeholder link, not a source document.")
        failed = None
        for url in urls:
            code, out = run(["python3", "skills/fetch-link/scripts/fetch.py",
                             url, "--session", st.session_state.session_id])
            if code != 0:
                failed = f"Fetch blocked: {url} — {out.strip()[:200]}"
                break
        if failed:
            st.session_state.stage_status["fetch-link"] = "failed"
            st.error(failed)
            st.stop()
        st.session_state.stage_status["fetch-link"] = "done"
        st.session_state.stage_status["source-intake"] = "running"
        # One source filter for the whole app (test-042): the intake
        # used to duplicate _stored_sources' filter, and the two
        # drifted — the intake read model-call records as sources.
        # _stored_sources is the single definition now.
        srcs = _stored_sources(session_dir)
        if not srcs:
            st.session_state.stage_status["source-intake"] = "failed"
            st.error("No source files to read. Paste a link or upload a file first.")
            st.stop()
        code, out = run(["python3", os.path.join(BASE, "skills/source-intake/scripts/docsrc.py"),
                         "intake"] + srcs, cwd=session_dir)
        if code != 0:
            st.session_state.stage_status["source-intake"] = "failed"
            st.error(f"Source intake failed: {out.strip()[:300]}")
            st.stop()
        # Read-record gate (test-025): docsrc can exit 0 with every
        # source UNREADABLE, and the app used to build an empty
        # packet from that without a word. A needed source that is
        # UNREADABLE stops here, in plain words, before any packet
        # is built. One OK or PARTIAL source is enough to proceed.
        _cache = {}
        try:
            _cache = json.load(open(os.path.join(session_dir, "docsrc_cache.json")))
        except (OSError, json.JSONDecodeError):
            _cache = {}
        _usable = [n for n, r in _cache.get("files", {}).items()
                   if isinstance(r, dict) and r.get("status") in ("OK", "PARTIAL")]
        if not _usable:
            st.session_state.stage_status["source-intake"] = "failed"
            st.error("The source could not be read — the file came back unreadable, so there is nothing to build from. Try uploading the file instead of a link, or a .docx, a text-based PDF, or pasted text.")
            st.stop()
        st.session_state.stage_status["source-intake"] = "done"
        st.session_state.stage_status["packet-builder"] = "running"
        with st.spinner("Building the packet from your sources…"):
            code, out = run(["python3", "skills/packet-builder/scripts/packet.py",
                             "build", "--session", st.session_state.session_id,
                             "--template", template_resolved])
        if code != 0:
            # Over cap is recoverable: packet.py wrote the packet
            # flagged over_cap, and the relevance step trims it
            # (one model call per section, template-matched sections
            # never dropped). Any other failure stops here.
            _pkt_path = os.path.join(session_dir, "source_packet.json")
            _over = False
            if os.path.exists(_pkt_path):
                try:
                    _over = bool(json.load(open(_pkt_path)).get("over_cap"))
                except (json.JSONDecodeError, OSError):
                    _over = False
            if not _over:
                st.session_state.stage_status["packet-builder"] = "failed"
                st.error(f"Packet build failed: {out.strip()[:300]}")
                st.stop()
            key = _secret("OPENROUTER_API_KEY")
            if not key:
                st.session_state.stage_status["packet-builder"] = "failed"
                st.error("The packet is over the size cap and there is no OpenRouter key in Secrets, so the relevance step that would trim it cannot run. Narrow the scope or drop a source.")
                st.stop()
            st.info("The packet is over the size cap, so the machine is trimming it to the sections that matter for this document. This takes a few model calls.")
            with st.spinner("Trimming the packet — scoring each section against your description. On a large manual this is the slow step…"):
                code, out = run(["python3", "skills/packet-builder/scripts/relevance.py",
                                 "--session", st.session_state.session_id,
                                 "--mode", "env",
                                 "--model", _secret("MODEL_DRAFTING") or "openai/gpt-6-luna"],
                                env={"OPENROUTER_API_KEY": key}, timeout=1200)
            if code != 0:
                # A failed relevance pass stops the build (finding
                # 3): relevance is the judgment that decides what
                # the drafter sees, and proceeding on an unjudged
                # packet while printing "Packet trimmed" hid its
                # failures exactly when the documents were biggest.
                st.session_state.stage_status["packet-builder"] = "failed"
                st.error(f"Relevance trimming failed: {out.strip()[:300]}")
                st.stop()
            _pkt = json.load(open(_pkt_path)) if os.path.exists(_pkt_path) else {}
            if not _pkt:
                st.session_state.stage_status["packet-builder"] = "failed"
                st.error(f"Relevance trimming failed: {out.strip()[:300]}")
                st.stop()
            if _pkt.get("over_cap"):
                # Relevance judges whole sections; a big guideline
                # can still be over cap because the kept sections
                # themselves are huge. Compaction condenses those.
                st.info("Still over the size cap after relevance — condensing the largest sections now.")
                with st.spinner("Condensing the largest sections…"):
                    code, out = run(["python3", "skills/packet-builder/scripts/compact.py",
                                     "--session", st.session_state.session_id,
                                     "--mode", "env",
                                     "--model", _secret("MODEL_COMPACTION") or "openai/gpt-6-luna"],
                                    env={"OPENROUTER_API_KEY": key}, timeout=1200)
                if code != 0:
                    # A compaction crash is a crash, not "still over
                    # cap" (finding 3).
                    st.session_state.stage_status["packet-builder"] = "failed"
                    st.error(f"Compaction failed: {out.strip()[:300]}")
                    st.stop()
                _pkt = json.load(open(_pkt_path)) if os.path.exists(_pkt_path) else {}
                if not _pkt:
                    st.session_state.stage_status["packet-builder"] = "failed"
                    st.error(f"Compaction failed: {out.strip()[:300]}")
                    st.stop()
            if _pkt.get("over_cap"):
                st.session_state.stage_status["packet-builder"] = "failed"
                st.error(f"Still over the size cap after relevance and compaction "
                         f"(~{_pkt.get('packet_tokens_estimate', '?')} tokens). Narrow the scope or drop a source.")
                st.stop()
            st.success(f"Packet trimmed: {len(_pkt.get('relevant_sections', []))} sections kept, "
                       f"~{_pkt.get('packet_tokens_estimate', '?')} tokens.")
        # Packet check (v18): does the packet answer the purpose as
        # a whole? See _run_packet_check. A failed check does not
        # block the build — the packet is still usable, and the
        # gate shows the check did not run. The lookup (v26) runs
        # right after it: it obtains what the relevant guidance says
        # about each uncovered step and assesses whether that covers
        # the gap.
        with st.spinner("Checking the packet against your description…"):
            st.session_state.packet_check = _run_packet_check(session_dir)
            st.session_state.lookup = _run_lookup(session_dir)
        st.session_state.stage_status["packet-builder"] = "needs-you"
        st.success("Packet built. Check how the machine read your description below, fix anything it got wrong, then press “Proceed to drafting?” just below — that is the human gate.")
        _pkt = json.load(open(os.path.join(session_dir, "source_packet.json")))
        if not _pkt.get("relevant_sections"):
            st.warning("Your sources had nothing the packet could use — the draft will be all flagged gaps for you to answer in section 3. Add a richer source document (a manual, a guidance PDF) for a fuller draft.")
        st.rerun()
    if "extracted" in st.session_state:
        ex = st.session_state.extracted
        if st.session_state.get("template_pick"):
            st.info(st.session_state["template_pick"])
        st.write("Here's how the machine read your description. If anything is wrong, fix it — a save button appears when you change a field, and saving rebuilds the packet from the corrected values. If it's all right, you're done here; the packet is already built and drafting is ready.")
        st.text_input(f"Purpose of this {doc_label}", ex.get("purpose", ""), key="ps-purpose")
        st.text_input("What is in scope?", ex.get("scope_in", ""), key="ps-scope-in")
        st.text_input("What is outside the scope? (optional)", ex.get("scope_out", ""), key="ps-scope-out")
        st.text_input(f"Who is this {doc_label} for?", ex.get("intended_user", ""), key="ps-user")
        if st.session_state.get("save_result"):
            st.success(st.session_state.pop("save_result"))
        # The save button only exists when the user changed something.
        # Otherwise it looks like a required step in the flow, and it
        # is not: the packet is already built and drafting is ready
        # (reported Nov 11, 2026 — "Proceed to drafting was already
        # ready. What is 'Save purpose and scope' for?").
        changed = (
            st.session_state.get("ps-purpose", ex.get("purpose", "")) != ex.get("purpose", "")
            or st.session_state.get("ps-scope-in", ex.get("scope_in", "")) != ex.get("scope_in", "")
            or st.session_state.get("ps-scope-out", ex.get("scope_out", "")) != ex.get("scope_out", "")
            or st.session_state.get("ps-user", ex.get("intended_user", "")) != ex.get("intended_user", "")
        )
        _sess2 = os.path.join(SESSIONS, st.session_state.session_id)
        if st.session_state.get("confirm_save_rebuild"):
            st.write("Saving rebuilds the packet and discards the "
                     "current run's drafts and any pause answers. "
                     "Your sources and the corrected purpose and "
                     "scope are kept.")
            _syes, _sno = st.columns(2)
            with _syes:
                if st.button("Yes, save and rebuild"):
                    st.session_state.save_rebuild_go = True
                    st.session_state.pop("confirm_save_rebuild", None)
                    st.rerun()
            with _sno:
                if st.button("Cancel save"):
                    st.session_state.pop("confirm_save_rebuild", None)
                    st.rerun()
        _save_pressed = changed and st.button("Save my fixes and rebuild the packet")
        _save_go = st.session_state.pop("save_rebuild_go", False)
        if _save_pressed or _save_go:
            if _save_pressed and not _save_go and _run_exists(_sess2):
                st.session_state.confirm_save_rebuild = True
                st.rerun()
            ps = dict(st.session_state.get("purpose_scope", {}))
            ps["purpose"] = st.session_state.get("ps-purpose", "")
            ps["scope_in"] = st.session_state.get("ps-scope-in", "")
            ps["scope_out"] = st.session_state.get("ps-scope-out", "")
            ps["intended_user"] = st.session_state.get("ps-user", "")
            session_dir = os.path.join(SESSIONS, st.session_state.session_id)
            with open(os.path.join(session_dir, "purpose_scope.json"), "w") as f:
                json.dump(ps, f, indent=2)
            st.session_state.purpose_scope = ps
            st.session_state.extracted = {"purpose": ps["purpose"], "scope_in": ps["scope_in"],
                                          "scope_out": ps["scope_out"], "intended_user": ps["intended_user"]}
            # The packet is about to be replaced: clear the previous
            # run's derived state and loop state first (finding 6),
            # so drafts and pauses from the old packet cannot be
            # presented against the new one.
            _clear_derived(session_dir)
            for _k in ("loop_step", "loop_current", "pause_shown",
                       "pause_questions", "loop_detail", "loop_result",
                       "download_unlocked"):
                st.session_state.pop(_k, None)
            code, out = run(["python3", "skills/packet-builder/scripts/packet.py",
                             "build", "--session", st.session_state.session_id,
                             "--template", ps.get("template", "sop-default")])
            # The confirmation must survive the rerun below, or it
            # only flashes: st.rerun() wipes anything rendered on
            # this run (same bug as section 3, fixed in v7).
            if code != 0:
                st.session_state.save_result = f"Purpose and scope saved, but the packet rebuild failed: {out.strip()[:200]}"
            else:
                # A fix can make the packet bigger; the rebuild gets
                # the same over-cap trim path as a fresh Build
                # (finding 6) instead of failing on packet.py's
                # over-cap exit.
                _rpkt_path = os.path.join(session_dir, "source_packet.json")
                _rpkt = {}
                try:
                    _rpkt = json.load(open(_rpkt_path))
                except (OSError, json.JSONDecodeError):
                    _rpkt = {}
                _trim_err = None
                if _rpkt.get("over_cap"):
                    _key = _secret("OPENROUTER_API_KEY")
                    if not _key:
                        _trim_err = "the packet is over the size cap and there is no key to trim it with"
                    else:
                        with st.spinner("Trimming the packet — scoring each section against your description. On a large manual this is the slow step…"):
                            _tc, _to = run(["python3", "skills/packet-builder/scripts/relevance.py",
                                            "--session", st.session_state.session_id,
                                            "--mode", "env",
                                            "--model", _secret("MODEL_DRAFTING") or "openai/gpt-6-luna"],
                                           env={"OPENROUTER_API_KEY": _key}, timeout=1200)
                        if _tc != 0:
                            _trim_err = f"relevance trimming failed: {_to.strip()[:200]}"
                        else:
                            try:
                                _rpkt = json.load(open(_rpkt_path))
                            except (OSError, json.JSONDecodeError):
                                _rpkt = {}
                            if _rpkt.get("over_cap"):
                                with st.spinner("Condensing the largest sections…"):
                                    _tc, _to = run(["python3", "skills/packet-builder/scripts/compact.py",
                                                    "--session", st.session_state.session_id,
                                                    "--mode", "env",
                                                    "--model", _secret("MODEL_COMPACTION") or "openai/gpt-6-luna"],
                                                   env={"OPENROUTER_API_KEY": _key}, timeout=1200)
                                if _tc != 0:
                                    _trim_err = f"compaction failed: {_to.strip()[:200]}"
                                else:
                                    try:
                                        _rpkt = json.load(open(_rpkt_path))
                                    except (OSError, json.JSONDecodeError):
                                        _rpkt = {}
                            if _rpkt.get("over_cap"):
                                _trim_err = (f"the packet is still over the size cap "
                                             f"(~{_rpkt.get('packet_tokens_estimate', '?')} tokens)")
                if _trim_err:
                    st.session_state.save_result = (f"Purpose and scope saved, and the packet rebuilt, but "
                                                    f"{_trim_err}. Narrow the scope or drop a source, then save again.")
                else:
                    # The packet changed, so the check re-runs too,
                    # and the lookup with it (the uncovered steps
                    # may have changed).
                    with st.spinner("Checking the packet against your description…"):
                        st.session_state.packet_check = _run_packet_check(session_dir)
                        st.session_state.lookup = _run_lookup(session_dir)
                    st.session_state.save_result = "Saved, and the packet rebuilt from the corrected values."
            st.rerun()
    # The drafting button lives here in section 1, right where the
    # packet was built — not at the bottom of the Pipeline view
    # (moved Nov 11, 2026: the gate was too far from the work).
    # It only appears once a packet exists, so it is never a dead
    # button.
    _packet_path = os.path.join(SESSIONS, st.session_state.session_id, "source_packet.json")
    if os.path.exists(_packet_path):
        st.write("The packet is built. You can review it in section 2 below. This next step runs the loop — drafting, HFE, cold read twice — and it is the expensive one, so it waits for you.")
    # Packet check result at the human gate (v18): what the check
    # found, what it fetched, what is still missing. Read from
    # disk — session state does not survive a page reload.
    _check_path = os.path.join(SESSIONS, st.session_state.session_id, "packet_check.json")
    _check = None
    try:
        _check = json.load(open(_check_path))
    except (OSError, json.JSONDecodeError):
        _check = None
    if _check is not None:
        _fetched = _check.get("fetched", [])
        _covered = _check.get("covered", [])
        _missing = _check.get("still_missing", [])
        # "Nothing missing" is only true on a direct fit (test-048):
        # on a partial fit the fetchable-topics lists are empty too,
        # and printing it contradicted the partial-fit banner right
        # below it in the Cary 60 live run.
        if not _fetched and not _covered and not _missing \
                and _check.get("fit", "DIRECT_FIT") == "DIRECT_FIT":
            st.write("Packet check: nothing missing for this purpose.")
        elif _fetched or _covered or _missing:
            _parts = []
            if _fetched:
                _parts.append("fetched " + str(len(_fetched)) + " section(s) from your sources: " +
                              ", ".join(f.get("title", "?") for f in _fetched))
            if _covered:
                _parts.append(str(len(_covered)) + " topic(s) were already in the packet: " +
                              ", ".join(f.get("topic", "?") for f in _covered))
            if _missing:
                _parts.append("still missing: " +
                              ", ".join(f.get("topic", "?") for f in _missing))
            st.write("Packet check: " + "; ".join(_parts) + ".")
            if _missing:
                st.write("For the still-missing topics you can add a source, narrow the scope, or proceed and answer them yourself.")
    # Fit at the human gate (v24/v26): a partial fit is a non-blocking
    # banner (the source has the technical rules; the workflow steps
    # will be flagged inline), an unrelated fit halts drafting with
    # a "Proceed anyway" override. A check written before v24 has no
    # fit field and reads as DIRECT. The lookup (v26) is what the
    # user sees for a partial fit: what the agent obtained about each
    # uncovered step and whether it covers the gap — obtained, then
    # assessed, not a built-in explanation (v25, removed). Read from
    # disk — session state does not survive a page reload.
    _fit = (_check or {}).get("fit", "DIRECT_FIT")
    _steps = (_check or {}).get("uncovered_steps", []) if _check else []
    _lookup = None
    try:
        _lookup = json.load(open(os.path.join(SESSIONS, st.session_state.session_id, "lookup.json")))
    except (OSError, json.JSONDecodeError):
        _lookup = None
    if _fit == "UNRELATED_MISMATCH":
        _missing = (_check or {}).get("still_missing", [])
        _msg = "This source doesn't cover what you asked for. " + \
            ("Still missing: " + ", ".join(f.get("topic", "?") for f in _missing) + ". " if _missing else "") + \
            "The draft can't be built from it. Add a source that describes what you asked for, narrow the scope, or proceed anyway."
        st.error(_msg)
        _proceed = st.button("Proceed anyway")
    else:
        if _fit == "PARTIAL_REGULATORY_FIT":
            _lookups = (_lookup or {}).get("lookups", [])
            # The lookup block names each step, so the banner does not
            # repeat the list (v27: the double listing was half the
            # verbosity). The list stays as a fallback when no lookup
            # ran.
            _banner = "Source covers the technical / regulatory criteria; the site-specific workflow steps will be flagged inline for author input."
            if not _lookups and _steps:
                _banner += " Uncovered steps: " + ", ".join(_steps) + "."
            st.info(_banner)
            if _lookups:
                st.write("What I found about the uncovered steps (looked up, then assessed):")
                for _lk in _lookups:
                    _label = {"covers": "covers this step",
                              "framework_only": "covers the framework — the operational mechanics are still site-specific (your internal SOPs)",
                              "not_found": "no relevant guidance found",
                              "error": "lookup failed"}.get(_lk.get("assessment", "error"), "lookup failed")
                    # One compact line per step (v27). The assessment
                    # note is kept in lookup.json for the record but
                    # not shown — it restated the found text and the
                    # label, and that repetition was the other half
                    # of the verbosity.
                    _line = f"- {_lk.get('step', '?')}: {_lk.get('found', '')}"
                    if _lk.get("sources"):
                        _line += f" (Sources: {', '.join(_lk['sources'])}.)"
                    _line += f" Assessment: {_label}."
                    st.write(_line)
        _proceed = st.button("Proceed to drafting?")
    _loop_midflight = st.session_state.get("loop_step") in ("start", "cold1", "pause1", "cold2", "pause2", "finish")
    if os.path.exists(_packet_path) and not _loop_midflight and _proceed:
        session_dir = os.path.join(SESSIONS, st.session_state.session_id)
        if not os.path.exists(os.path.join(session_dir, "source_packet.json")):
            st.error("No packet yet. Run “Build the packet” first.")
            st.stop()
        # Start (or restart) the loop. The loop is a state machine
        # in loop_step: it runs until a pause is needed or it
        # finishes, and the pause UI below resumes it. The packet
        # stage is done the moment the user proceeds (test-048: it
        # stayed on "needs-you" through the whole loop because it
        # was only set to done at the very end, in the finish step).
        st.session_state.stage_status["packet-builder"] = "done"
        st.session_state.loop_step = "start"
        st.session_state.loop_current = "draft_v2.md"
        st.session_state.pause_shown = []
        st.session_state.pause_questions = []
        st.session_state.loop_detail = {}
        with st.spinner("Running the loop: drafting, HFE, drafting, cold read, drafting, cold read, final draft…"):
            err = _run_loop_chunk(session_dir)
        if err:
            st.session_state.loop_step = "failed"
            st.error(err)
            st.stop()
        if st.session_state.get("loop_step") == "done":
            st.session_state.loop_result = "Loop finished. Final draft below — a Discussion Draft, with any flagged gaps visible, not invented."
        st.rerun()
    if st.session_state.get("loop_result"):
        st.success(st.session_state.pop("loop_result"))
    if st.session_state.get("loop_step") in ("pause1", "pause2"):
        # Paused after a cold read: the drafting agent could not
        # resolve these, so only a human can answer them. The
        # second cold read audits whatever is answered here.
        _round_no = 1 if st.session_state.loop_step == "pause1" else 2
        _stage_name = "human-input-1" if _round_no == 1 else "human-input-2"
        st.header(f"Paused after cold read {_round_no}")
        st.write("The drafting agent could not resolve these — only a human can answer them. "
                 "Answer what you know and leave the rest blank; a blank answer stays flagged. "
                 "“I don't know” is a valid answer.")
        if st.session_state.get("pause_result"):
            st.success(st.session_state.pop("pause_result"))
        _answers = {}
        for _marker in st.session_state.get("pause_questions", []):
            _short = _marker if len(_marker) <= 140 else _marker[:137] + "…"
            _key = "pause-answer-" + hashlib.md5((_marker + f"|{_round_no}").encode("utf-8")).hexdigest()
            _answers[_marker] = st.text_area(_short, key=_key, height=68)
        _advance = False
        _given = {}
        # The drafting step after this pause (drafting-4 after
        # pause 1, drafting-6 after pause 2 — the final drafting).
        # It runs only when the human answered something; on Skip
        # there is nothing to apply.
        _after_key = "drafting-4" if _round_no == 1 else "drafting-6"
        if st.button("Apply my answers and continue"):
            _given = {m: a.strip() for m, a in _answers.items() if a.strip()}
            if _given:
                st.session_state.stage_status[_after_key] = "running"
                _ok, _remaining, _err = _apply_pause_answers(
                    os.path.join(SESSIONS, st.session_state.session_id),
                    st.session_state.get("loop_current", "draft_v2.md"), _given)
                if not _ok:
                    st.session_state.stage_status[_after_key] = "failed"
                    st.error(f"Could not apply the answers: {_err}")
                    st.stop()
                st.session_state.stage_status[_after_key] = "done"
                st.session_state.setdefault("loop_detail", {})[_after_key] = (
                    f"Answers applied. {_remaining} gap(s) still flagged in this draft."
                    if _remaining else "All flagged gaps answered.")
                st.session_state.pause_result = (
                    f"Answers applied. {_remaining} gap(s) still flagged in this draft."
                    if _remaining else "All flagged gaps answered.")
            else:
                st.session_state.stage_status[_after_key] = "done"
                st.session_state.setdefault("loop_detail", {})[_after_key] = "No answers to apply."
            _advance = True
        if st.button("Continue without answering"):
            st.session_state.stage_status[_after_key] = "done"
            st.session_state.setdefault("loop_detail", {})[_after_key] = "No answers to apply."
            _advance = True
        if _advance:
            st.session_state.stage_status[_stage_name] = "done"
            st.session_state.setdefault("loop_detail", {})[_stage_name] = (
                "Answered." if _given else "Skipped — continued without answers.")
            st.session_state.loop_step = "cold2" if _round_no == 1 else "finish"
            with st.spinner("Continuing the loop…"):
                err = _run_loop_chunk(os.path.join(SESSIONS, st.session_state.session_id))
            if err:
                st.session_state.loop_step = "failed"
                st.error(err)
                st.stop()
            if st.session_state.get("loop_step") == "done":
                st.session_state.loop_result = "Loop finished. Final draft below — a Discussion Draft, with any flagged gaps visible, not invented."
            st.rerun()

    # --- Pipeline view
    st.header("2. Pipeline")
    st.write("Status only — nothing to press here. What each agent is doing, what it took in, and what it "
             "produced. No model thoughts, no live drafting, no raw "
             "instructions are shown here.")
    session_dir = os.path.join(SESSIONS, st.session_state.session_id)
    for _num, (_key, _label, _role, _desc) in enumerate(STAGES, 1):
        detail = ""
        if _key == "fetch-link" and os.path.exists(os.path.join(session_dir, "fetch_record.json")):
            try:
                _recs = json.load(open(os.path.join(session_dir, "fetch_record.json")))
                detail = " | ".join(
                    f"{r.get('saved_as', r.get('url', '?')).split('/')[-1]}: "
                    f"{r.get('fetch_status', '?')}, {r.get('bytes', '?')} bytes, "
                    f"{r.get('content_type', '?')}" for r in _recs)
            except (OSError, json.JSONDecodeError):
                detail = ""
        if _key == "source-intake" and os.path.exists(os.path.join(session_dir, "docsrc_cache.json")):
            try:
                _cache = json.load(open(os.path.join(session_dir, "docsrc_cache.json")))
                detail = " | ".join(
                    f"{n}: {r.get('status', '?')}, {r.get('pages', '?')} pages, "
                    f"{r.get('chars', '?')} source chars, {len(r.get('anchors', []))} sections"
                    for n, r in _cache.get("files", {}).items()
                    if isinstance(r, dict))
            except (OSError, json.JSONDecodeError):
                detail = ""
        if _key == "packet-builder" and os.path.exists(os.path.join(session_dir, "source_packet.json")):
            p = json.load(open(os.path.join(session_dir, "source_packet.json")))
            detail = (f"Packet {p.get('packet_id')}: {len(p.get('required_sections', []))} required sections, "
                      f"{len(p.get('relevant_sections', []))} relevant, {len(p.get('gaps', []))} gaps, "
                      f"~{p.get('packet_tokens_estimate', '?')} tokens.")
            _cp = os.path.join(session_dir, "packet_check.json")
            if os.path.exists(_cp):
                try:
                    _c = json.load(open(_cp))
                    detail += (f" Packet check: {len(_c.get('fetched', []))} fetched, "
                               f"{len(_c.get('covered', []))} already covered, "
                               f"{len(_c.get('still_missing', []))} still missing.")
                except (OSError, json.JSONDecodeError):
                    pass
            _dups = p.get("duplicate_sources", [])
            if _dups:
                detail += (f" {len(_dups)} duplicate source(s) ignored "
                           f"(same document twice): " +
                           ", ".join(d.get("name", "?") for d in _dups) + ".")
        if _key in ("human-input-1", "human-input-2", "drafting-1", "drafting-2",
                    "drafting-3", "drafting-4", "drafting-5", "drafting-6",
                    "cold-read-1", "cold-read-2", "audit-output"):
            detail = st.session_state.get("loop_detail", {}).get(_key, "")
        stage_box(_num, _label, _role, _desc, st.session_state.stage_status[_key], detail)

    # --- Human input: answer the flagged gaps
    final_path = os.path.join(session_dir, "draft_final.md")
    if os.path.exists(final_path):
        final_text = _draft_text(session_dir, "draft_final.md")
        markers = _find_markers(final_text)
        if markers:
            st.header("3. Answer the flagged gaps")
            st.write("The draft has flagged gaps — things only a human can answer. "
                     "Answer what you know and leave the rest blank; a blank answer "
                     "stays flagged. “I don't know” is a valid answer.")
            if st.session_state.get("gap_result"):
                st.success(st.session_state.pop("gap_result"))
            answers = {}
            for marker in markers:
                short = marker if len(marker) <= 140 else marker[:137] + "…"
                # Key by the marker itself, never by position. Positional
                # keys (gap-answer-0, -1, …) made answered values stick
                # to the wrong boxes after the list shrank: on the
                # rerun, the remaining boxes inherited the old values
                # by key (found live Nov 11, 2026 — the Responsibilities
                # answer showed under Records). A marker's key dies
                # with the marker; the remaining boxes keep their own.
                key = "gap-answer-" + hashlib.md5(marker.encode("utf-8")).hexdigest()
                answers[marker] = st.text_area(short, key=key, height=68)
            if st.button("Apply my answers"):
                given = {m: a.strip() for m, a in answers.items() if a.strip()}
                if not given:
                    st.warning("No answers given — the markers stay as they are.")
                    st.stop()
                packet_md = _packet_text(session_dir)
                model = _secret("MODEL_DRAFTING") or "openai/gpt-6-luna"
                drafting_prompt = _secret("DRAFTING_SYSTEM_PROMPT")
                if not drafting_prompt:
                    st.error("DRAFTING_SYSTEM_PROMPT is not in Streamlit Secrets.")
                    st.stop()
                _od = _prompt_outdated("DRAFTING_SYSTEM_PROMPT", drafting_prompt)
                if _od:
                    st.error(_od)
                    st.stop()
                author_text = "\n".join(f"- {m}\n  Answer: {a}" for m, a in given.items())
                ok, new_draft = _revise(session_dir, packet_md, model, drafting_prompt,
                                        "draft_final.md",
                                        "AUTHOR INPUT — answers supplied by the human for the flagged gaps. "
                                        "These are author decisions, not source-packet facts. Use them to replace "
                                        "the gap markers they answer. Do not invent anything beyond what is written here.\n\n" + author_text,
                                        "final")
                if not ok:
                    st.error(f"Could not apply the answers: {new_draft}")
                    st.stop()
                with open(final_path, "w") as f:
                    f.write(new_draft)
                with open(os.path.join(session_dir, "draft_final.txt"), "w") as f:
                    f.write(new_draft)
                _summary, _err = _docsrc_check_summary(session_dir, "draft_final.txt")
                remaining = len(_find_markers(new_draft))
                # The success message must survive the rerun below, or
                # it never shows: st.rerun() wipes anything rendered
                # on this run. Keep it in session state and show it
                # once at the top of this section (found live Nov 11,
                # 2026 — no confirmation appeared after Apply).
                if remaining == 0:
                    st.session_state.gap_result = ("All flagged gaps answered — the draft is now a clean copy "
                                                   "(0 markers). Download it below.")
                else:
                    st.session_state.gap_result = (f"Answers applied. {remaining} gap(s) still flagged — "
                                                   "answer them above, or press “Download as it stands” below.")
                if _summary:
                    st.session_state.gap_result += " " + _summary
                st.rerun()
            if st.button("Download as it stands"):
                # The downloads in section 4 stay locked while gaps
                # remain, so taking the draft is an explicit choice,
                # not the default. (Nov 12, 2026: downloads present
                # before the human input made the run look finished,
                # and let people take the draft before the loop was
                # done.)
                st.session_state.download_unlocked = True
                st.rerun()

    # --- Download
    st.header("4. Download")
    st.write("The final draft, as it stands, including any flagged gap "
             "markers. Labelled Discussion Draft.")
    _final = os.path.join(session_dir, "draft_final.md")
    _locked = False
    if os.path.exists(_final):
        _n = len(_find_markers(_draft_text(session_dir, "draft_final.md")))
        if _n and not st.session_state.get("download_unlocked"):
            # Locked while gaps remain: the buttons made the run
            # look finished before the human had answered. The
            # human unlocks them from section 3, or by answering
            # every gap (0 markers opens them on its own).
            _locked = True
            st.warning(f"The final draft still has {_n} flagged gap(s) — it is a list of questions as much as a draft. "
                       "Answer them in section 3 above, or press “Download as it stands” there to take it as it is.")
    if not _locked:
        for fname in ("draft_final.md", "draft_v3.md", "draft_v2.md", "draft_v1.md", "source_packet.md"):
            path = os.path.join(session_dir, fname)
            if os.path.exists(path):
                with open(path, "rb") as f:
                    st.download_button(f"Download {fname}", f.read(), file_name=fname)
                if fname.startswith("draft_"):
                    # RTF version of the same draft, for Word: same
                    # content, including the Discussion Draft status and
                    # any flagged gap markers. Generated on demand from
                    # the .md, so it never goes stale.
                    rtf_name = fname.replace(".md", ".rtf")
                    rtf_path = os.path.join(session_dir, rtf_name)
                    if (not os.path.exists(rtf_path)
                            or os.path.getmtime(rtf_path) < os.path.getmtime(path)):
                        run(["python3", os.path.join(BASE, "agents/drafting-agent/scripts/md_to_rtf.py"),
                             path, rtf_path])
                    if os.path.exists(rtf_path):
                        with open(rtf_path, "rb") as f:
                            st.download_button(f"Download {rtf_name} (Word)", f.read(), file_name=rtf_name)
    if not os.path.exists(session_dir):
        st.caption("No draft yet in this session. Run the pipeline first.")



if __name__ == "__main__":
    main()
