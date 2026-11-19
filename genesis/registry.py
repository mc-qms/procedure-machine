"""Genesis mode registry — deterministic data, no model calls.

Genesis builds one procedure from nothing: the user picks an
archetype from a standard list (never a free-text description of
their company), picks the one procedure they need, and the machine
assembles the packet from the public regulations and guidance
registered here for that topic.

Everything in this file is data a human curated:
- ARCHETYPES: the pick-list. Each entry names the regulation stack
  that archetype lives under (shown to the user, and used to word
  the scope) and any procedures that archetype adds to the core
  quality-system list.
- MARKETS / FUNCTIONS: the other two selections. Selections only —
  nothing about the user's own company is ever typed in.
- CORE_PROCEDURES: the quality-system checklist, drawn from the
  ICH Q10 pharmaceutical quality system elements and the EU GMP
  chapter structure. It is a menu, not a batch job: Genesis builds
  one procedure at a time, and the checklist shows what a system
  for the archetype needs.
- TOPICS: the procedures Genesis can build today. Each entry maps
  the topic to its packet sources — public documents only, each
  with the URL the fetch step retrieves it from, the filename it
  is stored under in the session, and the citation instruments it
  puts into the packet (the citation check verifies draft
  citations against exactly these, at the exact revision named).
  USP <1225> is deliberately absent from the method-validation
  entry: it is paywalled, and Genesis sources are public or they
  are not sources.
- Each topic also declares its COVERAGE: what its packet genuinely
  backs (stated positively), and the market / archetype selections
  that run past the packet. The build compares the user's
  selections against the declaration and flags every deficit —
  the run proceeds, but a selection the sources do not cover is
  never allowed to look covered (Don't Halt, Flag Gaps).

Adding a topic is adding an entry: title, purpose and scope text,
keywords for the describe-it fallback, and the source list. The
purpose and scope texts carry {archetype}, {market}, and
{functions} placeholders, filled deterministically from the
user's selections when the packet is built.
"""

VERSION = "1.0"

ARCHETYPES = [
    {
        "id": "small-molecule",
        "label": "Small-molecule drug product",
        "reg_stack": "21 CFR Parts 210/211; ICH Q7, Q9, Q10; EU GMP Parts I and II",
        "additions": ["Containment and Cross-Contamination Control"],
    },
    {
        "id": "mab-biologic",
        "label": "Monoclonal antibody / biologic",
        "reg_stack": "21 CFR Parts 210/211 and 600-610; ICH Q5, Q9, Q10; EU GMP Part I and Annex 2",
        "additions": ["Aseptic Processing and Media Fills",
                      "Cell Bank Management", "Viral Clearance"],
    },
    {
        "id": "cell-therapy",
        "label": "Cell therapy (CAR-T)",
        "reg_stack": "21 CFR Parts 210/211 and 1271 (HCT/Ps); ICH Q9, Q10; EU GMP Part I and ATMP rules",
        "additions": ["Chain of Identity and Chain of Custody",
                      "Donor Eligibility (HCT/P)",
                      "Apheresis and Starting Material Handling"],
    },
    {
        "id": "gene-therapy",
        "label": "Gene therapy",
        "reg_stack": "21 CFR Parts 210/211 and 1271 (HCT/Ps); ICH Q5, Q9, Q10; EU GMP Part I and ATMP rules",
        "additions": ["Vector Production Controls", "Donor Eligibility (HCT/P)"],
    },
    {
        "id": "vaccine",
        "label": "Vaccine",
        "reg_stack": "21 CFR Parts 210/211 and 600-610; ICH Q5, Q9, Q10; EU GMP Part I and Annex 2",
        "additions": ["Seed Lot Management", "Aseptic Processing and Media Fills"],
    },
    {
        "id": "ivd",
        "label": "In vitro diagnostics",
        "reg_stack": "21 CFR Parts 809 and 820; EU IVDR; ICH Q10 principles",
        "additions": ["Design Controls and Design Transfer",
                      "Performance Evaluation"],
    },
    {
        "id": "combination",
        "label": "Combination product (drug-device)",
        "reg_stack": "21 CFR Part 4; Parts 210/211 and 820; ICH Q9, Q10; EU GMP and MDR",
        "additions": ["Design Controls", "Human Factors Engineering"],
    },
    {
        "id": "device",
        "label": "Medical device",
        "reg_stack": "21 CFR Part 820; EU MDR; ISO 13485 (structure only - the standard itself is not a Genesis source)",
        "additions": ["Design Controls and Design Transfer",
                      "Device History Records", "UDI and Labeling Control"],
    },
]

