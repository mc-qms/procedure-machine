#!/usr/bin/env python3
"""One model call for the Procedure Machine pipeline.

Usage:
  model_call.py --model google/gemini-2.5-flash \
      --system-file hfe-system.txt --user-file hfe-user.txt \
      --out hfe_raw.json [--mode env|vault] [--temperature 0.2]

Modes:
  env   — OpenRouter key from the OPENROUTER_API_KEY environment
          variable. This is the Streamlit path: the app passes the
          key from st.secrets as an env var. Never printed or logged.
  vault — the model call goes through the Muse OpenRouter helper
          (~/workspace/custom-connectors/custom.openrouter/bin/
          openrouter_chat.py), which carries the stored credential.
          Local testing only; Streamlit Cloud has no such helper.

Output: the full OpenRouter reply JSON, same shape as
openrouter_chat.py writes. The caller strips a code fence and
parses the content; this script does not interpret the reply.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request

HELPER = os.path.expanduser(
    "~/workspace/custom-connectors/custom.openrouter/bin/openrouter_chat.py")
VERSION = "1.0"


def die(msg):
    print(f"MODEL CALL BLOCKED: {msg}", file=sys.stderr)
    sys.exit(2)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise RuntimeError("redirect refused, verify the endpoint")


def call_env(model, system, user, temperature, max_tokens):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        die("OPENROUTER_API_KEY is not set in the environment.")
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=180) as resp:
        return json.load(resp)


def call_vault(model, system, user, temperature, max_tokens):
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
             "--out", out_file, "--temperature", str(temperature),
             "--max-tokens", str(max_tokens)],
            capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            die(f"model call failed: {r.stdout}{r.stderr}".strip()[:300])
        with open(out_file, encoding="utf-8") as f:
            return json.load(f)


def main():
    ap = argparse.ArgumentParser(description="One Procedure Machine model call.")
    ap.add_argument("--model")
    ap.add_argument("--system-file")
    ap.add_argument("--user-file")
    ap.add_argument("--out")
    ap.add_argument("--mode", choices=["env", "vault"], default="env")
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--max-tokens", type=int, default=8000)
    # 8000, not 4000: a revised draft plus its Revision Summary, and
    # a cold-read findings list with verbatim quotes, can legitimately
    # exceed 4,000 output tokens (test-022, Nov 11, 2026: three
    # replies hit the 4,000 cap mid-output, one of them a findings
    # JSON that then failed to parse). The cap is a ceiling, not a
    # target — the model only outputs what it needs.
    ap.add_argument("--version", action="store_true")
    args = ap.parse_args()

    if args.version:
        print(f"model_call {VERSION}")
        return 0
    for needed in ("model", "system_file", "user_file", "out"):
        if not getattr(args, needed):
            die(f"--{needed.replace('_', '-')} is required.")

    with open(args.system_file, encoding="utf-8") as f:
        system = f.read()
    with open(args.user_file, encoding="utf-8") as f:
        user = f.read()

    data = call_vault(args.model, system, user, args.temperature, args.max_tokens) \
        if args.mode == "vault" else call_env(args.model, system, user, args.temperature, args.max_tokens)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    usage = data.get("usage", {})
    print(f"model: {data.get('model')}")
    print(f"usage: {usage}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
