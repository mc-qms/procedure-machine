#!/usr/bin/env python3
"""Build a template JSON from a plain-language description.

Usage:
  build_template.py --description "an SOP with subsections under
      Procedure for sample quantity and standard preparation"
      --out custom-template.json [--model google/gemini-2.5-flash]
      [--mode env|vault]

Modes:
  env   — OpenRouter key from the OPENROUTER_API_KEY environment
          variable. This is the Streamlit path: the app passes the
          key from st.secrets as an env var. Never printed or logged.
  vault — the model call goes through the Muse OpenRouter helper
          (~/workspace/custom-connectors/custom.openrouter/bin/
          openrouter_chat.py), which carries the stored credential.
          Local testing only; Streamlit Cloud has no such helper.

The model only converts the description into a section list. It
must not add sections the description does not name — a required
section with no packet content becomes a gap question to the
human, under the zero-inference rule. Output is validated here:
valid JSON, required fields present, ids unique, subsections
(4.1-style) immediately follow their parent. The user confirms
the section list before it is used; this script does not confirm
anything on its own.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_FILE = os.path.join(BASE, "build-template-system.txt")
HELPER = os.path.expanduser(
    "~/workspace/custom-connectors/custom.openrouter/bin/openrouter_chat.py")
VERSION = "1.0"


def die(msg):
    print(f"BUILD TEMPLATE BLOCKED: {msg}", file=sys.stderr)
    sys.exit(2)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise RuntimeError("redirect refused, verify the endpoint")


def call_env(model, system, user):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        die("OPENROUTER_API_KEY is not set in the environment.")
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": 2000,
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=120) as resp:
        data = json.load(resp)
    return data["choices"][0]["message"]["content"]


def call_vault(model, system, user):
    with tempfile.TemporaryDirectory() as td:
        sys_file = os.path.join(td, "system.txt")
        user_file = os.path.join(td, "user.txt")
        out_file = os.path.join(td, "out.json")
        with open(sys_file, "w", encoding="utf-8") as f:
            f.write(system)
        with open(user_file, "w", encoding="utf-8") as f:
            f.write(user)
        r = subprocess.run(
            [sys.executable, HELPER, "--model", model,
             "--system-file", sys_file, "--user-file", user_file,
             "--out", out_file],
            capture_output=True, text=True, timeout=180)
        if r.returncode != 0:
            die(f"model call failed: {r.stdout}{r.stderr}".strip()[:300])
        with open(out_file, encoding="utf-8") as f:
            data = json.load(f)
    return data["choices"][0]["message"]["content"]


def validate(template):
    if not isinstance(template, dict):
        die("model reply is not a JSON object.")
    if template.get("document_type") not in ("SOP", "Test Method"):
        die("document_type must be SOP or Test Method.")
    secs = template.get("required_sections")
    if not isinstance(secs, list) or not secs:
        die("required_sections must be a non-empty list.")
    ids = [str(s.get("id", "")) for s in secs]
    if len(set(ids)) != len(ids):
        die("section ids are not unique.")
    for s in secs:
        if not s.get("title"):
            die("a required section has no title.")
    # A subsection (4.1) must immediately follow its parent (4).
    for i, sid in enumerate(ids):
        if "." in sid:
            parent = sid.split(".")[0]
            if i == 0 or ids[i - 1] != parent:
                # Allow consecutive subsections under the same parent.
                if i == 0 or not ids[i - 1].startswith(parent + "."):
                    die(f"subsection {sid} does not follow its parent {parent}.")
    return template


def main():
    ap = argparse.ArgumentParser(description="Build a template from a description.")
    ap.add_argument("--description")
    ap.add_argument("--out")
    ap.add_argument("--model", default="google/gemini-2.5-flash")
    ap.add_argument("--mode", choices=["env", "vault"], default="env")
    ap.add_argument("--version", action="store_true")
    args = ap.parse_args()

    if args.version:
        print(f"build_template {VERSION}")
        return 0
    if not args.description or not args.out:
        die("--description and --out are required.")

    if not args.description.strip():
        die("description is empty.")
    with open(SYSTEM_FILE, encoding="utf-8") as f:
        system = f.read()
    user = f"Build a template from this description:\n{args.description.strip()}"
    reply = call_vault(args.model, system, user) if args.mode == "vault" \
        else call_env(args.model, system, user)
    reply = reply.strip()
    if reply.startswith("```"):
        reply = reply.strip("`").strip()
        if reply.lower().startswith("json"):
            reply = reply[4:].strip()
    try:
        template = json.loads(reply)
    except json.JSONDecodeError:
        die("model reply is not valid JSON.")
    template = validate(template)
    template["template_id"] = "custom-template"
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(template, f, indent=2)
    print(f"template: {template['document_type']}, "
          f"{len(template['required_sections'])} required sections")
    for s in template["required_sections"]:
        print(f"  {s['id']} {s['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