MARKETS = [
    {"id": "us", "label": "US", "scope_text": "the United States"},
    {"id": "eu", "label": "EU", "scope_text": "the European Union"},
    {"id": "us-eu", "label": "US and EU", "scope_text": "the United States and the European Union"},
]

FUNCTIONS = [
    "Quality Assurance",
    "Quality Control laboratory",
    "Microbiology laboratory",
    "Manufacturing",
    "Packaging and labeling",
    "Warehouse and distribution",
    "Engineering and maintenance",
    "Regulatory Affairs",
    "Clinical operations",
]

# The quality-system checklist: what a system for any archetype
# needs, before archetype additions. Drawn from the ICH Q10
# elements (monitoring, CAPA, change management, management
# review, with knowledge management and quality risk management
# as enablers) and the EU GMP chapter structure.
CORE_PROCEDURES = [
    "Document Control",
    "Change Control",
    "Deviation and Nonconformance Management",
    "Corrective and Preventive Action (CAPA)",
    "Training and Qualification",
    "Internal Audit (Self-Inspection)",
    "Management Review",
    "Quality Risk Management",
    "Supplier Quality and Supplier Audits",
    "Complaint Handling",
    "Product Recall",
    "Process Validation",
    "Cleaning Validation",
    "Analytical Procedure Validation (Test Method Validation)",
    "Computer System Validation and Data Integrity",
    "Proper Use of AI in a Regulated Environment",
    "Calibration and Preventive Maintenance",
    "Environmental Monitoring",
    "Stability Testing",
    "Out-of-Specification (OOS) Investigation",
    "Batch Record Review and Product Release",
    "Annual Product Quality Review",
    "Labeling and Packaging Control",
    "Warehouse and Distribution Control",
]

