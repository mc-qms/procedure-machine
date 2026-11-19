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
- SOURCES: the source library. The core public documents are
  registered once, each with a stable id, the URL the fetch step
  retrieves it from, the filename it is stored under in the
  session, and the citation instruments it puts into the packet
  (the citation check verifies draft citations against exactly
  these, at the exact revision named). Every URL here was
  fetch-verified when it was registered: a source that cannot be
  fetched and read is not a source. USP and ISO standards are
  deliberately absent: they are paywalled, and Genesis sources are
  public or they are not sources.
- TOPICS: the procedures Genesis can build — every item on the
  core checklist, plus the archetype additions. Each entry maps
  the topic to its packet as a list of library source ids
  (typically a shared spine — ICH Q10, ICH Q9(R1), the relevant
  EU GMP chapter — plus the topic's own sources), and declares
  its purpose and scope text, keywords for the describe-it
  fallback, and its COVERAGE: what the packet genuinely backs,
  and the selections that run past it. The build compares the
  user's selections against the declaration and flags every
  deficit — the run proceeds, but a selection the sources do not
  cover is never allowed to look covered (Don't Halt, Flag Gaps).

Adding a topic is adding an entry: title, purpose and scope text,
the roles the procedure's responsibilities are written against
(actors in the process, not departments — the functions a user
selects set the scope's applicability only), keywords for the
describe-it fallback, and the source id list.
The purpose and scope texts carry {archetype}, {market}, and
{functions} placeholders, filled deterministically from the
user's selections when the packet is built.
"""

VERSION = "2.0"

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
        "additions": ["Design Controls and Design Transfer",
                      "Human Factors Engineering"],
    },
    {
        "id": "device",
        "label": "Medical device",
        "reg_stack": "21 CFR Part 820; EU MDR; ISO 13485 (structure only - the standard itself is not a source here)",
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
    "Good Documentation Practices",
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
    "AI Use",
    "Calibration and Preventive Maintenance",
    "Environmental Monitoring",
    "Stability Testing",
    "Out-of-Specification (OOS) Investigation",
    "Batch Record Review and Product Release",
    "Annual Product Quality Review",
    "Labeling and Packaging Control",
    "Warehouse and Distribution Control",
]

# The source library: the core public documents, registered once.
# Topics name these by id. Every URL was downloaded and read back
# when it was registered (see the build record); a URL that stops
# working is a broken source, and the build says so at fetch time
# rather than filling in from another document.
SOURCES = {
    # --- ICH guidelines ---
    "ich-q1a-r2": {
        "name": "ICH Q1A(R2): Stability Testing of New Drug Substances and Products",
        "url": "https://www.ema.europa.eu/en/documents/scientific-guideline/ich-q-1-r2-stability-testing-new-drug-substances-and-products-step-5_en.pdf",
        "filename": "ich-q1a-r2.pdf",
        "instruments": ["ICH Q1A(R2)"],
    },
    "ich-q2-r2": {
        "name": "ICH Q2(R2): Validation of Analytical Procedures",
        "url": "https://database.ich.org/sites/default/files/ICH_Q2%28R2%29_Guideline_2023_1130.pdf",
        "filename": "ich-q2-r2.pdf",
        "instruments": ["ICH Q2(R2)"],
    },
    "ich-q5a-r2": {
        "name": "ICH Q5A(R2): Viral Safety Evaluation of Biotechnology Products Derived from Cell Lines of Human or Animal Origin",
        "url": "https://www.ema.europa.eu/en/documents/scientific-guideline/ich-q5ar2-guideline-viral-safety-evaluation-biotechnology-products-derived-cell-lines-human-or-animal-origin-step-5_en.pdf",
        "filename": "ich-q5a-r2.pdf",
        "instruments": ["ICH Q5A(R2)"],
    },
    "ich-q5d": {
        "name": "ICH Q5D: Derivation and Characterisation of Cell Substrates Used for Production of Biotechnological/Biological Products",
        "url": "https://database.ich.org/sites/default/files/Q5D%20Guideline.pdf",
        "filename": "ich-q5d.pdf",
        "instruments": ["ICH Q5D"],
    },
    "ich-q7": {
        "name": "ICH Q7: Good Manufacturing Practice Guide for Active Pharmaceutical Ingredients",
        "url": "https://www.ema.europa.eu/en/documents/scientific-guideline/ich-q-7-good-manufacturing-practice-active-pharmaceutical-ingredients-step-5_en.pdf",
        "filename": "ich-q7.pdf",
        "instruments": ["ICH Q7"],
    },
    "ich-q8-r2": {
        "name": "ICH Q8(R2): Pharmaceutical Development",
        "url": "https://database.ich.org/sites/default/files/Q8%28R2%29%20Guideline.pdf",
        "filename": "ich-q8-r2.pdf",
        "instruments": ["ICH Q8(R2)"],
    },
    "ich-q9-r1": {
        "name": "ICH Q9(R1): Quality Risk Management",
        "url": "https://database.ich.org/sites/default/files/ICH_Q9%28R1%29_Guideline_Step4_2022_1219.pdf",
        "filename": "ich-q9-r1.pdf",
        "instruments": ["ICH Q9(R1)"],
    },
    "ich-q10": {
        "name": "ICH Q10: Pharmaceutical Quality System",
        "url": "https://database.ich.org/sites/default/files/Q10%20Guideline.pdf",
        "filename": "ich-q10.pdf",
        "instruments": ["ICH Q10"],
    },
    "ich-q12": {
        "name": "ICH Q12: Technical and Regulatory Considerations for Pharmaceutical Product Lifecycle Management",
        "url": "https://www.ema.europa.eu/en/documents/scientific-guideline/ich-guideline-q12-technical-and-regulatory-considerations-pharmaceutical-product-lifecycle-management-step-5_en.pdf",
        "filename": "ich-q12.pdf",
        "instruments": ["ICH Q12"],
    },
    "ich-q14": {
        "name": "ICH Q14: Analytical Procedure Development",
        "url": "https://database.ich.org/sites/default/files/ICH_Q14_Guideline_2023_1116_1.pdf",
        "filename": "ich-q14.pdf",
        "instruments": ["ICH Q14"],
    },
    # --- EU GMP Guide, Part I chapters (EudraLex Volume 4) ---
    "eu-gmp-ch1": {
        "name": "EU GMP Part I, Chapter 1: Pharmaceutical Quality System",
        "url": "https://health.ec.europa.eu/document/download/e458c423-f564-4171-b344-030a461c567f_en?filename=vol4-chap1_2013-01_en.pdf",
        "filename": "eu-gmp-chapter-1.pdf",
        "instruments": ["EU GMP Chapter 1"],
    },
    "eu-gmp-ch2": {
        "name": "EU GMP Part I, Chapter 2: Personnel",
        "url": "https://health.ec.europa.eu/document/download/11f4f8e6-a6e9-4897-afe3-f21e1dc56cb8_en?filename=2014-03_chapter_2.pdf",
        "filename": "eu-gmp-chapter-2.pdf",
        "instruments": ["EU GMP Chapter 2"],
    },
    "eu-gmp-ch3": {
        "name": "EU GMP Part I, Chapter 3: Premises and Equipment",
        "url": "https://health.ec.europa.eu/document/download/18d76565-137b-41d2-a602-794527f708c1_en?filename=chapter_3.pdf",
        "filename": "eu-gmp-chapter-3.pdf",
        "instruments": ["EU GMP Chapter 3"],
    },
    "eu-gmp-ch4": {
        "name": "EU GMP Part I, Chapter 4: Documentation",
        "url": "https://health.ec.europa.eu/document/download/104b3eb8-81a7-4858-9419-cb06562adb66_en?filename=chapter4_01-2011_en.pdf",
        "filename": "eu-gmp-chapter-4.pdf",
        "instruments": ["EU GMP Chapter 4"],
    },
    "eu-gmp-ch5": {
        "name": "EU GMP Part I, Chapter 5: Production",
        "url": "https://health.ec.europa.eu/document/download/4a1fdb4f-6f6f-49c4-b264-8056e5bbe078_en?filename=chapter_5.pdf",
        "filename": "eu-gmp-chapter-5.pdf",
        "instruments": ["EU GMP Chapter 5"],
    },
    "eu-gmp-ch6": {
        "name": "EU GMP Part I, Chapter 6: Quality Control",
        "url": "https://health.ec.europa.eu/document/download/c74c8720-27bf-4252-808f-d65a206a90bb_en?filename=2014-11_vol4_chapter_6.pdf",
        "filename": "eu-gmp-chapter-6.pdf",
        "instruments": ["EU GMP Chapter 6"],
    },
    "eu-gmp-ch7": {
        "name": "EU GMP Part I, Chapter 7: Outsourced Activities",
        "url": "https://health.ec.europa.eu/document/download/58b5106a-cf6f-4352-9dca-1caf5d27d97e_en?filename=vol4-chap7_2012-06_en.pdf",
        "filename": "eu-gmp-chapter-7.pdf",
        "instruments": ["EU GMP Chapter 7"],
    },
    "eu-gmp-ch8": {
        "name": "EU GMP Part I, Chapter 8: Complaints, Quality Defects and Product Recalls",
        "url": "https://health.ec.europa.eu/document/download/b1eb2292-cb0d-4e3f-aea9-e3fe79faf6e3_en?filename=2014-08_gmp_chap8.pdf",
        "filename": "eu-gmp-chapter-8.pdf",
        "instruments": ["EU GMP Chapter 8"],
    },
    "eu-gmp-ch9": {
        "name": "EU GMP Part I, Chapter 9: Self Inspection",
        "url": "https://health.ec.europa.eu/document/download/07195808-d02e-4d7a-b8f4-f84a83278b62_en?filename=cap9_en.pdf",
        "filename": "eu-gmp-chapter-9.pdf",
        "instruments": ["EU GMP Chapter 9"],
    },
    # --- EU GMP annexes and related EU documents ---
    "eu-gmp-annex1": {
        "name": "EU GMP Annex 1: Manufacture of Sterile Medicinal Products (2022)",
        "url": "https://health.ec.europa.eu/document/download/e05af55b-38e9-42bf-8495-194bbf0b9262_en?filename=20220825_gmp-an1_en_0.pdf",
        "filename": "eu-gmp-annex-1.pdf",
        "instruments": ["EU GMP Annex 1"],
    },
    "eu-gmp-annex2": {
        "name": "EU GMP Annex 2: Manufacture of Biological Active Substances and Medicinal Products for Human Use",
        "url": "https://health.ec.europa.eu/document/download/380fdf24-8a1e-4f65-809b-e08d990d5f9e_en?filename=2018_annex2_en.pdf",
        "filename": "eu-gmp-annex-2.pdf",
        "instruments": ["EU GMP Annex 2"],
    },
    "eu-gmp-annex11": {
        "name": "EU GMP Annex 11: Computerised Systems",
        "url": "https://health.ec.europa.eu/document/download/8d305550-dd22-4dad-8463-2ddb4a1345f1_en?filename=annex11_01-2011_en.pdf",
        "filename": "eu-gmp-annex-11.pdf",
        "instruments": ["EU GMP Annex 11"],
    },
    "eu-gmp-annex15": {
        "name": "EU GMP Annex 15: Qualification and Validation",
        "url": "https://health.ec.europa.eu/document/download/7c6c5b3c-4902-46ea-b7ab-7608682fb68d_en?filename=2015-10_annex15.pdf",
        "filename": "eu-gmp-annex-15.pdf",
        "instruments": ["EU GMP Annex 15"],
    },
    "eu-gmp-annex16": {
        "name": "EU GMP Annex 16: Certification by a Qualified Person and Batch Release",
        "url": "https://health.ec.europa.eu/document/download/20c41532-33d5-4635-ae80-8735d3d09fe0_en?filename=v4_an16_201510_en.pdf",
        "filename": "eu-gmp-annex-16.pdf",
        "instruments": ["EU GMP Annex 16"],
    },
    "eu-gmp-atmp": {
        "name": "EU GMP Part IV: Guidelines on Good Manufacturing Practice Specific to Advanced Therapy Medicinal Products",
        "url": "https://health.ec.europa.eu/document/download/ad33d9dd-03f0-4bef-af53-21308ce2187d_en?filename=2017_11_22_guidelines_gmp_for_atmps.pdf",
        "filename": "eu-gmp-atmp-part-iv.pdf",
        "instruments": ["EU GMP Part IV"],
    },
    "eu-gdp": {
        "name": "EU Guidelines on Good Distribution Practice of Medicinal Products for Human Use (2013/C 343/01)",
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:52013XC1123(01)",
        "filename": "eu-gdp-guidelines.pdf",
        "instruments": ["EU GDP Guidelines"],
    },
    "ema-hbel": {
        "name": "EMA Guideline on Setting Health Based Exposure Limits for Use in Risk Identification in the Manufacture of Different Medicinal Products in Shared Facilities",
        "url": "https://www.ema.europa.eu/en/documents/scientific-guideline/guideline-setting-health-based-exposure-limits-use-risk-identification-manufacture-different-medicinal-products-shared-facilities_en.pdf",
        "filename": "ema-hbel-guideline.pdf",
        "instruments": ["EMA HBEL guideline"],
    },
    # --- US Code of Federal Regulations (21 CFR, govinfo annual edition) ---
    "cfr-part-4": {
        "name": "21 CFR Part 4: Regulation of Combination Products",
        "url": "https://www.govinfo.gov/content/pkg/CFR-2025-title21-vol1/pdf/CFR-2025-title21-vol1-part4.pdf",
        "filename": "cfr-part-4.pdf",
        "instruments": ["21 CFR Part 4"],
    },
    "cfr-part-7": {
        "name": "21 CFR Part 7: Enforcement Policy (including Subpart C, Recalls)",
        "url": "https://www.govinfo.gov/content/pkg/CFR-2025-title21-vol1/pdf/CFR-2025-title21-vol1-part7.pdf",
        "filename": "cfr-part-7.pdf",
        "instruments": ["21 CFR Part 7"],
    },
    "cfr-part-11": {
        "name": "21 CFR Part 11: Electronic Records; Electronic Signatures",
        "url": "https://www.govinfo.gov/content/pkg/CFR-2025-title21-vol1/pdf/CFR-2025-title21-vol1-part11.pdf",
        "filename": "cfr-part-11.pdf",
        "instruments": ["21 CFR Part 11"],
    },
    "cfr-part-210": {
        "name": "21 CFR Part 210: Current Good Manufacturing Practice in Manufacturing, Processing, Packing, or Holding of Drugs; General",
        "url": "https://www.govinfo.gov/content/pkg/CFR-2025-title21-vol4/pdf/CFR-2025-title21-vol4-part210.pdf",
        "filename": "cfr-part-210.pdf",
        "instruments": ["21 CFR Part 210"],
    },
    "cfr-part-211": {
        "name": "21 CFR Part 211: Current Good Manufacturing Practice for Finished Pharmaceuticals",
        "url": "https://www.govinfo.gov/content/pkg/CFR-2025-title21-vol4/pdf/CFR-2025-title21-vol4-part211.pdf",
        "filename": "cfr-part-211.pdf",
        "instruments": ["21 CFR Part 211"],
    },
    "cfr-part-600": {
        "name": "21 CFR Part 600: Biological Products; General",
        "url": "https://www.govinfo.gov/content/pkg/CFR-2025-title21-vol7/pdf/CFR-2025-title21-vol7-part600.pdf",
        "filename": "cfr-part-600.pdf",
        "instruments": ["21 CFR Part 600"],
    },
    "cfr-part-610": {
        "name": "21 CFR Part 610: General Biological Products Standards",
        "url": "https://www.govinfo.gov/content/pkg/CFR-2025-title21-vol7/pdf/CFR-2025-title21-vol7-part610.pdf",
        "filename": "cfr-part-610.pdf",
        "instruments": ["21 CFR Part 610"],
    },
    "cfr-part-809": {
        "name": "21 CFR Part 809: In Vitro Diagnostic Products for Human Use",
        "url": "https://www.govinfo.gov/content/pkg/CFR-2025-title21-vol8/pdf/CFR-2025-title21-vol8-part809.pdf",
        "filename": "cfr-part-809.pdf",
        "instruments": ["21 CFR Part 809"],
    },
    "cfr-part-820": {
        "name": "21 CFR Part 820: Quality Management System Regulation (device quality system)",
        "url": "https://www.govinfo.gov/content/pkg/CFR-2025-title21-vol8/pdf/CFR-2025-title21-vol8-part820.pdf",
        "filename": "cfr-part-820.pdf",
        "instruments": ["21 CFR Part 820"],
    },
    "cfr-part-1271": {
        "name": "21 CFR Part 1271: Human Cells, Tissues, and Cellular and Tissue-Based Products (HCT/Ps)",
        "url": "https://www.govinfo.gov/content/pkg/CFR-2025-title21-vol8/pdf/CFR-2025-title21-vol8-part1271.pdf",
        "filename": "cfr-part-1271.pdf",
        "instruments": ["21 CFR Part 1271"],
    },
    # --- FDA guidance and related US sources ---
    "fda-ai-guidance": {
        "name": "FDA draft guidance: Considerations for the Use of Artificial "
                "Intelligence to Support Regulatory Decision-Making for Drug "
                "and Biological Products (January 2025)",
        "url": "https://www.fda.gov/media/184830/download",
        "filename": "fda-ai-decision-making-draft-guidance.pdf",
        "instruments": ["FDA AI decision-making draft guidance"],
    },
    "nist-ai-rmf": {
        "name": "NIST Artificial Intelligence Risk Management Framework "
                "(AI RMF 1.0, NIST AI 100-1)",
        "url": "https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf",
        "filename": "nist-ai-rmf-1-0.pdf",
        "instruments": ["NIST AI RMF", "NIST AI 100-1", "AI RMF"],
    },
    "gmlp-principles": {
        "name": "Good Machine Learning Practice for Medical Device "
                "Development: Guiding Principles (FDA, Health Canada, MHRA)",
        "url": "https://www.fda.gov/media/153094/download",
        "filename": "gmlp-guiding-principles.pdf",
        "instruments": ["Good Machine Learning Practice", "GMLP"],
    },
    "fda-methods-validation": {
        "name": "FDA guidance: Analytical Procedures and Methods Validation "
                "for Drugs and Biologics (July 2015)",
        "url": "https://www.fda.gov/media/87801/download",
        "filename": "fda-analytical-procedures-methods-validation.pdf",
        "instruments": ["FDA methods validation guidance"],
    },
}

TOPICS = [
    {
        "id": "document-control",
        "title": "Document control",
        "procedure_name": "Document Control",
        "sop_title": "Document Control",
        "purpose": (
            "Establish how quality-system documents are drafted, reviewed, "
            "approved, issued, revised, and retired, so that only current, "
            "approved documents are in use."
        ),
        "roles": [
            "Document Author", "Document Owner", "Approvers",
            "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "EU GMP Chapter 4 (documentation) and Chapter 1, and ICH Q10: "
                "the document lifecycle requirements the packet drafts from.",
                "United States requirements: 21 CFR Part 211 records and "
                "document provisions, and 21 CFR 820.40 document controls "
                "for device operations.",
            ],
        },
        "scope_in": (
            "Applies to the creation, approval, distribution, revision, and "
            "retirement of controlled documents at a {archetype} organization "
            "marketing products in {market}, in the following functions: "
            "{functions}."
        ),
        "scope_out": (
            "Does not cover records retention schedules for specific record "
            "types, which are set in the procedures that create those records."
        ),
        "intended_user": (
            "Document authors, reviewers, and approvers in every function, "
            "and the quality unit that administers the document system"
        ),
        "keywords": [
            "document control", "controlled document", "document management",
            "sop management", "document approval", "version control",
            "records management",
        ],
        "source_ids": ["eu-gmp-ch4", "eu-gmp-ch1", "cfr-part-211",
                       "cfr-part-820", "ich-q10"],
    },
    {
        "id": "good-documentation-practices",
        "title": "Good documentation practices",
        "procedure_name": "Good Documentation Practices",
        "sop_title": "Good Documentation Practices",
        "purpose": (
            "Establish the requirements for creating, completing, "
            "correcting, and retaining GMP records and documents so "
            "that records are attributable, legible, contemporaneous, "
            "original, and accurate."
        ),
        "principles": [
            "Records are attributable, legible, contemporaneous, "
            "original, and accurate, and remain complete, consistent, "
            "enduring, and available over their retention life "
            "(ALCOA+).",
            "An error in a record is corrected by a single "
            "line-through that leaves the original entry legible; "
            "the correction is initialled and dated by the person "
            "making it, and the reason is recorded where it is not "
            "obvious.",
            "No entry is obliterated: correction fluid, overwriting, "
            "and removal of pages or entries are prohibited.",
            "Records are made at the time the activity is performed, "
            "not reconstructed afterwards.",
            "A signature or initial on a record carries a defined "
            "meaning - performed, checked, or approved - and the "
            "signer is accountable for that meaning.",
        ],
        "roles": [
            "Record Author", "Record Reviewer", "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "EU GMP Chapter 4 (documentation): the good "
                "documentation practice requirements for generating, "
                "completing, and retaining records and documents.",
                "ICH Q10: documentation and record-keeping within "
                "the pharmaceutical quality system.",
                "United States requirements: the 21 CFR Part 211 "
                "records provisions (production, control, and "
                "laboratory records, and retention under 211.180) "
                "and 21 CFR Part 11 for electronic records and "
                "signatures.",
            ],
            "always": [
                "FDA's 2018 data integrity guidance (Data Integrity "
                "and Compliance With Drug CGMP: Questions and "
                "Answers) is not in this packet; "
                "documentation-practice coverage rests on the Part "
                "211 records provisions and Part 11 for the United "
                "States, EU GMP Chapter 4, and ICH Q10 for "
                "documentation within the pharmaceutical quality "
                "system.",
            ],
        },
        "scope_in": (
            "Applies to the creation, completion, correction, "
            "review, and retention of GMP records and documents, on "
            "paper and in electronic systems, at a {archetype} "
            "organization marketing products in {market}, in the "
            "following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover the approval and version control of "
            "documents themselves, which follows the document "
            "control procedure, or the content required in a "
            "specific record, which is set in the procedure that "
            "creates it."
        ),
        "intended_user": (
            "Personnel who create, complete, review, or approve GMP "
            "records, and the quality unit"
        ),
        "keywords": [
            "good documentation practices", "good documentation practice",
            "documentation practices", "documentation practice",
            "record keeping", "alcoa",
        ],
        "source_ids": ["eu-gmp-ch4", "cfr-part-211", "cfr-part-11",
                       "ich-q10"],
    },
    {
        "id": "change-control",
        "title": "Change control",
        "procedure_name": "Change Control",
        "sop_title": "Change Control",
        "purpose": (
            "Establish how changes to processes, systems, equipment, "
            "materials, and documents are proposed, assessed, approved, "
            "implemented, and verified, so that no change is made without "
            "evaluation of its impact on product quality."
        ),
        "principles": [
            "Every change is assessed for its impact on product quality, "
            "patient safety, and the validated state before it is approved, "
            "with the depth of assessment proportionate to the risk.",
            "Changes to established conditions in a marketing authorization "
            "are distinguished from changes managed inside the quality "
            "system, and each follows its own approval and reporting route.",
        ],
        "roles": [
            "Requester", "Change Owner", "Quality Assurance", "Approvers",
        ],
        "coverage": {
            "covers": [
                "ICH Q10 change management and ICH Q12 lifecycle tools "
                "(established conditions, post-approval change management "
                "protocols), which apply in the US, the EU, and the other "
                "ICH regions.",
                "United States requirements: 21 CFR 211.100 (written "
                "procedures and change review) and the Part 820 change "
                "provisions for device operations; EU coverage through "
                "ICH Q10/Q12 as adopted in the EU.",
            ],
        },
        "scope_in": (
            "Applies to all changes affecting validated processes, qualified "
            "equipment, approved materials, specifications, and controlled "
            "documents at a {archetype} organization marketing products in "
            "{market}, in the following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover emergency changes made to protect patients or "
            "product during an ongoing event, which follow the deviation "
            "procedure and are assessed retrospectively."
        ),
        "intended_user": (
            "Change originators and assessors in every function, and the "
            "quality unit that approves changes"
        ),
        "keywords": [
            "change control", "change", "change management", "change request",
            "post-approval change", "established conditions", "pacmp",
            "lifecycle management",
        ],
        "source_ids": ["ich-q12", "ich-q10", "ich-q9-r1", "cfr-part-211",
                       "cfr-part-820"],
    },
    {
        "id": "deviation",
        "title": "Deviation and nonconformance management",
        "procedure_name": "Deviation and Nonconformance Management",
        "sop_title": "Deviation and Nonconformance Management",
        "purpose": (
            "Establish how departures from approved procedures, "
            "specifications, and established conditions are recorded, "
            "investigated, assessed for impact, and dispositioned."
        ),
        "principles": [
            "A deviation is recorded when it is found, not reconstructed "
            "later: the record states what happened, when, and what was "
            "affected, before any investigation conclusion is drawn.",
            "The depth of investigation is proportionate to the potential "
            "impact on product quality and patient safety, and the "
            "disposition of affected product is a quality-unit decision.",
        ],
        "roles": [
            "Initiator", "Investigator", "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "EU GMP Chapter 1 deviation and quality-defect handling, and "
                "ICH Q10's process performance and product quality monitoring "
                "system.",
                "United States requirements: 21 CFR 211.192 (investigation of "
                "unexplained discrepancies) and 211.204.",
            ],
        },
        "scope_in": (
            "Applies to every departure from an approved procedure, "
            "specification, or established condition found at a {archetype} "
            "organization marketing products in {market}, in the following "
            "functions: {functions}."
        ),
        "scope_out": (
            "Does not cover laboratory results that fail specification, "
            "which follow the out-of-specification investigation procedure, "
            "or customer complaints, which follow the complaint procedure."
        ),
        "intended_user": (
            "Personnel who find and record deviations, investigators, and "
            "the quality unit that dispositions affected product"
        ),
        "keywords": [
            "deviation", "nonconformance", "non-conformance", "investigation",
            "unexplained discrepancy", "quality defect", "incident",
        ],
        "source_ids": ["ich-q10", "eu-gmp-ch1", "cfr-part-211", "ich-q9-r1"],
    },
    {
        "id": "capa",
        "title": "Corrective and preventive action (CAPA)",
        "procedure_name": "Corrective and Preventive Action (CAPA)",
        "sop_title": "Corrective and Preventive Action (CAPA)",
        "purpose": (
            "Establish how the causes of nonconformities and quality "
            "problems are identified and eliminated, and how the "
            "effectiveness of the actions taken is verified."
        ),
        "principles": [
            "A corrective action addresses the cause of a problem that has "
            "occurred; a preventive action addresses the cause of a problem "
            "that could occur. Fixing the instance is neither.",
            "Every CAPA closes with an effectiveness check defined when the "
            "action is planned, not invented when the action is done.",
        ],
        "roles": [
            "Initiator", "CAPA Owner", "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "ICH Q10's CAPA system element and EU GMP Chapter 1, which "
                "apply in the US, the EU, and the other ICH regions.",
                "United States requirements: 21 CFR 820.100 (corrective and "
                "preventive action) for device operations, and 21 CFR Part "
                "211 investigation provisions for drug operations.",
            ],
        },
        "scope_in": (
            "Applies to corrective and preventive actions arising from "
            "deviations, complaints, audit findings, and quality trends at "
            "a {archetype} organization marketing products in {market}, in "
            "the following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover the investigations that feed it, which follow "
            "the deviation and complaint procedures."
        ),
        "intended_user": (
            "CAPA owners in every function, and the quality unit that "
            "oversees the CAPA system"
        ),
        "keywords": [
            "capa", "corrective action", "preventive action", "root cause",
            "effectiveness check", "corrective and preventive",
        ],
        "source_ids": ["ich-q10", "eu-gmp-ch1", "cfr-part-820", "cfr-part-211",
                       "ich-q9-r1"],
    },
    {
        "id": "training",
        "title": "Training and qualification",
        "procedure_name": "Training and Qualification",
        "sop_title": "Training and Qualification of Personnel",
        "purpose": (
            "Establish how personnel are trained and qualified for the "
            "tasks they perform, and how training is recorded and kept "
            "current."
        ),
        "principles": [
            "No one performs a task affecting product quality before they "
            "are trained and qualified for it; the training record, not the "
            "assignment, is the evidence.",
            "A document revision triggers an assessment of who must be "
            "retrained on what changed, proportionate to the change.",
        ],
        "roles": [
            "Trainee", "Trainer", "Supervisor",
        ],
        "coverage": {
            "covers": [
                "EU GMP Chapter 2 (personnel, training, and hygiene) and "
                "Chapter 1, and ICH Q10's knowledge management enabler.",
                "United States requirements: 21 CFR 211.25 (personnel "
                "qualifications) and 211.34.",
            ],
        },
        "scope_in": (
            "Applies to the training and qualification of all personnel "
            "whose work affects product quality at a {archetype} "
            "organization marketing products in {market}, in the following "
            "functions: {functions}."
        ),
        "scope_out": (
            "Does not cover professional licensing or continuing education "
            "outside the quality system."
        ),
        "intended_user": (
            "All personnel, their supervisors, and the quality unit that "
            "oversees training compliance"
        ),
        "keywords": [
            "training", "qualification", "competency", "curriculum",
            "training record", "personnel qualification", "onboarding",
        ],
        "source_ids": ["eu-gmp-ch2", "ich-q10", "cfr-part-211", "eu-gmp-ch1"],
    },
    {
        "id": "internal-audit",
        "title": "Internal audit (self-inspection)",
        "procedure_name": "Internal Audit (Self-Inspection)",
        "sop_title": "Internal Audit and Self-Inspection",
        "purpose": (
            "Establish how the organization's compliance with its own "
            "procedures and with GMP is audited internally, and how "
            "findings are recorded, answered, and closed."
        ),
        "roles": [
            "Lead Auditor", "Auditor", "Auditee", "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "EU GMP Chapter 9 (self inspection) and Chapter 1, and ICH "
                "Q10's monitoring and management review elements.",
            ],
            "markets": {
                "us": (
                    "US market selected: self-inspection is an EU GMP "
                    "Chapter 9 requirement, and the packet contains no US "
                    "regulation text on internal audits. US coverage in "
                    "this draft rests on ICH Q10's monitoring elements."
                ),
            },
        },
        "scope_in": (
            "Applies to planned and for-cause internal audits of every "
            "function at a {archetype} organization marketing products in "
            "{market}, in the following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover audits of suppliers and contractors, which "
            "follow the supplier quality procedure, or regulatory "
            "inspections by authorities."
        ),
        "intended_user": (
            "Internal auditors, audited functions, and the quality unit"
        ),
        "keywords": [
            "internal audit", "self-inspection", "self inspection", "audit",
            "audit programme", "audit schedule",
        ],
        "source_ids": ["eu-gmp-ch9", "ich-q10", "eu-gmp-ch1"],
    },
    {
        "id": "management-review",
        "title": "Management review",
        "procedure_name": "Management Review",
        "sop_title": "Management Review of the Quality System",
        "purpose": (
            "Establish how senior management reviews the performance of "
            "the quality system at planned intervals and directs its "
            "improvement."
        ),
        "roles": [
            "Senior Management", "Management Representative",
            "Quality Assurance", "Process Owners",
        ],
        "coverage": {
            "covers": [
                "ICH Q10 management review and EU GMP Chapter 1, which "
                "apply in the US, the EU, and the other ICH regions.",
                "United States requirements for device operations: 21 CFR "
                "820.20 (management responsibility and quality system "
                "review).",
            ],
        },
        "scope_in": (
            "Applies to the periodic review of quality-system performance "
            "at a {archetype} organization marketing products in {market}, "
            "in the following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover product-specific quality reviews, which follow "
            "the annual product quality review procedure."
        ),
        "intended_user": (
            "Senior management and the quality unit"
        ),
        "keywords": [
            "management review", "quality system review", "quality system",
            "management responsibility", "quality metrics review",
        ],
        "source_ids": ["ich-q10", "eu-gmp-ch1", "cfr-part-820"],
    },
    {
        "id": "quality-risk-management",
        "title": "Quality risk management",
        "procedure_name": "Quality Risk Management",
        "sop_title": "Quality Risk Management",
        "purpose": (
            "Establish how risks to product quality are identified, "
            "assessed, controlled, communicated, and reviewed across the "
            "product lifecycle."
        ),
        "principles": [
            "The effort, formality, and documentation of a risk assessment "
            "are proportionate to the level of risk: the same template is "
            "not the answer to every question.",
            "Risk decisions are based on the available science and data, "
            "and the residual risk after control is stated, not implied.",
        ],
        "roles": [
            "Risk Assessment Lead", "Subject Matter Expert", "Risk Owner",
            "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "ICH Q9(R1) quality risk management and ICH Q10's risk "
                "management enabler, adopted in the US, the EU, and the "
                "other ICH regions; EU GMP Chapter 1 states the EU "
                "expectation.",
            ],
        },
        "scope_in": (
            "Applies to quality risk assessments performed at a {archetype} "
            "organization marketing products in {market}, in the following "
            "functions: {functions}."
        ),
        "scope_out": (
            "Does not cover occupational safety risk assessments or "
            "business and financial risk management."
        ),
        "intended_user": (
            "Risk assessment teams in every function, and the quality unit"
        ),
        "keywords": [
            "risk management", "risk assessment", "quality risk", "fmea",
            "hazard", "risk evaluation", "ich q9",
        ],
        "source_ids": ["ich-q9-r1", "ich-q10", "eu-gmp-ch1"],
    },
    {
        "id": "supplier-quality",
        "title": "Supplier quality and supplier audits",
        "procedure_name": "Supplier Quality and Supplier Audits",
        "sop_title": "Supplier Qualification, Audits, and Quality Agreements",
        "purpose": (
            "Establish how suppliers of materials, components, and "
            "services are selected, qualified, audited, and monitored, "
            "and how quality responsibilities are agreed with them."
        ),
        "principles": [
            "Responsibility for the quality of a purchased material or an "
            "outsourced activity is never outsourced with it: the "
            "organization remains accountable for what its suppliers do.",
            "The depth of qualification and audit is proportionate to the "
            "risk the material or service poses to product quality.",
        ],
        "roles": [
            "Purchasing", "Supplier Quality Auditor", "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "EU GMP Chapter 7 (outsourced activities) and Chapter 5 "
                "(starting materials and supplier approval), and ICH Q10.",
                "Active-substance supply: ICH Q7 GMP for APIs. United States "
                "requirements: 21 CFR 211.84 (component testing and "
                "approval) and related Part 211 provisions.",
            ],
        },
        "scope_in": (
            "Applies to the qualification, auditing, and monitoring of "
            "suppliers and contractors whose materials or services affect "
            "product quality at a {archetype} organization marketing "
            "products in {market}, in the following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover purchasing of indirect goods and services that "
            "cannot affect product quality."
        ),
        "intended_user": (
            "Supplier quality personnel, procurement, and the quality unit"
        ),
        "keywords": [
            "supplier", "vendor qualification", "supplier audit",
            "quality agreement", "outsourced", "contractor", "approved "
            "supplier",
        ],
        "source_ids": ["eu-gmp-ch7", "eu-gmp-ch5", "ich-q7", "ich-q10",
                       "cfr-part-211"],
    },
    {
        "id": "complaint-handling",
        "title": "Complaint handling",
        "procedure_name": "Complaint Handling",
        "sop_title": "Complaint Handling and Investigation",
        "purpose": (
            "Establish how complaints about a product are recorded, "
            "reviewed, investigated, and answered, and how they are "
            "assessed for escalation to recall or regulatory reporting."
        ),
        "roles": [
            "Complaint Intake", "Investigator", "Quality Assurance",
            "Regulatory Affairs",
        ],
        "coverage": {
            "covers": [
                "EU GMP Chapter 8 (complaints and quality defects) and ICH "
                "Q10's monitoring system.",
                "United States requirements: 21 CFR 211.198 (complaint "
                "files) for drugs and 21 CFR 820.198 (complaint files) for "
                "device operations.",
            ],
        },
        "scope_in": (
            "Applies to every complaint received about a marketed product "
            "of a {archetype} organization marketing products in {market}, "
            "in the following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover adverse-event intake and reporting for "
            "pharmacovigilance, which follows its own procedures, or "
            "commercial complaints with no quality content."
        ),
        "intended_user": (
            "Complaint handlers, investigators, and the quality unit"
        ),
        "keywords": [
            "complaint", "complaint handling", "complaint investigation",
            "customer complaint", "product complaint", "quality defect",
        ],
        "source_ids": ["eu-gmp-ch8", "cfr-part-211", "cfr-part-820", "ich-q10"],
    },
    {
        "id": "product-recall",
        "title": "Product recall",
        "procedure_name": "Product Recall",
        "sop_title": "Product Recall",
        "purpose": (
            "Establish how a decision to recall product from the market "
            "is made, executed, reconciled, and reported, and how recall "
            "readiness is maintained and tested."
        ),
        "principles": [
            "A recall decision is made on the risk to patients, not on the "
            "commercial cost: the quality unit can initiate a recall "
            "without commercial approval.",
            "Recall effectiveness is proven by reconciliation: quantities "
            "distributed, returned, and accounted for must agree.",
        ],
        "roles": [
            "Recall Coordinator", "Quality Assurance", "Regulatory Affairs",
            "Executive Management",
        ],
        "coverage": {
            "covers": [
                "EU GMP Chapter 8 (complaints, quality defects, and product "
                "recalls) and ICH Q10.",
                "United States requirements: 21 CFR Part 7 Subpart C "
                "(recalls, including voluntary firm-initiated recalls) and "
                "Part 211 distribution and complaint provisions.",
            ],
        },
        "scope_in": (
            "Applies to the recall of any distributed product of a "
            "{archetype} organization marketing products in {market}, in "
            "the following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover market withdrawals of product for purely "
            "commercial reasons with no quality defect."
        ),
        "intended_user": (
            "The recall team, distribution and regulatory functions, and "
            "the quality unit"
        ),
        "keywords": [
            "recall", "product recall", "market withdrawal", "mock recall",
            "recall reconciliation", "field action",
        ],
        "source_ids": ["eu-gmp-ch8", "cfr-part-7", "cfr-part-211", "ich-q10"],
    },
    {
        "id": "process-validation",
        "title": "Process validation",
        "procedure_name": "Process Validation",
        "sop_title": "Process Validation",
        "purpose": (
            "Establish how manufacturing processes are designed, "
            "qualified, and monitored so that they consistently produce "
            "product meeting its specifications."
        ),
        "principles": [
            "Validation follows the product lifecycle: process design, "
            "process qualification, and continued process verification. "
            "Qualification batches are the middle of the evidence, not "
            "the whole of it.",
            "The number of qualification batches and the sampling within "
            "them are justified by the process's variability and risk, "
            "not by convention alone.",
        ],
        "roles": [
            "Validation Engineer", "Process Owner", "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "EU GMP Annex 15 (qualification and validation) and ICH "
                "Q8(R2) process design, with ICH Q10's lifecycle framing.",
                "United States requirements: 21 CFR 211.100 and 211.110 "
                "(in-process controls and validation of processes).",
            ],
            "always": [
                "FDA's 2011 process validation guidance, which sets out "
                "the US stage 1-3 lifecycle in detail, is not in this "
                "packet; US coverage rests on the Part 211 text and the "
                "ICH and EU sources.",
            ],
        },
        "scope_in": (
            "Applies to the validation and continued verification of "
            "manufacturing processes at a {archetype} organization "
            "marketing products in {market}, in the following functions: "
            "{functions}."
        ),
        "scope_out": (
            "Does not cover cleaning validation, analytical procedure "
            "validation, or computer system validation, which have their "
            "own procedures."
        ),
        "intended_user": (
            "Validation scientists and engineers, manufacturing, and the "
            "quality unit"
        ),
        "keywords": [
            "process validation", "validation", "qualification", "ppq",
            "continued process verification", "process qualification",
            "validation protocol",
        ],
        "source_ids": ["eu-gmp-annex15", "ich-q8-r2", "ich-q10",
                       "cfr-part-211"],
    },
    {
        "id": "cleaning-validation",
        "title": "Cleaning validation",
        "procedure_name": "Cleaning Validation",
        "sop_title": "Cleaning Validation",
        "purpose": (
            "Establish how cleaning processes for product-contact "
            "equipment are validated and verified, so that residues of "
            "the previous product, cleaning agents, and microorganisms "
            "are removed to scientifically justified limits."
        ),
        "principles": [
            "Carryover limits are health-based where the data allow: a "
            "permitted daily exposure derived from the previous product's "
            "toxicology, not a fraction of a dose carried by habit.",
            "The worst case is chosen and defended: the hardest-to-clean "
            "product, location, and condition stand for the group.",
        ],
        "roles": [
            "Validation Engineer", "Manufacturing Operator",
            "Laboratory Analyst", "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "EU GMP Annex 15 (cleaning validation) and Chapters 3 and "
                "5 (premises, cross-contamination), and the EMA guideline "
                "on health-based exposure limits (PDE derivation).",
                "United States requirements: 21 CFR 211.67 (equipment "
                "cleaning and maintenance) and 211.160.",
            ],
        },
        "scope_in": (
            "Applies to the validation of cleaning for shared and "
            "dedicated product-contact equipment at a {archetype} "
            "organization marketing products in {market}, in the "
            "following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover routine cleaning operations themselves, which "
            "follow equipment-specific cleaning procedures, or cleaning "
            "of non-product-contact surfaces."
        ),
        "intended_user": (
            "Validation scientists, manufacturing, and the quality unit"
        ),
        "keywords": [
            "cleaning validation", "cleaning", "carryover", "residue limit",
            "health-based exposure", "pde", "cross-contamination",
            "swab",
        ],
        "source_ids": ["eu-gmp-annex15", "ema-hbel", "eu-gmp-ch3",
                       "cfr-part-211", "ich-q9-r1"],
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
        "roles": [
            "Analyst", "Study Director / Protocol Owner",
            "Quality Assurance",
        ],
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
        "source_ids": ["ich-q2-r2", "ich-q14", "fda-methods-validation"],
    },
    {
        "id": "csv-data-integrity",
        "title": "Computer system validation and data integrity",
        "procedure_name": "Computer System Validation and Data Integrity",
        "sop_title": "Computer System Validation and Data Integrity",
        "purpose": (
            "Establish how computerized systems used in regulated "
            "activities are validated and controlled, and how the "
            "integrity of the data they create and hold is assured "
            "throughout its lifecycle."
        ),
        "principles": [
            "Records are attributable, legible, contemporaneous, "
            "original, and accurate (ALCOA) from creation to retirement, "
            "in whatever system holds them.",
            "Validation effort is proportionate to the system's impact "
            "on product quality and data integrity, and is based on the "
            "system's intended use, not on its size.",
        ],
        "roles": [
            "System Owner", "System Administrator", "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "EU GMP Annex 11 (computerised systems) and ICH Q10.",
                "United States requirements: 21 CFR Part 11 (electronic "
                "records and signatures) and 21 CFR 211.68 (automatic and "
                "electronic equipment controls).",
            ],
            "always": [
                "FDA's 2018 data integrity guidance (Data Integrity and "
                "Compliance With Drug CGMP: Questions and Answers) is "
                "not in this packet; US data-integrity coverage rests on "
                "the Part 11 and Part 211 text and Annex 11.",
            ],
        },
        "scope_in": (
            "Applies to computerized systems that create, process, or "
            "store regulated records at a {archetype} organization "
            "marketing products in {market}, in the following functions: "
            "{functions}."
        ),
        "scope_out": (
            "Does not cover business systems with no regulated records, "
            "or the validation of individual spreadsheets used outside "
            "regulated records."
        ),
        "intended_user": (
            "System owners, validation personnel, IT, and the quality unit"
        ),
        "keywords": [
            "computer system validation", "csv", "data integrity",
            "electronic records", "part 11", "annex 11", "computerised",
            "software validation", "audit trail",
        ],
        "source_ids": ["eu-gmp-annex11", "cfr-part-11", "cfr-part-211",
                       "ich-q10"],
    },
    {
        "id": "ai-use",
        "title": "Proper use of AI in a regulated environment",
        "procedure_name": "AI Use",
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
        "roles": [
            "Requester", "System Owner", "Quality Assurance",
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
        "source_ids": ["fda-ai-guidance", "nist-ai-rmf", "gmlp-principles",
                       "ich-q10", "ich-q9-r1"],
    },
    {
        "id": "calibration-maintenance",
        "title": "Calibration and preventive maintenance",
        "procedure_name": "Calibration and Preventive Maintenance",
        "sop_title": "Calibration and Preventive Maintenance",
        "purpose": (
            "Establish how equipment and instruments are calibrated, "
            "maintained, and qualified, so that they remain fit for "
            "their intended use and their status is known at all times."
        ),
        "roles": [
            "Calibration Technician", "Maintenance Technician",
            "Equipment Owner", "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "EU GMP Chapter 3 (premises and equipment) and Annex 15 "
                "(qualification), and ICH Q10.",
                "United States requirements: 21 CFR 211.68 (equipment "
                "calibration and maintenance) and 211.160.",
            ],
        },
        "scope_in": (
            "Applies to the calibration, preventive maintenance, and "
            "qualification of equipment and instruments used in regulated "
            "activities at a {archetype} organization marketing products "
            "in {market}, in the following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover corrective repair work orders, which follow "
            "the maintenance work-order process, or facility systems with "
            "no product contact or product impact."
        ),
        "intended_user": (
            "Engineering and maintenance personnel, equipment owners, and "
            "the quality unit"
        ),
        "keywords": [
            "calibration", "preventive maintenance", "maintenance",
            "instrument calibration", "equipment qualification",
            "out of tolerance", "metrology",
        ],
        "source_ids": ["eu-gmp-ch3", "eu-gmp-annex15", "cfr-part-211",
                       "ich-q10"],
    },
    {
        "id": "environmental-monitoring",
        "title": "Environmental monitoring",
        "procedure_name": "Environmental Monitoring",
        "sop_title": "Environmental Monitoring",
        "purpose": (
            "Establish how the microbial and particulate state of "
            "controlled environments is monitored, trended, and acted "
            "on, so that loss of environmental control is detected "
            "before it affects product."
        ),
        "principles": [
            "Monitoring results are trended, not filed: alert and action "
            "excursions are investigated for what they say about the "
            "state of control, including when product impact is none.",
        ],
        "roles": [
            "Microbiologist", "Microbiology Supervisor",
            "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "EU GMP Annex 1 (sterile manufacture: cleanroom "
                "classification, monitoring, and limits) and Chapter 3, "
                "and ICH Q10.",
                "United States requirements: 21 CFR 211.42 and 211.113 "
                "(control of microbiological contamination).",
            ],
            "always": [
                "The packet's detailed monitoring text is the sterile-"
                "manufacturing framework of EU GMP Annex 1. Non-sterile "
                "monitoring is covered only at the level of premises "
                "controls; FDA's aseptic processing guidance is not in "
                "this packet.",
            ],
        },
        "scope_in": (
            "Applies to environmental and personnel monitoring in "
            "classified and controlled areas at a {archetype} "
            "organization marketing products in {market}, in the "
            "following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover monitoring of utilities such as water and "
            "compressed gases, which follow their own procedures, or "
            "occupational exposure monitoring."
        ),
        "intended_user": (
            "Microbiology and environmental monitoring personnel, "
            "manufacturing, and the quality unit"
        ),
        "keywords": [
            "environmental monitoring", "cleanroom", "viable monitoring",
            "particulate", "microbial monitoring", "em programme",
            "contamination control",
        ],
        "source_ids": ["eu-gmp-annex1", "eu-gmp-ch3", "cfr-part-211",
                       "ich-q10"],
    },
    {
        "id": "stability-testing",
        "title": "Stability testing",
        "procedure_name": "Stability Testing",
        "sop_title": "Stability Testing Programme",
        "purpose": (
            "Establish how stability studies are designed, conducted, "
            "and evaluated to support shelf life, retest periods, and "
            "storage conditions for drug substances and products."
        ),
        "roles": [
            "Analyst", "Stability Coordinator", "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "ICH Q1A(R2) stability testing (storage conditions, "
                "testing frequency, evaluation), adopted in the US, the "
                "EU, and the other ICH regions.",
                "EU GMP Chapter 6 (quality control, ongoing stability) "
                "and United States requirements: 21 CFR 211.166 "
                "(stability testing) and 211.204.",
            ],
            "always": [
                "ICH Q5C, the stability guideline for biotechnological "
                "and biological products, is not in this packet; for "
                "biologics, this draft rests on Q1A(R2) principles and "
                "the Chapter 6 ongoing-stability requirements.",
            ],
        },
        "scope_in": (
            "Applies to registration, commitment, and ongoing stability "
            "studies at a {archetype} organization marketing products in "
            "{market}, in the following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover stability of clinical trial materials or "
            "in-use stability of multi-dose presentations after first "
            "opening, which are assessed per product."
        ),
        "intended_user": (
            "Stability scientists, the quality control laboratory, and "
            "the quality unit"
        ),
        "keywords": [
            "stability", "stability testing", "shelf life", "retest",
            "stability programme", "stability study", "ich q1a",
        ],
        "source_ids": ["ich-q1a-r2", "eu-gmp-ch6", "cfr-part-211", "ich-q10"],
    },
    {
        "id": "oos-investigation",
        "title": "Out-of-specification (OOS) investigation",
        "procedure_name": "Out-of-Specification (OOS) Investigation",
        "sop_title": "Out-of-Specification (OOS) Investigation",
        "purpose": (
            "Establish how out-of-specification and out-of-trend "
            "laboratory results are investigated, so that a result is "
            "invalidated only for a documented, scientifically sound "
            "cause and valid results are acted on."
        ),
        "principles": [
            "A result stands unless the investigation assigns it a "
            "documented, scientifically sound laboratory cause: results "
            "are never averaged, retested, or sampled into compliance.",
            "The laboratory phase comes first and is time-bound: the "
            "analyst's work is examined before any full-scale "
            "investigation of the batch is opened.",
        ],
        "roles": [
            "Analyst", "Laboratory Supervisor", "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "EU GMP Chapter 6 (quality control: OOS handling, "
                "retesting, and resampling rules) and ICH Q10.",
                "United States requirements: 21 CFR 211.192 "
                "(investigation of discrepancies) and 211.160/211.165.",
            ],
            "always": [
                "FDA's guidance on investigating out-of-specification "
                "test results, which sets out the US two-phase "
                "investigation in detail, is not in this packet; US "
                "coverage rests on the Part 211 text and Chapter 6.",
            ],
        },
        "scope_in": (
            "Applies to every out-of-specification and out-of-trend "
            "result generated by the quality control laboratory at a "
            "{archetype} organization marketing products in {market}, in "
            "the following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover out-of-specification results on stability "
            "studies' alert limits before a specification failure, or "
            "microbiological excursions in environmental monitoring, "
            "which follow their own procedures."
        ),
        "intended_user": (
            "Laboratory analysts and supervisors, investigators, and the "
            "quality unit"
        ),
        "keywords": [
            "out-of-specification", "out of specification", "out of spec",
            "specification result", "oos", "out-of-trend", "oot",
            "laboratory investigation", "invalidated result", "retesting",
        ],
        "source_ids": ["eu-gmp-ch6", "cfr-part-211", "ich-q10"],
    },
    {
        "id": "batch-release",
        "title": "Batch record review and product release",
        "procedure_name": "Batch Record Review and Product Release",
        "sop_title": "Batch Record Review and Product Release",
        "purpose": (
            "Establish how batch records and associated quality data are "
            "reviewed and how the decision to release, reject, or hold a "
            "batch is made and recorded."
        ),
        "principles": [
            "Release is a decision on the whole record, not the last "
            "test result: unresolved deviations, investigations, and "
            "changes affecting the batch are closed or explicitly "
            "dispositioned before release.",
        ],
        "roles": [
            "Batch Record Reviewer", "Manufacturing Supervisor",
            "Quality Assurance", "Authorized Person",
        ],
        "coverage": {
            "covers": [
                "EU GMP Annex 16 (certification by a Qualified Person and "
                "batch release) with Chapters 4 and 6, and ICH Q10.",
                "United States requirements: 21 CFR 211.192 and 211.204 "
                "(production record review and release).",
            ],
            "archetypes": {
                "cell-therapy": (
                    "Cell therapy selected: Annex 16's Qualified Person "
                    "certification is an EU construct, and the ATMP GMP "
                    "Part IV release rules for advanced therapies are "
                    "not in this packet."
                ),
                "gene-therapy": (
                    "Gene therapy selected: Annex 16's Qualified Person "
                    "certification is an EU construct, and the ATMP GMP "
                    "Part IV release rules for advanced therapies are "
                    "not in this packet."
                ),
                "device": (
                    "Medical device selected: device release is device "
                    "history record review under 21 CFR 820.184, which "
                    "is not in this packet - see the Device History "
                    "Records procedure."
                ),
                "ivd": (
                    "In vitro diagnostics selected: device release is "
                    "device history record review under 21 CFR 820.184, "
                    "which is not in this packet - see the Device "
                    "History Records procedure."
                ),
            },
        },
        "scope_in": (
            "Applies to the review of batch production and control "
            "records and the release decision for every batch at a "
            "{archetype} organization marketing products in {market}, in "
            "the following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover release of starting materials and components "
            "for use in production, which follows the supplier and "
            "materials procedures."
        ),
        "intended_user": (
            "Batch record reviewers, the Qualified Person or authorized "
            "releaser, and the quality unit"
        ),
        "keywords": [
            "batch release", "batch record review", "product release",
            "qualified person", "qp certification", "disposition",
            "release decision",
        ],
        "source_ids": ["eu-gmp-annex16", "eu-gmp-ch4", "eu-gmp-ch6",
                       "cfr-part-211", "ich-q10"],
    },
    {
        "id": "apqr",
        "title": "Annual product quality review",
        "procedure_name": "Annual Product Quality Review",
        "sop_title": "Annual Product Quality Review",
        "purpose": (
            "Establish how the quality of each product is reviewed at "
            "least annually, so that trends, recurring problems, and the "
            "need for change are identified from the year's data."
        ),
        "roles": [
            "Report Author", "Process Owners", "Quality Assurance",
            "Senior Management",
        ],
        "coverage": {
            "covers": [
                "EU GMP Chapter 1 (product quality review) and ICH Q10's "
                "monitoring and management review elements.",
                "United States requirements: 21 CFR 211.180(e) (annual "
                "review of records and quality standards).",
            ],
        },
        "scope_in": (
            "Applies to the periodic quality review of every marketed "
            "product of a {archetype} organization marketing products in "
            "{market}, in the following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover management review of the quality system as "
            "a whole, which has its own procedure."
        ),
        "intended_user": (
            "Product quality reviewers, manufacturing and laboratory "
            "functions, and the quality unit"
        ),
        "keywords": [
            "annual product quality review", "apqr", "pqr",
            "product quality review", "annual review", "quality review",
        ],
        "source_ids": ["eu-gmp-ch1", "ich-q10", "cfr-part-211", "ich-q9-r1"],
    },
    {
        "id": "labeling-packaging",
        "title": "Labeling and packaging control",
        "procedure_name": "Labeling and Packaging Control",
        "sop_title": "Labeling and Packaging Control",
        "purpose": (
            "Establish how labeling and packaging materials are "
            "controlled, issued, reconciled, and verified, so that the "
            "right label is on the right product and no mix-up can pass "
            "undetected."
        ),
        "principles": [
            "Labels are counted, not trusted: issuance, use, and "
            "destruction of printed labeling are reconciled for every "
            "batch, and a discrepancy stops the line.",
        ],
        "roles": [
            "Packaging Operator", "Packaging Supervisor", "Label Reviewer",
            "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "EU GMP Chapter 5 (production: packaging operations and "
                "printed materials) and Chapter 4, and ICH Q10.",
                "United States requirements: 21 CFR Part 211 Subpart G "
                "(packaging and labeling control, 211.122-211.137).",
            ],
            "archetypes": {
                "device": (
                    "Medical device selected: device labeling and UDI "
                    "obligations (21 CFR 820.120 and Part 830) are not "
                    "in this packet - see the UDI and Labeling Control "
                    "procedure."
                ),
                "ivd": (
                    "In vitro diagnostics selected: device labeling and "
                    "UDI obligations (21 CFR 820.120 and Part 830) are "
                    "not in this packet - see the UDI and Labeling "
                    "Control procedure."
                ),
            },
        },
        "scope_in": (
            "Applies to the receipt, storage, issuance, application, and "
            "reconciliation of labels and packaging materials at a "
            "{archetype} organization marketing products in {market}, in "
            "the following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover artwork design and regulatory approval of "
            "label content, which follows the regulatory labeling "
            "procedures."
        ),
        "intended_user": (
            "Packaging operations, labeling control personnel, and the "
            "quality unit"
        ),
        "keywords": [
            "labeling", "labelling", "packaging control", "label "
            "reconciliation", "packaging", "printed materials", "mix-up",
        ],
        "source_ids": ["eu-gmp-ch5", "cfr-part-211", "eu-gmp-ch4"],
    },
    {
        "id": "warehouse-distribution",
        "title": "Warehouse and distribution control",
        "procedure_name": "Warehouse and Distribution Control",
        "sop_title": "Warehouse and Distribution Control",
        "purpose": (
            "Establish how materials and finished products are received, "
            "stored, picked, and distributed under controlled "
            "conditions, so that identity, status, and storage "
            "conditions are maintained through the supply chain."
        ),
        "roles": [
            "Warehouse Operator", "Warehouse Supervisor",
            "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "EU Good Distribution Practice guidelines (2013/C "
                "343/01) and EU GMP Chapter 3 (storage areas), and ICH "
                "Q10.",
                "United States requirements: 21 CFR 211.150 (distribution "
                "procedures) and 211.204 (returned product).",
            ],
            "always": [
                "The US Drug Supply Chain Security Act (DSCSA) product "
                "tracing requirements are not in this packet.",
            ],
        },
        "scope_in": (
            "Applies to warehousing and distribution operations for "
            "materials and finished products at a {archetype} "
            "organization marketing products in {market}, in the "
            "following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover transport qualification of specific shipping "
            "lanes, which is assessed per lane, or direct-to-patient "
            "distribution models."
        ),
        "intended_user": (
            "Warehouse and distribution personnel, supply chain, and the "
            "quality unit"
        ),
        "keywords": [
            "warehouse", "distribution", "storage", "goods receipt",
            "gdp", "good distribution practice", "shipping", "inventory "
            "control",
        ],
        "source_ids": ["eu-gdp", "eu-gmp-ch3", "cfr-part-211", "ich-q10"],
    },
    {
        "id": "containment",
        "title": "Containment and cross-contamination control",
        "procedure_name": "Containment and Cross-Contamination Control",
        "sop_title": "Containment and Cross-Contamination Control",
        "purpose": (
            "Establish how cross-contamination between products and "
            "materials is prevented and controlled in shared facilities, "
            "using technical and organizational measures proportionate "
            "to the risk."
        ),
        "roles": [
            "Manufacturing Operator", "Area Supervisor",
            "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "EU GMP Chapters 3 and 5 (premises design and "
                "cross-contamination prevention) and the EMA "
                "health-based exposure limit guideline.",
                "United States requirements: 21 CFR 211.42 and 211.100 "
                "(facility separation and contamination precautions).",
            ],
        },
        "scope_in": (
            "Applies to the design and operation of shared manufacturing "
            "areas and campaigns at a {archetype} organization marketing "
            "products in {market}, in the following functions: "
            "{functions}."
        ),
        "scope_out": (
            "Does not cover cleaning validation itself, which has its "
            "own procedure, or occupational exposure controls for "
            "personnel safety."
        ),
        "intended_user": (
            "Manufacturing, engineering, and the quality unit"
        ),
        "keywords": [
            "containment", "cross-contamination", "cross contamination",
            "dedicated facility", "campaign", "shared facility",
            "segregation",
        ],
        "source_ids": ["eu-gmp-ch3", "eu-gmp-ch5", "ema-hbel", "ich-q9-r1",
                       "cfr-part-211"],
    },
    {
        "id": "aseptic-processing",
        "title": "Aseptic processing and media fills",
        "procedure_name": "Aseptic Processing and Media Fills",
        "sop_title": "Aseptic Processing and Media Fills",
        "purpose": (
            "Establish how aseptic operations are designed, performed, "
            "and monitored, including aseptic process simulations "
            "(media fills), so that sterile product is protected from "
            "contamination at every step."
        ),
        "principles": [
            "Sterility is built by the process, never tested in: the "
            "contamination control strategy governs design, behavior, "
            "and monitoring as one system.",
            "A media fill represents the process at its worst credible "
            "case: routine interventions, maximum personnel, and maximum "
            "duration are in the simulation, not edited out of it.",
        ],
        "roles": [
            "Aseptic Operator", "Manufacturing Supervisor",
            "Microbiologist", "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "EU GMP Annex 1 (manufacture of sterile medicinal "
                "products: contamination control strategy, aseptic "
                "process simulation) and Annex 2, and ICH Q10.",
                "United States requirements: 21 CFR 211.113 (control of "
                "microbiological contamination) and related Part 211 "
                "provisions.",
            ],
            "always": [
                "FDA's 2004 guidance on sterile drug products produced "
                "by aseptic processing is not in this packet; US "
                "coverage rests on the Part 211 text and Annex 1.",
            ],
        },
        "scope_in": (
            "Applies to aseptic processing, sterile filtration, and "
            "media fills at a {archetype} organization marketing "
            "products in {market}, in the following functions: "
            "{functions}."
        ),
        "scope_out": (
            "Does not cover terminal sterilization processes, which are "
            "validated under the process validation procedure, or "
            "sterility testing itself."
        ),
        "intended_user": (
            "Aseptic operations personnel, microbiology, and the quality "
            "unit"
        ),
        "keywords": [
            "aseptic", "media fill", "sterile", "aseptic process "
            "simulation", "contamination control strategy", "ccs",
            "sterile manufacturing", "grade a",
        ],
        "source_ids": ["eu-gmp-annex1", "eu-gmp-annex2", "cfr-part-211",
                       "ich-q10"],
    },
    {
        "id": "cell-bank-management",
        "title": "Cell bank management",
        "procedure_name": "Cell Bank Management",
        "sop_title": "Cell Bank Management",
        "purpose": (
            "Establish how master and working cell banks are created, "
            "characterized, stored, and issued, so that production "
            "always starts from a qualified, traceable cell substrate."
        ),
        "roles": [
            "Cell Bank Operator", "Laboratory Supervisor",
            "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "ICH Q5D (derivation and characterization of cell "
                "substrates) and ICH Q5A(R2) (viral safety of cell "
                "lines), and EU GMP Annex 2.",
                "United States requirements: 21 CFR Part 610 (general "
                "biological product standards, including cell bank "
                "testing) and Part 600.",
            ],
        },
        "scope_in": (
            "Applies to cell banks used in the manufacture of products "
            "at a {archetype} organization marketing products in "
            "{market}, in the following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover cell line development and clone selection "
            "research before banking."
        ),
        "intended_user": (
            "Cell banking personnel, quality control, and the quality "
            "unit"
        ),
        "keywords": [
            "cell bank", "master cell bank", "working cell bank", "mcb",
            "wcb", "cell substrate", "cell line characterization",
            "banking",
        ],
        "source_ids": ["ich-q5d", "ich-q5a-r2", "eu-gmp-annex2",
                       "cfr-part-610", "ich-q10"],
    },
    {
        "id": "viral-clearance",
        "title": "Viral clearance",
        "procedure_name": "Viral Clearance",
        "sop_title": "Viral Clearance Studies and Controls",
        "purpose": (
            "Establish how the capacity of the manufacturing process to "
            "remove and inactivate viruses is evaluated, validated, and "
            "maintained, as one part of the overall viral safety "
            "strategy."
        ),
        "principles": [
            "Viral safety rests on three complementary legs: controlled "
            "starting materials, testing at defined stages, and "
            "validated clearance. No leg substitutes for another.",
        ],
        "roles": [
            "Study Director", "Laboratory Scientist", "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "ICH Q5A(R2) (viral safety evaluation: clearance study "
                "design, log-reduction claims, revalidation triggers) "
                "and ICH Q5D, and EU GMP Annex 2.",
                "Risk assessment method: ICH Q9(R1).",
            ],
        },
        "scope_in": (
            "Applies to viral clearance studies and their maintenance "
            "for products manufactured at a {archetype} organization "
            "marketing products in {market}, in the following functions: "
            "{functions}."
        ),
        "scope_out": (
            "Does not cover adventitious-agent testing of banks and "
            "harvests itself, which follows the testing procedures, or "
            "raw material viral safety qualification."
        ),
        "intended_user": (
            "Process development and validation scientists, quality "
            "control, and the quality unit"
        ),
        "keywords": [
            "viral clearance", "virus clearance", "viral safety",
            "log reduction", "adventitious", "viral inactivation",
            "ich q5a",
        ],
        "source_ids": ["ich-q5a-r2", "ich-q5d", "eu-gmp-annex2", "ich-q9-r1"],
    },
    {
        "id": "chain-of-identity",
        "title": "Chain of identity and chain of custody",
        "procedure_name": "Chain of Identity and Chain of Custody",
        "sop_title": "Chain of Identity and Chain of Custody",
        "purpose": (
            "Establish how the identity of patient-specific material is "
            "preserved and documented at every handoff, from collection "
            "through manufacture to administration, so that material is "
            "never given to the wrong patient."
        ),
        "principles": [
            "The chain is never broken and never reconstructed from "
            "memory: identity is verified at each handoff against the "
            "label and the record, at the time of the handoff.",
            "One patient's material is handled at a time in any "
            "work area; concurrent handling is designed out, not "
            "managed by care.",
        ],
        "roles": [
            "Collection Operator", "Logistics Coordinator",
            "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "EU GMP Part IV (ATMP guidelines: traceability and chain "
                "of identity) and EU GMP Chapter 4 documentation.",
                "United States requirements: 21 CFR Part 1271 Subpart D "
                "(current good tissue practice, tracking) and Subpart C "
                "traceability provisions.",
            ],
        },
        "scope_in": (
            "Applies to all autologous and patient-specific materials "
            "handled by a {archetype} organization marketing products "
            "in {market}, in the following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover chain of custody for laboratory samples in "
            "non-clinical testing."
        ),
        "intended_user": (
            "Collection, logistics, manufacturing, and quality personnel"
        ),
        "keywords": [
            "chain of identity", "chain of custody", "coi", "coc",
            "traceability", "patient material", "autologous",
            "unique identifier",
        ],
        "source_ids": ["cfr-part-1271", "eu-gmp-atmp", "eu-gmp-ch4",
                       "ich-q10"],
    },
    {
        "id": "donor-eligibility",
        "title": "Donor eligibility (HCT/P)",
        "procedure_name": "Donor Eligibility (HCT/P)",
        "sop_title": "Donor Eligibility Determination",
        "purpose": (
            "Establish how donors of human cells and tissues are "
            "screened and tested and how donor eligibility is "
            "determined and documented before material is used."
        ),
        "roles": [
            "Screening Personnel", "Responsible Physician",
            "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "United States requirements: 21 CFR Part 1271 Subpart C "
                "(donor eligibility: screening, testing, determination, "
                "and records).",
                "EU coverage in this packet rests on the EU GMP Part IV "
                "ATMP guidelines' starting-material provisions.",
            ],
            "markets": {
                "eu": (
                    "EU market selected: donor screening and testing in "
                    "the EU rest on the tissues and cells directives "
                    "(2004/23/EC and 2006/17/EC), which are not in this "
                    "packet. EU coverage rests on the ATMP GMP guidelines "
                    "only."
                ),
            },
            "always": [
                "FDA's donor eligibility guidance documents, which "
                "interpret Part 1271 screening in detail, are not in "
                "this packet; US coverage rests on the regulation text.",
            ],
        },
        "scope_in": (
            "Applies to donor screening, testing, and eligibility "
            "determination for starting materials used by a {archetype} "
            "organization marketing products in {market}, in the "
            "following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover donor recruitment or compensation, or "
            "eligibility determinations for blood donation."
        ),
        "intended_user": (
            "Donor screening personnel, the responsible person, and the "
            "quality unit"
        ),
        "keywords": [
            "donor eligibility", "donor screening", "hct/p", "donor",
            "eligibility determination", "communicable disease testing",
            "tissue donor",
        ],
        "source_ids": ["cfr-part-1271", "eu-gmp-atmp", "ich-q10"],
    },
    {
        "id": "apheresis-handling",
        "title": "Apheresis and starting material handling",
        "procedure_name": "Apheresis and Starting Material Handling",
        "sop_title": "Apheresis and Starting Material Handling",
        "purpose": (
            "Establish how apheresis collections and other patient "
            "starting materials are received, inspected, stored, and "
            "transferred to manufacturing, with identity and condition "
            "preserved."
        ),
        "roles": [
            "Apheresis Operator", "Collection Supervisor",
            "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "EU GMP Part IV (ATMP guidelines: starting materials, "
                "receipt, and storage) and EU GMP Chapter 5.",
                "United States requirements: 21 CFR Part 1271 Subpart D "
                "(good tissue practice: receipt, storage, and handling).",
            ],
        },
        "scope_in": (
            "Applies to the receipt and handling of apheresis and other "
            "starting materials at a {archetype} organization marketing "
            "products in {market}, in the following functions: "
            "{functions}."
        ),
        "scope_out": (
            "Does not cover the apheresis collection procedure itself, "
            "which is performed at the collection site under its own "
            "procedures and quality agreement."
        ),
        "intended_user": (
            "Materials management, manufacturing, and quality personnel"
        ),
        "keywords": [
            "apheresis", "starting material", "leukapheresis",
            "collection receipt", "material handling", "cryopreservation",
            "receipt inspection",
        ],
        "source_ids": ["cfr-part-1271", "eu-gmp-atmp", "eu-gmp-ch5",
                       "ich-q10"],
    },
    {
        "id": "vector-production",
        "title": "Vector production controls",
        "procedure_name": "Vector Production Controls",
        "sop_title": "Vector Production Controls",
        "purpose": (
            "Establish the controls for the production, testing, and "
            "release of viral and plasmid vectors used as starting "
            "materials or intermediates, so that vector quality is "
            "consistent from batch to batch."
        ),
        "roles": [
            "Production Operator", "Manufacturing Supervisor",
            "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "ICH Q5A(R2) and ICH Q5D (cell substrates and viral "
                "safety for vector-producing systems), and EU GMP Annex "
                "2 and Part IV (ATMP).",
                "Quality-system framing: ICH Q10.",
            ],
        },
        "scope_in": (
            "Applies to vector production performed by or for a "
            "{archetype} organization marketing products in {market}, "
            "in the following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover vector design and construct development "
            "research."
        ),
        "intended_user": (
            "Vector production, quality control, and quality personnel"
        ),
        "keywords": [
            "vector", "viral vector", "lentivirus", "plasmid",
            "vector production", "transduction", "aav",
        ],
        "source_ids": ["ich-q5a-r2", "ich-q5d", "eu-gmp-annex2",
                       "eu-gmp-atmp", "ich-q10"],
    },
    {
        "id": "seed-lot-management",
        "title": "Seed lot management",
        "procedure_name": "Seed Lot Management",
        "sop_title": "Seed Lot Management",
        "purpose": (
            "Establish how microbial and viral seed lots are created, "
            "characterized, stored, and issued, so that production "
            "always starts from a qualified, traceable seed."
        ),
        "roles": [
            "Seed Lot Custodian", "Laboratory Supervisor",
            "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "ICH Q5D (cell substrates, applied to seed systems) and "
                "ICH Q5A(R2), and EU GMP Annex 2.",
                "United States requirements: 21 CFR Part 610 (seed "
                "lot standards) and Part 600.",
            ],
        },
        "scope_in": (
            "Applies to master and working seed lots used at a "
            "{archetype} organization marketing products in {market}, "
            "in the following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover strain development research before banking."
        ),
        "intended_user": (
            "Seed lot custodians, quality control, and the quality unit"
        ),
        "keywords": [
            "seed lot", "seed stock", "master seed", "working seed",
            "seed management", "inoculum",
        ],
        "source_ids": ["ich-q5d", "cfr-part-610", "cfr-part-600",
                       "eu-gmp-annex2", "ich-q5a-r2"],
    },
    {
        "id": "design-controls",
        "title": "Design controls and design transfer",
        "procedure_name": "Design Controls and Design Transfer",
        "sop_title": "Design Controls and Design Transfer",
        "purpose": (
            "Establish how product design is planned, controlled, "
            "verified, validated, and transferred to production, so "
            "that the device produced is the device that was designed "
            "and shown to meet user needs."
        ),
        "principles": [
            "Verification asks whether the design output meets the "
            "design input; validation asks whether the device meets "
            "user needs and intended uses. The two are never merged "
            "into one activity.",
            "The design history file is built as the design proceeds: "
            "it is the record of the design, not a reconstruction of "
            "it at transfer.",
        ],
        "roles": [
            "Design Engineer", "Design Owner", "Quality Assurance",
            "Regulatory Affairs",
        ],
        "coverage": {
            "covers": [
                "United States requirements: 21 CFR Part 820 Subpart C "
                "(design controls) and Part 4 (combination product "
                "application of design controls).",
                "Risk management within design: ICH Q9(R1) method, with "
                "ICH Q10's quality-system framing.",
            ],
            "always": [
                "ISO 13485 and the EU MDR and IVDR texts are not "
                "sources here - ISO standards are paywalled and no "
                "verified public text of the regulations is in the "
                "library. Design-control coverage rests on the Part 820 "
                "and Part 4 text.",
            ],
        },
        "scope_in": (
            "Applies to the design and development of products of a "
            "{archetype} organization marketing products in {market}, "
            "in the following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover feasibility research before design inputs "
            "are established, or software lifecycle processes, which "
            "follow the software procedure."
        ),
        "intended_user": (
            "Design and development engineers, design reviewers, and "
            "the quality unit"
        ),
        "keywords": [
            "design control", "design transfer", "design history file",
            "dhf", "design input", "design output", "design verification",
            "design validation",
        ],
        "source_ids": ["cfr-part-820", "cfr-part-4", "ich-q9-r1", "ich-q10"],
    },
    {
        "id": "performance-evaluation",
        "title": "Performance evaluation",
        "procedure_name": "Performance Evaluation",
        "sop_title": "Performance Evaluation of In Vitro Diagnostics",
        "purpose": (
            "Establish how the scientific validity, analytical "
            "performance, and clinical performance of an in vitro "
            "diagnostic are evaluated and documented across its "
            "lifecycle."
        ),
        "roles": [
            "Evaluation Author", "Scientific Reviewer", "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "United States requirements: 21 CFR Part 809 (in vitro "
                "diagnostic products for human use) and the design "
                "control provisions of Part 820.",
                "Risk management method: ICH Q9(R1).",
            ],
            "markets": {
                "eu": (
                    "EU market selected: performance evaluation in the "
                    "EU is governed by the IVDR, Regulation (EU) "
                    "2017/746, whose text is not in this packet. EU "
                    "coverage rests on the design-control and risk "
                    "sources only, and the IVDR performance evaluation "
                    "report structure is not covered."
                ),
            },
        },
        "scope_in": (
            "Applies to performance evaluation of diagnostic products "
            "of a {archetype} organization marketing products in "
            "{market}, in the following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover clinical trial conduct, which follows the "
            "clinical procedures, or post-market performance follow-up "
            "planning in detail."
        ),
        "intended_user": (
            "Assay development, clinical affairs, regulatory, and "
            "quality personnel"
        ),
        "keywords": [
            "performance evaluation", "clinical performance",
            "analytical performance", "scientific validity", "ivdr",
            "performance study", "diagnostic performance",
        ],
        "source_ids": ["cfr-part-809", "cfr-part-820", "ich-q9-r1",
                       "ich-q10"],
    },
    {
        "id": "human-factors",
        "title": "Human factors engineering",
        "procedure_name": "Human Factors Engineering",
        "sop_title": "Human Factors Engineering",
        "purpose": (
            "Establish how use-related risks are identified and "
            "controlled through user interface design and validated "
            "with representative users, so that the product can be "
            "used safely and effectively by its intended users."
        ),
        "roles": [
            "Human Factors Engineer", "Study Moderator",
            "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "United States requirements: design validation under 21 "
                "CFR 820.30(g), including use under actual or simulated "
                "conditions, and Part 4 for combination products.",
                "Risk management method: ICH Q9(R1).",
            ],
            "always": [
                "FDA's human factors guidance and IEC 62366 are not in "
                "this packet; coverage rests on the Part 820 design "
                "validation text and the ICH Q9(R1) risk method.",
            ],
        },
        "scope_in": (
            "Applies to human factors activities for products of a "
            "{archetype} organization marketing products in {market}, "
            "in the following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover occupational ergonomics of manufacturing "
            "workstations."
        ),
        "intended_user": (
            "Human factors engineers, design teams, and the quality "
            "unit"
        ),
        "keywords": [
            "human factors", "usability", "use error", "use-related "
            "risk", "user interface", "summative evaluation",
            "formative evaluation",
        ],
        "source_ids": ["cfr-part-820", "cfr-part-4", "ich-q9-r1"],
    },
    {
        "id": "device-history-records",
        "title": "Device history records",
        "procedure_name": "Device History Records",
        "sop_title": "Device History Records",
        "purpose": (
            "Establish how device history records are created, reviewed, "
            "and used to release finished devices, so that the history "
            "of every unit or batch shows it was made to its device "
            "master record."
        ),
        "roles": [
            "Production Operator", "Record Reviewer", "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "United States requirements: 21 CFR 820.184 (device "
                "history record) and 820.180-820.198 record provisions.",
                "Documentation principles: EU GMP Chapter 4 and ICH Q10.",
            ],
        },
        "scope_in": (
            "Applies to device history records for products of a "
            "{archetype} organization marketing products in {market}, "
            "in the following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover drug batch records, which follow the batch "
            "record review and release procedure."
        ),
        "intended_user": (
            "Manufacturing, device history reviewers, and the quality "
            "unit"
        ),
        "keywords": [
            "device history record", "dhr", "device master record",
            "dmr", "device release", "production record",
        ],
        "source_ids": ["cfr-part-820", "eu-gmp-ch4", "ich-q10"],
    },
    {
        "id": "udi-labeling",
        "title": "UDI and labeling control",
        "procedure_name": "UDI and Labeling Control",
        "sop_title": "UDI and Device Labeling Control",
        "purpose": (
            "Establish how unique device identifiers are assigned, "
            "applied, and verified, and how device labeling is "
            "controlled, so that every device is identifiable and "
            "traceable throughout distribution."
        ),
        "roles": [
            "Labeling Specialist", "Regulatory Affairs",
            "Quality Assurance",
        ],
        "coverage": {
            "covers": [
                "United States requirements: 21 CFR 820.120 (device "
                "labeling) and 820.184/820.186 identification and "
                "traceability provisions.",
                "Packaging and labeling control principles: EU GMP "
                "Chapter 5.",
            ],
            "always": [
                "21 CFR Part 830, the UDI rule itself (identifier "
                "structure, GUDID submission), is not in this packet; "
                "the packet carries the labeling and traceability "
                "provisions of Part 820.",
            ],
        },
        "scope_in": (
            "Applies to UDI assignment and labeling of devices of a "
            "{archetype} organization marketing products in {market}, "
            "in the following functions: {functions}."
        ),
        "scope_out": (
            "Does not cover drug product labeling, which follows the "
            "labeling and packaging control procedure."
        ),
        "intended_user": (
            "Labeling, regulatory, and quality personnel"
        ),
        "keywords": [
            "udi", "unique device identifier", "device labeling",
            "gudid", "label control", "traceability",
        ],
        "source_ids": ["cfr-part-820", "eu-gmp-ch5", "ich-q10"],
    },
]

# Resolve each topic's packet from the library. The resolved "sources"
# list carries the same dict shape the v1 registry used (name, url,
# filename, instruments), so the drafting build and the citation
# checker consume it unchanged.
for _t in TOPICS:
    _t["sources"] = [dict(SOURCES[_sid]) for _sid in _t["source_ids"]]
del _t


def archetype_by_label(label: str) -> dict:
    for a in ARCHETYPES:
        if a["label"] == label:
            return a
    raise KeyError(label)


def market_by_label(label: str) -> dict:
    for m in MARKETS:
        if m["label"] == label:
            return m
    raise KeyError(label)


def topic_by_id(topic_id: str) -> dict:
    for t in TOPICS:
        if t["id"] == topic_id:
            return t
    raise KeyError(topic_id)


def topic_by_title(title: str) -> dict:
    for t in TOPICS:
        if t["title"] == title:
            return t
    raise KeyError(title)


def coverage_flags(topic, market, archetype):
    """Deterministic coverage flags for one run: the deficits
    between what the user selected and what the topic's packet
    genuinely covers, from the topic's own coverage declaration.
    A combined market (US and EU) is checked as both of its
    components. A topic may also declare "always" flags - limits
    of the packet that hold for every selection, such as a named
    guidance that is not a Genesis source. An empty list means
    the selections sit inside what the packet covers. The run
    always proceeds - the flags travel with the draft (Don't
    Halt, Flag Gaps)."""
    cov = topic.get("coverage", {}) if topic else {}
    flags = list(cov.get("always", []))
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
    Genesis builds one procedure at a time. With the full source
    library registered, every entry carries a topic id."""
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
    is no match, and the caller stops plainly instead of guessing:
    no other topic is substituted (Don't Halt, Flag Gaps covers
    gaps, not substitutions)."""
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
