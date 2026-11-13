#!/usr/bin/env python3
"""Markdown draft -> Rich Text Format, deterministic, no LLM.

Usage:
  md_to_rtf.py draft_final.md draft_final.rtf
  md_to_rtf.py --version

The demo downloads drafts as .md; RTF opens directly in Word and
looks like a document instead of raw markup (Manuel, Nov 11,
2026). The RTF carries the same content, including the Discussion
Draft status line and any flagged gap markers — it is the same
draft in a different format, not a clean copy.

Conversion is deliberately small: # / ## / ### headings become
bold at 16 / 14 / 12 pt, "- " lines become bullets, everything
else is 11 pt body text. No tables, no images, no styles beyond
that. RTF special characters (\\, {, }) are escaped.
"""

import argparse
import re
import sys

VERSION = "1.0"


def escape(s):
    # Backslash and braces first, then any non-ASCII character as
    # an RTF \u escape (finding 17): drafts routinely carry °C,
    # µL, em dashes, and curly quotes, and written raw they render
    # as mojibake in Word — in a technical document, exactly the
    # characters that matter.
    s = s.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
    out = []
    for ch in s:
        o = ord(ch)
        if o > 127:
            out.append(f"\\u{o if o < 32768 else o - 65536}?")
        else:
            out.append(ch)
    return "".join(out)


def md_to_rtf(text):
    out = ["{\\rtf1\\ansi\\deff0",
           "{\\fonttbl {\\f0 Arial;}}",
           "\\f0"]
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            out.append("\\par")
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", stripped)
        if m:
            size = {1: 32, 2: 28, 3: 24}[len(m.group(1))]
            out.append(f"\\pard\\sb240\\sa60\\fs{size}\\b {escape(m.group(2))}\\b0\\par")
            continue
        if stripped.startswith("- "):
            out.append(f"\\pard\\fi-360\\li720\\fs22 \\bullet\\tab {escape(stripped[2:])}\\par")
            continue
        # Inline bold **text** -> \b text\b0 ; inline *text* left as-is.
        body = re.sub(r"\*\*(.+?)\*\*", r"\\b \1\\b0 ", escape(stripped))
        out.append(f"\\pard\\fs22 {body}\\par")
    out.append("}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Convert a Markdown draft to RTF.")
    ap.add_argument("input", nargs="?")
    ap.add_argument("output", nargs="?")
    ap.add_argument("--version", action="store_true")
    args = ap.parse_args()
    if args.version:
        print(f"md_to_rtf {VERSION}")
        return 0
    if not args.input or not args.output:
        print("usage: md_to_rtf.py <in.md> <out.rtf>", file=sys.stderr)
        return 2
    with open(args.input, encoding="utf-8") as f:
        text = f.read()
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(md_to_rtf(text))
    print(f"Wrote {args.output} ({len(text)} chars in)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