TOPICS = [
    {
        "id": "ai-use",
        "title": "Proper use of AI in a regulated environment",
        "procedure_name": "Proper Use of AI in a Regulated Environment",
        "sop_title": "Proper Use of Artificial Intelligence in a Regulated Environment",
        "purpose": (
            "Establish the requirements for the selection, assessment, "
            "approval, use, and monitoring of artificial intelligence "
            "tools in regulated activities."
        ),
        # Principles this procedure carries as obligations in its
        # body (Responsibilities / Procedure). They are not Purpose
        # text: the drafting prompt hands them to the drafting pass
        # separately, as obligations to state in the body.
        "principles": [
            "AI output supports, and never replaces, qualified human "
            "review: a qualified person reviews AI-assisted output and "
            "remains accountable for every record or decision it "
            "contributes to.",
            "Every AI-assisted record is traceable to the sources used "
            "to produce it.",
        ],
        "coverage": {
            "covers": [
                "United States requirements and guidance: the packet's "
                "FDA draft guidance and the NIST AI Risk Management "
                "Framework are US sources, and the ICH guidelines in "
                "the packet apply in the US.",
                "ICH-level quality-system and quality-risk requirements "
                "(ICH Q10, ICH Q9(R1)), which apply in the US, the EU, "
                "and the other ICH regions.",
            ],
            "markets": {
                "us": None,
                "eu": (
                    "EU market selected, but the packet contains no "
                    "EU-specific AI sources: the EU AI Act, the EMA "
                    "reflection paper on artificial intelligence, and "
                    "EU GMP Annex 11 are not in it. EU coverage in this "
                    "draft rests on the ICH guidelines only."
                ),
            },
            "archetypes": {
                "combination": (
                    "Combination product (drug-device) selected, but the "
                    "packet contains no device or combination-product "
                    "sources: 21 CFR Part 4 (combination products) and "
                    "21 CFR Part 820 (device quality system regulation) "
                    "are not in it. Device-side obligations are not "
                    "covered."
                ),
                "device": (
                    "Medical device selected, but the packet contains no "
                    "device quality-system sources: 21 CFR Part 820 and "
                    "the EU MDR are not in it; its only device-oriented "
                    "source is the GMLP guiding principles. Device "
                    "obligations are not covered."
                ),
                "ivd": (
                    "In vitro diagnostics selected, but the packet "
                    "contains no diagnostics-specific sources: 21 CFR "
                    "Parts 809 and 820 and the EU IVDR are not in it. "
                    "Diagnostics obligations are not covered."
                ),
            },
        },
        "scope_in": (
            "Applies to all personnel at a {archetype} organization marketing "
            "products in {market} who use, evaluate, approve, or oversee "
            "artificial intelligence tools that draft, check, summarize, or "
            "analyze content used in regulated records, submissions, or quality "
            "decisions, in the following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover artificial intelligence embedded in validated "
            "manufacturing or laboratory equipment under change control, or "
            "software features that do not touch regulated records or decisions."
        ),
        "intended_user": (
            "Personnel who use or approve AI tools in regulated work, and the "
            "quality unit that oversees that use"
        ),
        "keywords": [
            "artificial intelligence", "machine learning", "ai tool", "use of ai",
            "ai use", "llm", "chatbot", "generative", "algorithm", "model risk",
        ],
        "sources": [
            {
                "name": "FDA draft guidance: Considerations for the Use of Artificial "
                        "Intelligence to Support Regulatory Decision-Making for Drug "
                        "and Biological Products (January 2025)",
                "url": "https://www.fda.gov/media/184830/download",
                "filename": "fda-ai-decision-making-draft-guidance.pdf",
                "instruments": ["FDA AI decision-making draft guidance"],
            },
            {
                "name": "NIST Artificial Intelligence Risk Management Framework "
                        "(AI RMF 1.0, NIST AI 100-1)",
                "url": "https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf",
                "filename": "nist-ai-rmf-1-0.pdf",
                "instruments": ["NIST AI RMF", "NIST AI 100-1", "AI RMF"],
            },
            {
                "name": "Good Machine Learning Practice for Medical Device "
                        "Development: Guiding Principles (FDA, Health Canada, MHRA)",
                "url": "https://www.fda.gov/media/153094/download",
                "filename": "gmlp-guiding-principles.pdf",
                "instruments": ["Good Machine Learning Practice", "GMLP"],
            },
            {
                "name": "ICH Q10: Pharmaceutical Quality System",
                "url": "https://database.ich.org/sites/default/files/Q10%20Guideline.pdf",
                "filename": "ich-q10.pdf",
                "instruments": ["ICH Q10"],
            },
            {
                "name": "ICH Q9(R1): Quality Risk Management",
                "url": "https://database.ich.org/sites/default/files/ICH_Q9%28R1%29_Guideline_Step4_2022_1219.pdf",
                "filename": "ich-q9-r1.pdf",
                "instruments": ["ICH Q9(R1)"],
            },
        ],
    },
    {
        "id": "method-validation",
        "title": "Validation of test methods",
        "procedure_name": "Analytical Procedure Validation (Test Method Validation)",
        "sop_title": "Validation of Analytical Test Methods",
        "purpose": (
            "Describe how analytical test methods are validated - the "
            "characteristics assessed, the studies performed, and the "
            "criteria applied to demonstrate each method suitable for "
            "its intended use."
        ),
        "coverage": {
            "covers": [
                "ICH Q2(R2) and ICH Q14, which are adopted in the US, "
                "the EU, and the other ICH regions.",
                "United States expectations: the FDA guidance on "
                "analytical procedures and methods validation is in "
                "the packet.",
            ],
            "markets": {
                "us": None,
                "eu": (
                    "EU market selected: ICH Q2(R2) and ICH Q14 are "
                    "adopted in the EU and are in the packet, but no "
                    "EU-specific instrument (such as EU GMP Chapter 6, "
                    "Quality Control) is in it."
                ),
            },
            "archetypes": {
                "device": (
                    "Medical device selected: for devices, analytical "
                    "validation sits inside design controls (21 CFR "
                    "Part 820), which this packet does not cover."
                ),
                "ivd": (
                    "In vitro diagnostics selected: for diagnostics, "
                    "analytical performance is established under design "
                    "controls and performance evaluation (21 CFR Parts "
                    "809 and 820, EU IVDR), which this packet does not "
                    "cover."
                ),
            },
        },
        "scope_in": (
            "Applies to the validation of analytical procedures used for "
            "release, stability, and in-process testing at a {archetype} "
            "organization marketing products in {market}, in the following "
            "functions: {functions}."
        ),
        "scope_out": (
            "Does not cover analytical procedure development, method transfer "
            "between laboratories, or verification of compendial procedures."
        ),
        "intended_user": (
            "Analytical scientists and reviewers in the quality control "
            "laboratory, and the quality unit"
        ),
        "keywords": [
            "validat", "analyt", "method", "accuracy", "precision",
            "specificity", "linearity", "robustness", "detection limit",
            "quantitation limit", "test method",
        ],
        "sources": [
            {
                "name": "ICH Q2(R2): Validation of Analytical Procedures",
                "url": "https://database.ich.org/sites/default/files/ICH_Q2%28R2%29_Guideline_2023_1130.pdf",
                "filename": "ich-q2-r2.pdf",
                "instruments": ["ICH Q2(R2)"],
            },
            {
                "name": "ICH Q14: Analytical Procedure Development",
                "url": "https://database.ich.org/sites/default/files/ICH_Q14_Guideline_2023_1116_1.pdf",
                "filename": "ich-q14.pdf",
                "instruments": ["ICH Q14"],
            },
            {
                "name": "FDA guidance: Analytical Procedures and Methods Validation "
                        "for Drugs and Biologics (July 2015)",
                "url": "https://www.fda.gov/media/87801/download",
                "filename": "fda-analytical-procedures-methods-validation.pdf",
                "instruments": ["FDA methods validation guidance"],
            },
        ],
    },
]


