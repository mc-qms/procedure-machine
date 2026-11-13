#!/usr/bin/env python3
"""docsrc.py - deterministic source reading for the Protocols & Procedures agent.

Commands
  intake [paths...]                 Extract supplied files, build the cache, print the read record.
  outline FILE                      List detected sections for a file.
  get FILE SECTION | --lines A-B    Print verbatim baseline text for a section or line range.
  find FILE TEXT [--context N] [--regex]  Locate wording (literal unless --regex) with section/page.
  redline FILE SECTION REVISED.txt  Word-level diff of verbatim baseline vs revised text.
  check PATH_OR_FILE                Deterministic consistency checks on a cached file or a new .docx/.txt.
  --version                         Print script version.

FILE may be the exact name, the name without extension, or a unique case-insensitive fragment.
Cache: ./docsrc_cache.json. If it is missing, the sandbox has reset; re-run intake.
"""
import sys, os, re, json, glob, zipfile, hashlib, difflib, datetime
import xml.etree.ElementTree as ET

VERSION = "2.1"
CACHE = "docsrc_cache.json"
SEARCH_DIRS = ["/mnt/user-data/uploads", "/mnt/data", "."]
EXCLUDE_RE = re.compile(r"(^rev_|^rev\d*\.txt$|skill\.md$|^docsrc)", re.I)
EXTS = (".docx", ".pdf", ".txt", ".md")
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MIN_PAGE_CHARS = 25
ANCHOR_RE = re.compile(r"^\s*((?:\d+\.)*\d+)\.?\s+(\S.*)$")
DOCID_RE = re.compile(r"\b(?:SOP|FRM|TM|PRO|RPT|WI|POL|SPC|SPEC|MP|BR|QCM|VMP|DCC|CC|DEV|CAPA)[-\s]?\d{3,7}(?:-[A-Z0-9]+)?\b")
MARKER_RE = re.compile(r"\[(AUTHOR INPUT REQUIRED|TECHNICAL PARAMETER REQUIRED|QA REVIEW REQUIRED|REFERENCE CONFLICT)[^\]]*\]")
PLACEHOLDER_RE = re.compile(r"\bTBD\b|\bTBC\b|\bXX+\b|\[\s*insert[^\]]*\]|<<[^>]*>>", re.I)
UNIT_RE = re.compile(r"^(?:%|µ|u?[mnµ]?[LlgM]\b|mg|mL|µL|uL|ng|kDa|°C|min\b|h\b|rpm|x\s*g)", re.I)
XREF_RE = re.compile(r"\b(?:Section|Step|§)\s*((?:\d+\.)*\d+)", re.I)


# ---------------------------------------------------------------- helpers
def die(msg, code=2):
    print(msg)
    sys.exit(code)


def norm_id(s):
    s = s.strip().rstrip(".")
    while s.endswith(".0") and s.count(".") >= 1:
        s = s[:-2]
    return s


def level_of(sid):
    return sid.count(".") + 1


def load_cache():
    if not os.path.exists(CACHE):
        die("NO INTAKE RECORD. The sandbox may have reset or intake was never run.\n"
            "Re-run: python docsrc.py intake\n"
            "If intake finds no files, ask the user to re-upload. Do not draft from memory.")
    with open(CACHE, encoding="utf-8") as f:
        return json.load(f)


def pick(cache, frag):
    files = cache["files"]
    if frag in files:
        return frag, files[frag]
    stem = [n for n in files if os.path.splitext(n)[0].lower() == frag.lower()]
    if len(stem) == 1:
        return stem[0], files[stem[0]]
    hits = [n for n in files if frag.lower() in n.lower()]
    if len(hits) == 1:
        return hits[0], files[hits[0]]
    if not hits:
        die(f"NOT IN INTAKE RECORD: '{frag}'. Cached files: {', '.join(files) or 'none'}")
    die(f"AMBIGUOUS: '{frag}' matches {hits}. Use a longer name.")


