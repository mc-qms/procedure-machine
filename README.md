# The Procedure Machine

Multi-agent procedure orchestration, from guidance to a solid first draft of an SOP or test method.

Give it a purpose, a scope, and your source documents — guidance, instrument manuals, reference procedures — and it drafts an SOP or a test method through a full loop: drafting, human-factors review, drafting, cold-read audit, drafting, cold read, final draft. Python owns what must be true; the LLM owns what should feel human.

## How it works

1. **Purpose & scope** — you say what document you want, what it covers, and what template to use. SOPs and test methods are in scope; policy, work instructions, and protocols are flagged out of scope. Or pick the built-in example — a pH test method from US EPA Method 150.1, source included — and watch a full run without bringing a document.
2. **Fetch & intake** — source links are fetched (public links only) or files uploaded. Every source is read and recorded with `docsrc.py` (OK / PARTIAL / UNREADABLE). A source that cannot be read stops that source; it is never filled in from another.
3. **Packet builder** — the relevant sections are pulled out verbatim, labelled by source and section, with a model relevance check per section. Target 8,000–12,000 tokens, hard cap 20,000. A section is included whole or not at all.
4. **Drafting** — the drafting model writes draft v1 from the packet. What it cannot ground in the packet becomes a gap marker, never invented text, and the deterministic fills (Records, References, Responsibilities) come from the packet itself.
5. **Human factors** — a structured review of whether a qualified user can actually follow the draft in order. Findings go back to drafting.
6. **Cold-read audit** — a fresh audit of the draft and packet only, no drafting history, no HFE reasoning. Findings are ordered by load-bearing weight, not severity, with no grade and no score. A deterministic filter drops findings that only restate a gap already flagged in the draft.
7. **Human in the loop** — gaps that need an author answer pause for the human. "I don't know" is a valid answer; that item stays a flagged gap and the run continues. A run may end as a Discussion Draft with markers visible. A formal clean copy needs zero markers.
The loop is: drafting, HFE, drafting, cold read, drafting, cold read, final draft. A run takes minutes and costs cents — the Python does the bulk of the work for free, and each model call is one narrow judgment on a small prompt.

## The design principle

> Python owns what must be true; the LLM owns what should feel human.

- Narrow single-workflow agents, smallest workable skill set, human keeps the final decision.
- Agents draft and format. They do not decide root cause, disposition, or acceptance criteria.
- Zero inference: leave a placeholder and flag what is missing; never invent a value, a step, or a criterion.
- Facts trace to a user-provided source. If a reviewer could not explain the output to an auditor without the agent, the scope is too wide.

Skills are the testable core; agent instructions stay thin (role, boundaries, which skill when). `app.py` is the orchestrator; the pipeline stages live under `skills/` and `agents/`.

## Run it

### Streamlit Cloud (the live app)

1. Fork or clone this repo.
2. In Streamlit Cloud, create an app from `app.py`.
3. In Settings → Secrets, paste the contents of `.streamlit/secrets.toml.example` and fill in your own `OPENROUTER_API_KEY` plus the three system prompts. The key and the prompts are never committed — `.streamlit/secrets.toml` is gitignored.
4. Deploy. The app runs the full pipeline in the browser: purpose and scope, template picker (including "describe it" custom templates), the pipeline view, human gates as buttons, and download for the final draft.

### Locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export OPENROUTER_API_KEY=your_key_here
streamlit run app.py
```

The pipeline also runs headlessly from the scripts — that is how it was built and tested. Each script has `--help`.

## Project layout

```
app.py                  Streamlit front end (pipeline view, human gates, download)
examples/               the built-in example source (US EPA Method 150.1 text, public domain) the example picker loads
requirements.txt        streamlit + pypdf
.streamlit/
  secrets.toml.example  template for Streamlit Secrets (key + prompts, no real values)
agents/
  audit-agent/          dedup.py — deterministic filter for cold-read findings
  drafting-agent/       draft.py + md_to_rtf.py (Word downloads)
  model_call.py         one shared model call (env mode for Streamlit, vault mode for local tests)
skills/
  fetch-link/           fetch a public link (Python only, no LLM)
  source-intake/        docsrc.py 2.1 — read documents (Python only)
  packet-builder/       build the condensed packet; relevance, compaction, fit check, and lookup calls
templates/              sop-default, equipment-sop, sop-lab, test-method-default + "describe it" builder (the picker defaults to Auto — the machine reads the template out of your description)
```

## What is not in this repo

- The design standards file this work is built from — it is a private working standard.
- Any work-agent instructions or skills from a previous employer, and anything company-specific (document numbers, product names, real procedures). Everything here was rebuilt from first principles, not exported.
- Any API key. The OpenRouter key and the polished agent prompts live in Streamlit Secrets, not in the code.

## Test history

The build was tested run by run: intake, drafting, HFE and cold read as model calls, the Flash downgrade (about 17× cheaper than Pro for the same findings), the dedup filter, the full loop, templates and test methods back in scope, custom templates from a plain-language description, the app wiring, a real guidance document (ICH Q2(R2)), Q2 rebuilt as an SOP, and the human-in-the-loop run that produced the first clean copy — zero markers, numbering clean, cross-references resolving.

## License

MIT. See `LICENSE`.