def archetype_by_label(label):
    return next((a for a in ARCHETYPES if a["label"] == label), None)


def market_by_label(label):
    return next((m for m in MARKETS if m["label"] == label), None)


def topic_by_id(topic_id):
    return next((t for t in TOPICS if t["id"] == topic_id), None)


def topic_by_title(title):
    return next((t for t in TOPICS if t["title"] == title), None)


def coverage_flags(topic, market, archetype):
    """Deterministic coverage flags for one run: the deficits
    between what the user selected and what the topic's packet
    genuinely covers, from the topic's own coverage declaration.
    A combined market (US and EU) is checked as both of its
    components. An empty list means the selections sit inside
    what the packet covers. The run always proceeds - the flags
    travel with the draft (Don't Halt, Flag Gaps)."""
    cov = topic.get("coverage", {}) if topic else {}
    flags = []
    markets = cov.get("markets", {})
    market_id = (market or {}).get("id", "")
    components = ("us", "eu") if market_id == "us-eu" else (market_id,)
    for component in components:
        flag = markets.get(component)
        if flag:
            flags.append(flag)
    if archetype:
        flag = cov.get("archetypes", {}).get(archetype.get("id", ""))
        if flag:
            flags.append(flag)
    return flags


def procedures_for(archetype_id):
    """The checklist for one archetype: core list plus its
    additions, each entry marked with the Genesis topic that can
    build it today, when there is one. The checklist is a menu -
    Genesis builds one procedure at a time."""
    arch = next((a for a in ARCHETYPES if a["id"] == archetype_id), None)
    names = list(CORE_PROCEDURES)
    if arch:
        for extra in arch.get("additions", []):
            if extra not in names:
                names.append(extra)
    by_procedure = {t["procedure_name"]: t["id"] for t in TOPICS}
    return [{"name": n, "topic_id": by_procedure.get(n)} for n in names]


def match_topic(text):
    """Best registry topic for a free-text request, by keyword
    overlap (word-boundary phrase match, or a stem of five or more
    characters matched as a prefix). Returns (topic, hits) or
    (None, best_hits). A match needs at least two distinct keyword
    hits and strictly more than any other topic - anything weaker
    is no match, and the caller flags the partial coverage instead
    of guessing (Don't Halt, Flag Gaps)."""
    import re
    low = " " + (text or "").lower() + " "

    def hits_for(topic):
        hits = 0
        for kw in topic["keywords"]:
            if len(kw) >= 5 and " " not in kw:
                if re.search(r"\b" + re.escape(kw), low):
                    hits += 1
            elif kw.lower() in low:
                hits += 1
        return hits

    scored = sorted(((hits_for(t), t) for t in TOPICS),
                    key=lambda p: p[0], reverse=True)
    if not scored:
        return None, 0
    best_hits, best = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0
    if best_hits >= 2 and best_hits > second:
        return best, best_hits
    return None, best_hits