def to_roman(n):
    vals = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
            (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out


def fmt_num(n, fmt):
    if fmt == "lowerLetter":
        return chr(96 + ((n - 1) % 26) + 1)
    if fmt == "upperLetter":
        return chr(64 + ((n - 1) % 26) + 1)
    if fmt == "lowerRoman":
        return to_roman(n)
    if fmt == "upperRoman":
        return to_roman(n).upper()
    if fmt in ("bullet", "none"):
        return ""
    return str(n)


# ---------------------------------------------------------------- DOCX
def docx_extract(path):
    z = zipfile.ZipFile(path)
    names = set(z.namelist())
    doc = ET.fromstring(z.read("word/document.xml"))

    abstract, num_map = {}, {}
    if "word/numbering.xml" in names:
        nx = ET.fromstring(z.read("word/numbering.xml"))
        for an in nx.findall(W + "abstractNum"):
            lv = {}
            for l in an.findall(W + "lvl"):
                il = int(l.get(W + "ilvl"))
                st = l.find(W + "start")
                nf = l.find(W + "numFmt")
                lt = l.find(W + "lvlText")
                lv[il] = {"start": int(st.get(W + "val")) if st is not None else 1,
                          "fmt": nf.get(W + "val") if nf is not None else "decimal",
                          "text": lt.get(W + "val") if lt is not None else ""}
            abstract[an.get(W + "abstractNumId")] = lv
        for n in nx.findall(W + "num"):
            a = n.find(W + "abstractNumId")
            num_map[n.get(W + "numId")] = a.get(W + "val") if a is not None else None

    styles = {}
    if "word/styles.xml" in names:
        sx = ET.fromstring(z.read("word/styles.xml"))
        for s in sx.findall(W + "style"):
            sid = s.get(W + "styleId")
            nm = s.find(W + "name")
            bo = s.find(W + "basedOn")
            ppr = s.find(W + "pPr")
            np_ = ol = None
            if ppr is not None:
                npr = ppr.find(W + "numPr")
                if npr is not None:
                    ni, il = npr.find(W + "numId"), npr.find(W + "ilvl")
                    np_ = (ni.get(W + "val") if ni is not None else None,
                           int(il.get(W + "val")) if il is not None else 0)
                o = ppr.find(W + "outlineLvl")
                if o is not None:
                    ol = int(o.get(W + "val"))
            styles[sid] = {"name": nm.get(W + "val") if nm is not None else sid,
                           "based": bo.get(W + "val") if bo is not None else None,
                           "numPr": np_, "outline": ol}

    def style_attr(sid, key, depth=0):
        while sid and depth < 15:
            st = styles.get(sid)
            if not st:
                return None
            if st[key] is not None:
                return st[key]
            sid, depth = st["based"], depth + 1
        return None

    counters = {}

    def number_for(num_id, ilvl):
        aid = num_map.get(num_id)
        lv = abstract.get(aid, {})
        if ilvl not in lv:
            return ""
        c = counters.setdefault(num_id, {})
        c[ilvl] = c.get(ilvl, lv[ilvl]["start"] - 1) + 1
        for deeper in [k for k in c if k > ilvl]:
            del c[deeper]
        if lv[ilvl]["fmt"] in ("bullet", "none"):
            return "-"
        txt = lv[ilvl]["text"]
        for k in range(ilvl + 1):
            val = c.get(k, lv.get(k, {}).get("start", 1))
            txt = txt.replace(f"%{k+1}", fmt_num(val, lv.get(k, {}).get("fmt", "decimal")))
        return txt.strip()

    def run_text(el):
        out = []

        def walk(e):
            tag = e.tag
            if tag in (W + "del", W + "moveFrom", W + "delText", W + "instrText"):
                return
            if tag == W + "t":
                out.append(e.text or "")
            elif tag == W + "tab":
                out.append("\t")
            elif tag in (W + "br", W + "cr"):
                out.append(" ")
            for ch in e:
                walk(ch)
        walk(el)
        return "".join(out)

    lines = []  # [page(None), text, heading_level or None]

    def para(p):
        ppr = p.find(W + "pPr")
        sid = num = None
        ilvl, outline = 0, None
        if ppr is not None:
            ps = ppr.find(W + "pStyle")
            sid = ps.get(W + "val") if ps is not None else None
            npr = ppr.find(W + "numPr")
            if npr is not None:
                ni, il = npr.find(W + "numId"), npr.find(W + "ilvl")
                num = ni.get(W + "val") if ni is not None else None
                ilvl = int(il.get(W + "val")) if il is not None else 0
            o = ppr.find(W + "outlineLvl")
            if o is not None:
                outline = int(o.get(W + "val"))
        if num is None and sid:
            snp = style_attr(sid, "numPr")
            if snp:
                num, ilvl = snp
        if outline is None and sid:
            outline = style_attr(sid, "outline")
        text = run_text(p).strip()
        prefix = number_for(num, ilvl) if (num and num != "0") else ""
        sname = (styles.get(sid, {}).get("name") or "").lower() if sid else ""
        hl = None
        m = re.match(r"heading\s*(\d)", sname)
        if m:
            hl = int(m.group(1))
        elif sname == "title":
            hl = 0
        elif outline is not None and outline < 9:
            hl = outline + 1
        if not text and not prefix:
            return
        if prefix == "-":
            full = f"- {text}"
        elif prefix:
            full = f"{prefix} {text}".strip()
        else:
            full = text
        lines.append([None, full, hl])

    def table(t):
        for row in t.findall(W + "tr"):
            cells = []
            for tc in row.findall(W + "tc"):
                ps = [run_text(p).strip() for p in tc.iter(W + "p")]
                cells.append(" / ".join(x for x in ps if x))
            if any(cells):
                lines.append([None, "| " + " | ".join(cells) + " |", None])

    def body(el):
        for ch in el:
            if ch.tag == W + "p":
                para(ch)
            elif ch.tag == W + "tbl":
                table(ch)
            elif ch.tag == W + "sdt":
                c = ch.find(W + "sdtContent")
                if c is not None:
                    body(c)

    body(doc.find(W + "body"))

    xml = z.read("word/document.xml").decode("utf8", "ignore")
    tracked = {"ins": xml.count("<w:ins "), "del": xml.count("<w:del "),
               "moves": xml.count("<w:moveFrom ") + xml.count("<w:moveTo ")}
    comments = 0
    if "word/comments.xml" in names:
        comments = z.read("word/comments.xml").decode("utf8", "ignore").count("<w:comment ")
    header = []
    for n in sorted(x for x in names if re.match(r"word/header\d*\.xml", x)):
        t = run_text(ET.fromstring(z.read(n))).strip()
        if t and t not in header:
            header.append(t[:200])
    notes = ["Headers/footers excluded from body text.",
             "Auto-numbering reconstructed from numbering.xml; confirm against the rendered document if a number looks wrong."]
    if tracked["ins"] or tracked["del"]:
        notes.append("Tracked changes read as accepted (insertions kept, deletions dropped).")
    return {"type": "docx", "pages": None, "lines": lines, "tracked": tracked, "comments": comments,
            "header": header, "empty_pages": [], "furniture": [], "notes": notes}


# ---------------------------------------------------------------- PDF
def pdf_pages(path):
    errs = []
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return [(p.extract_text() or "") for p in pdf.pages], "pdfplumber", errs
    except Exception as e:
        errs.append(f"pdfplumber: {e}")
    try:
        import fitz
        d = fitz.open(path)
        return [p.get_text() for p in d], "pymupdf", errs
    except Exception as e:
        errs.append(f"pymupdf: {e}")
    try:
        from pypdf import PdfReader
        r = PdfReader(path)
        return [(p.extract_text() or "") for p in r.pages], "pypdf", errs
    except Exception as e:
        errs.append(f"pypdf: {e}")
    return None, None, errs


def pdf_extract(path):
    pages, engine, errs = pdf_pages(path)
    if pages is None:
        return {"type": "pdf", "pages": 0, "lines": [], "error": "; ".join(errs)}
    # repeating page furniture: same line (digits normalized) on >50% of pages
    furniture = set()
    if len(pages) >= 3:
        counts = {}
        for t in pages:
            seen = set()
            for ln in t.splitlines()[:4] + t.splitlines()[-4:]:
                k = re.sub(r"\d+", "#", ln.strip())
                if k and k not in seen:
                    seen.add(k)
                    counts[k] = counts.get(k, 0) + 1
        furniture = {k for k, c in counts.items() if c > len(pages) / 2}
    lines, body_chars = [], [0] * len(pages)
    for i, t in enumerate(pages):
        for ln in t.splitlines():
            s = ln.strip()
            if not s or re.sub(r"\d+", "#", s) in furniture:
                continue
            lines.append([i + 1, s, None])
            body_chars[i] += len(s)
    empty = [i + 1 for i, c in enumerate(body_chars) if c < MIN_PAGE_CHARS]
    notes = [f"Extracted with {engine}.", "Repeating headers/footers removed from body text."]
    if empty:
        notes.append(f"Pages with no extractable text (likely scanned/image): {empty}")
    return {"type": "pdf", "pages": len(pages), "lines": lines, "tracked": None, "comments": None,
            "header": sorted(furniture)[:5], "empty_pages": empty, "furniture": sorted(furniture), "notes": notes}


def text_extract(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = [[None, l.rstrip(), None] for l in f if l.strip()]
    return {"type": "text", "pages": None, "lines": lines, "tracked": None, "comments": None,
            "header": [], "empty_pages": [], "furniture": [], "notes": []}


# ---------------------------------------------------------------- anchors
def build_anchors(lines):
    anchors = []
    for i, (pg, t, hl) in enumerate(lines):
        if t.startswith("|"):
            continue
        m = ANCHOR_RE.match(t)
        if m:
            sid = norm_id(m.group(1))
            title = m.group(2).strip()
            lvl = level_of(sid)
            headingish = len(title) <= 60 and not title.endswith(".")
            if lvl == 1 and not headingish and hl is None:
                continue
            if hl is None and (title[:1].islower() or UNIT_RE.match(title)):
                continue  # measurement or sentence fragment, not a section
            if lvl > 1 and hl is None:
                top = int(sid.split(".")[0])
                prev_tops = [int(a["id"].split(".")[0]) for a in anchors if a["id"]]
                if prev_tops and top < max(prev_tops):
                    continue  # numbering runs backward, e.g. "2.5 mg" under section 4
            anchors.append({"id": sid, "level": lvl, "title": title[:80], "line": i})
        elif hl is not None and len(t) <= 120:
            anchors.append({"id": None, "level": max(hl, 1), "title": t[:80], "line": i})
    return anchors


def section_range(rec, key):
    anchors, n = rec["anchors"], len(rec["lines"])
    k = norm_id(key) if re.match(r"^[\d.]+$", key.strip()) else None
    hit = None
    for idx, a in enumerate(anchors):
        if (k and a["id"] == k) or (not k and key.lower() in a["title"].lower()):
            hit = idx
            break
    if hit is None:
        return None
    a = anchors[hit]
    end = n
    for b in anchors[hit + 1:]:
        if b["level"] <= a["level"]:
            end = b["line"]
            break
    return a, a["line"], end


def section_of_line(rec, i):
    cur = None
    for a in rec["anchors"]:
        if a["line"] <= i:
            cur = a
        else:
            break
    return (cur["id"] or cur["title"]) if cur else "(before first section)"


def page_span(rec, s, e):
    pgs = [l[0] for l in rec["lines"][s:e] if l[0]]
    return f"p. {min(pgs)}-{max(pgs)}" if pgs else ""


# ---------------------------------------------------------------- commands
def cmd_intake(args):
    paths = []
    if args:
        for a in args:
            paths += glob.glob(a) if any(c in a for c in "*?[") else [a]
    else:
        for d in SEARCH_DIRS:
            if os.path.isdir(d):
                for f in sorted(os.listdir(d)):
                    fp = os.path.join(d, f)
                    if os.path.isfile(fp) and f.lower().endswith(EXTS) and not EXCLUDE_RE.search(f):
                        paths.append(fp)
                if paths:
                    break  # first directory containing uploads wins; never sweep agent work files
    seen, uniq = set(), []
    for p in paths:
        rp = os.path.realpath(p)
        if rp not in seen:
            seen.add(rp)
            uniq.append(p)
    if not uniq:
        die("NO FILES FOUND. Searched: " + ", ".join(SEARCH_DIRS) +
            "\nThe uploads are not available to this session. Ask the user to re-upload (.docx preferred). Do not proceed.")

    cache = {"created": datetime.datetime.now().isoformat(timespec="seconds"), "files": {}}
    if args and os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            cache["files"] = json.load(f).get("files", {})  # explicit intake adds to the record
    print("SOURCE READ RECORD")
    print("| File | Status | Pages | Chars | Sections | Tracked ins/del | Comments | First section | Last section |")
    print("|---|---|---|---|---|---|---|---|---|")
    blocked = []
    for p in uniq:
        name = os.path.basename(p)
        ext = os.path.splitext(name)[1].lower()
        try:
            if ext == ".docx":
                rec = docx_extract(p)
            elif ext == ".pdf":
                rec = pdf_extract(p)
            elif ext in (".txt", ".md"):
                rec = text_extract(p)
            else:
                rec = {"type": ext, "lines": [], "error": "Unsupported type. Ask for .docx, .pdf, or pasted text."}
        except Exception as e:
            rec = {"type": ext, "lines": [], "error": f"Extraction failed: {e}"}
        chars = sum(len(l[1]) for l in rec["lines"])
        rec["anchors"] = build_anchors(rec["lines"]) if rec["lines"] else []
        if rec.get("error") or chars == 0:
            status = "UNREADABLE"
        elif rec.get("empty_pages"):
            status = "PARTIAL"
        else:
            status = "OK"
        rec.update({"status": status, "chars": chars, "path": p,
                    "sha256": hashlib.sha256(open(p, "rb").read()).hexdigest()[:12]})
        cache["files"][name] = rec
        an = rec["anchors"]
        first = f"{an[0]['id'] or ''} {an[0]['title']}".strip() if an else "-"
        last = f"{an[-1]['id'] or ''} {an[-1]['title']}".strip() if an else "-"
        tr = rec.get("tracked")
        trs = f"{tr['ins']}/{tr['del']}" if tr else "n/a"
        cm = rec.get("comments")
        print(f"| {name} | {status} | {rec.get('pages') or '-'} | {chars} | {len(an)} | {trs} | "
              f"{cm if cm is not None else 'n/a'} | {first[:40]} | {last[:40]} |")
        if status != "OK":
            why = rec.get("error") or ("No extractable text (likely scanned, image-only, or protected)." if status == "UNREADABLE"
                                       else f"Pages with no body text: {rec.get('empty_pages')}. Content on those pages is unread.")
            blocked.append((name, status, why))
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    print()
    for name in [os.path.basename(p) for p in uniq]:
        for n in cache["files"][name].get("notes", []):
            print(f"Note ({name}): {n}")
    if blocked:
        print("\nBLOCKED OR PARTIAL SOURCES - do not use unread content:")
        for name, st, why in blocked:
            print(f"- {name}: {st}. {why}")
        print("Ask the user for a .docx/text-based PDF or pasted text for each blocked file.")
    print(f"\nCache written: {CACHE} ({len(cache['files'])} file(s) on record)")


def cmd_outline(args):
    if not args:
        die("usage: outline FILE")
    cache = load_cache()
    name, rec = pick(cache, args[0])
    print(f"OUTLINE: {name} ({rec['status']}, {len(rec['anchors'])} sections)")
    for a in rec["anchors"]:
        pg = rec["lines"][a["line"]][0]
        ind = "  " * (a["level"] - 1)
        print(f"{ind}{a['id'] or '*'}  {a['title']}" + (f"  (p. {pg})" if pg else "") + f"  [line {a['line']}]")


def cmd_get(args):
    if len(args) < 2:
        die("usage: get FILE SECTION | get FILE --lines A-B")
    cache = load_cache()
    name, rec = pick(cache, args[0])
    if rec["status"] == "UNREADABLE":
        die(f"BLOCKED: {name} is UNREADABLE. No baseline available.")
    if args[1] == "--lines":
        a, b = [int(x) for x in args[2].split("-")]
        s, e, label = a, b + 1, f"lines {a}-{b}"
    else:
        r = section_range(rec, " ".join(args[1:]))
        if r is None:
            die(f"SECTION NOT FOUND: '{' '.join(args[1:])}' in {name}. Run outline, use --lines, "
                "or ask the user to paste the section. Do not draft this section from memory.")
        a, s, e = r
        label = f"section {a['id'] or ''} {a['title']}".strip()
    print(f"VERBATIM BASELINE: {name} | {label} | lines {s}-{e-1} {page_span(rec, s, e)}")
    print("-" * 60)
    for l in rec["lines"][s:e]:
        print(l[1])
    print("-" * 60)


def cmd_find(args):
    if len(args) < 2:
        die("usage: find FILE TEXT [--context N] [--regex]")
    ctx = 1
    if "--context" in args:
        i = args.index("--context")
        ctx = int(args[i + 1])
        args = args[:i] + args[i + 2:]
    use_regex = "--regex" in args
    args = [a for a in args if a != "--regex"]
    cache = load_cache()
    name, rec = pick(cache, args[0])
    term = " ".join(args[1:])
    pat = re.compile(term if use_regex else re.escape(term), re.I)
    hits = [i for i, l in enumerate(rec["lines"]) if pat.search(l[1])]
    print(f"FIND '{term}' in {name}: {len(hits)} match(es)")
    if not hits:
        print("No location found. Do not attribute this content to the source.")
    for i in hits[:40]:
        pg = rec["lines"][i][0]
        print(f"\n[section {section_of_line(rec, i)}" + (f", p. {pg}" if pg else "") + f", line {i}]")
        for l in rec["lines"][max(0, i - ctx): i + ctx + 1]:
            print("  " + l[1])
    if len(hits) > 40:
        print(f"\n... {len(hits) - 40} more. Narrow the search.")


def cmd_redline(args):
    if len(args) < 3:
        die("usage: redline FILE SECTION REVISED.txt")
    cache = load_cache()
    name, rec = pick(cache, args[0])
    r = section_range(rec, args[1])
    if r is None:
        die(f"SECTION NOT FOUND: '{args[1]}' in {name}. No redline without a verbatim baseline.")
    a, s, e = r
    strip_num = lambda t: re.sub(r"^\s*(?:\d+\.)*\d+\.?\s+", "", t)
    base = "\n".join(strip_num(l[1]) for l in rec["lines"][s:e])
    with open(args[2], encoding="utf-8") as f:
        new = "\n".join(strip_num(l) for l in f.read().strip().splitlines())
    tok = lambda x: re.findall(r"\s+|[^\s]+", x)
    bt, nt = tok(base), tok(new)
    sm = difflib.SequenceMatcher(None, bt, nt, autojunk=False)
    out, kept, total = [], 0, len([t for t in bt if not t.isspace()]) or 1
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        old, nw = "".join(bt[i1:i2]), "".join(nt[j1:j2])
        if op == "equal":
            out.append(old)
            kept += len([t for t in bt[i1:i2] if not t.isspace()])
        else:
            if old[:1].isspace() or nw[:1].isspace():
                out.append(" ")
            if old.strip():
                out.append(f"~~{old.strip()}~~")
            if nw.strip():
                out.append(f"**{nw.strip()}**")
            if old[-1:].isspace() or nw[-1:].isspace():
                out.append(" ")
    print(f"REDLINE: {name} | section {a['id'] or ''} {a['title'][:50]} | baseline lines {s}-{e-1}")
    print("Leading section numbers ignored; numbering is checked separately.")
    print(f"Baseline words retained: {kept}/{total} ({100*kept//total}%)")
    print("-" * 60)
    print("".join(out))
    print("-" * 60)


def cmd_check(args):
    if not args:
        die("usage: check PATH_OR_FILE")
    target = args[0]
    if os.path.exists(target):
        ext = os.path.splitext(target)[1].lower()
        rec = docx_extract(target) if ext == ".docx" else (pdf_extract(target) if ext == ".pdf" else text_extract(target))
        rec["anchors"] = build_anchors(rec["lines"])
        name = os.path.basename(target)
    else:
        name, rec = pick(load_cache(), target)
    lines = rec["lines"]
    print(f"CHECK: {name}")
    issues, last = [], {}
    for a in [x for x in rec["anchors"] if x["id"]]:
        parts = a["id"].split(".")
        parent = ".".join(parts[:-1])
        prev = last.get(parent)
        cur = int(parts[-1])
        if prev is not None and cur != prev + 1:
            issues.append(f"{a['id']} follows {parent + '.' if parent else ''}{prev}")
        last[parent] = cur
        for k in [k for k in last if k.startswith(a["id"] + ".")]:
            del last[k]
    print(f"\nNumbering sequence: {'no gaps/repeats detected' if not issues else ''}")
    for i in issues:
        print(f"- {i}")
    ids = {a["id"] for a in rec["anchors"] if a["id"]}
    bad = []
    for i, l in enumerate(lines):
        for m in XREF_RE.finditer(l[1]):
            if norm_id(m.group(1)) not in ids:
                bad.append(f"line {i}: '{m.group(0)}' has no matching section")
    print(f"\nInternal cross-references: {'all resolve' if not bad else ''}")
    for b in bad[:30]:
        print(f"- {b}")
    docids = {}
    for l in lines:
        for m in DOCID_RE.finditer(l[1]):
            docids[m.group(0)] = docids.get(m.group(0), 0) + 1
    print("\nDocument IDs cited: " + (", ".join(f"{k} (x{v})" for k, v in sorted(docids.items())) or "none"))
    mk = [(i, m.group(0)) for i, l in enumerate(lines) for m in MARKER_RE.finditer(l[1])]
    ph = [(i, m.group(0)) for i, l in enumerate(lines) for m in PLACEHOLDER_RE.finditer(l[1])]
    dcr = [i for i, l in enumerate(lines) if re.search(r"\bDCR\b", l[1])]
    print(f"\nUnresolved markers: {len(mk)}")
    for i, t in mk[:20]:
        print(f"- line {i}: {t[:90]}")
    print(f"Placeholders (TBD/XX/insert): {len(ph)}" + (f" at lines {[i for i, _ in ph[:15]]}" if ph else ""))
    print(f"Legacy 'DCR' occurrences: {len(dcr)}" + (f" at lines {dcr[:15]}" if dcr else ""))
    if rec.get("tracked") is not None:
        t = rec["tracked"]
        print(f"\nTracked changes: {t['ins']} insertions, {t['del']} deletions, {t['moves']} moves | Comments: {rec['comments']}")
    print("\nFacts only. Severity (Blocking/Material/Editorial) is assigned by the agent; layout findings need rendered confirmation.")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--version":
        print(f"docsrc {VERSION}")
        return
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    cmd, args = sys.argv[1], sys.argv[2:]
    fn = {"intake": cmd_intake, "outline": cmd_outline, "get": cmd_get, "find": cmd_find,
          "redline": cmd_redline, "check": cmd_check}.get(cmd)
    if not fn:
        die(f"Unknown command '{cmd}'.\n{__doc__}")
    fn(args)


if __name__ == "__main__":
    main()
