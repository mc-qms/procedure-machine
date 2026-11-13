# The Procedure Machine

Multi-agent procedure drafting, from guidance to a polished SOP or test method.

Give it a purpose, a scope, and your source documents — guidance, instrument manuals, reference procedures — and it drafts the document through a full loop: drafting, human-factors review, drafting, cold-read audit, drafting, cold read, final draft. Python owns what must be true; the LLM owns what should feel human.

## How it works

1. **Purpose & scope** — you say what document you want, what it covers, and which template to use. SOPs and test methods are in scope; policies, work instructions, and protocols are flagged out of scope.
2. **Fetch & intake** — source links are fetched (public links only; every redirect hop is re-validated) or files uploaded. Every source is read and recorded (OK / PARTIAL / UNREADABLE). A source that cannot be read stops that source; it is never filled in from another.
3. **Packet builder** — the relevant sections are pulled out verbatim, labelled by source and section, with a model relevance check per section. Target 8,000–12,000 tokens, hard cap 20,000. A packet-coverage check then looks for workflow steps the packet does not cover, fetches just those sections if the sources have them, and classifies the fit between the sources and the document you asked for.
4. **Drafting** — the drafting model writes the first draft from the packet and the template. Anything the sources do not support becomes a flagged gap marker, never invented text.
5. **Human factors** — a structured review of whether a qualified user can actually follow the draft in order, including prose clarity. Findings go back to drafting.
6. **Cold-read audit** — a fresh audit of the draft and packet only: no drafting history, no HFE reasoning. Every concern is reconciled against the whole document before it is reported. Findings are ordered by load-bearing weight, not severity, with no grade and no score. A deterministic filter drops findings that only restate a gap already flagged in the draft.
7. **Human in the loop** — gaps that need an author answer pause for the human, twice. "I don't know" is a valid answer; that item stays a flagged gap and the run continues. A run may end as a Discussion Draft with markers visible. A formal clean copy needs zero markers.
8. **Delivery checks** — deterministic checks verify section numbering, cross-references, and remaining markers, and the results are shown with the finished draft.

## The design principle

> Python owns what must be true; the LLM owns what should feel human.

- Narrow single-workflow agents; the human keeps the final decision.
- Agents draft and format. They do not decide root cause, disposition, or acceptance criteria.
- Zero inference: leave a placeholder and flag what is missing; never invent a value, a step, or a criterion.
- Facts trace to a user-provided source. If a reviewer could not explain the output to an auditor without the agent, the scope is too wide.

## Running it

The app is a Streamlit app (`app.py`). It needs an OpenRouter API key and three agent prompts in Streamlit Secrets — see `.streamlit/secrets.toml.example` for the names and the model-routing defaults. The prompts themselves are the author's private instruction sets and are not distributed with this repository.

## License

MIT — see `LICENSE`.
