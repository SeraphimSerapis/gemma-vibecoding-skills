#!/usr/bin/env python3
"""gemma-coder worker: send a one-file task spec to a local model and write the result.

Usage:
    python3 gemma_worker.py --task tasks/01-thing.md --out src/thing.py \
        [--context src/dep.py ...] [--model NAME] [--url URL --api ollama|openai]

Backend and model come from ~/.config/gemma-coder/config.json (created by setup.py);
--model/--url/--api override it per call. Works with ollama (native API) or any
OpenAI-compatible server (LM Studio, llama.cpp llama-server, mlx_lm.server, ...).

The task file is a markdown spec describing exactly one output file. Context files
are included read-only so the model can match existing interfaces. The largest
fenced code block in the response is written to --out.
"""
import argparse
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request

CONFIG_PATH = pathlib.Path(os.environ.get(
    "GEMMA_CODER_CONFIG",
    str(pathlib.Path.home() / ".config" / "gemma-coder" / "config.json")))

SYSTEM_PROMPT = """You are a senior software engineer. You will receive a spec for exactly one file.
Respond with a single fenced code block containing the COMPLETE contents of that file.
No explanations before or after the code block. No placeholders or TODOs — write the full implementation.
Follow the spec exactly: file purpose, function signatures, and behavior are all requirements."""


def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


def build_prompt(task_path, context_paths, out_path):
    parts = ["Target file to write: `%s`\n" % out_path]
    for ctx in context_paths:
        parts.append("Existing file `%s` (read-only context, do not rewrite it):\n"
                     "```\n%s\n```\n" % (ctx, ctx.read_text()))
    parts.append("## Task spec\n\n" + task_path.read_text())
    return "\n".join(parts)


def post_json(url, payload, timeout, api_key=None):
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def call_ollama(base_url, model, prompt, options, timeout):
    data = post_json(base_url.rstrip("/") + "/api/chat", {
        "model": model,
        "stream": False,
        "think": False,  # thinking models: skip reasoning tokens, go straight to code
        "options": options,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }, timeout)
    eval_count = data.get("eval_count", 0)
    eval_ns = data.get("eval_duration", 0)
    if eval_ns:
        print("[gemma-coder] %d tokens, %.1f tok/s, %.1fs total"
              % (eval_count, eval_count / (eval_ns / 1e9),
                 data.get("total_duration", 0) / 1e9), file=sys.stderr)
    return data["message"]["content"]


def call_openai(base_url, model, prompt, options, timeout, api_key=None):
    data = post_json(base_url.rstrip("/") + "/v1/chat/completions", {
        "model": model,
        "temperature": options.get("temperature", 0.2),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }, timeout, api_key)
    return data["choices"][0]["message"]["content"]


def strip_thinking(text):
    """Remove <think>...</think> blocks some models emit before the answer."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def extract_code(text):
    blocks = re.findall(r"```[a-zA-Z0-9_+-]*\n(.*?)```", text, flags=re.DOTALL)
    if not blocks:
        return None
    return max(blocks, key=len)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, help="markdown file with the task spec")
    ap.add_argument("--out", required=True, help="path of the file to write")
    ap.add_argument("--context", nargs="*", default=[],
                    help="existing files to include as read-only context")
    ap.add_argument("--model", help="override configured model")
    ap.add_argument("--url", help="override backend base URL")
    ap.add_argument("--api", choices=["ollama", "openai"], help="override backend API type")
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()

    cfg = load_config()
    model = args.model or cfg.get("model")
    base_url = args.url or cfg.get("base_url")
    api = args.api or cfg.get("api")
    if not (model and base_url and api):
        print("[gemma-coder] no backend configured. Run: python3 %s"
              % (pathlib.Path(__file__).parent / "setup.py"), file=sys.stderr)
        return 2

    options = {"temperature": cfg.get("temperature", 0.2),
               "num_ctx": cfg.get("num_ctx", 16384)}
    prompt = build_prompt(pathlib.Path(args.task),
                          [pathlib.Path(p) for p in args.context], args.out)
    print("[gemma-coder] %s (%s) <- %s (%d chars)"
          % (model, api, args.task, len(prompt)), file=sys.stderr)

    try:
        api_key = os.environ.get("GEMMA_CODER_API_KEY") or cfg.get("api_key")
        if api == "ollama":
            response = call_ollama(base_url, model, prompt, options, args.timeout)
        else:
            response = call_openai(base_url, model, prompt, options, args.timeout,
                                   api_key)
    except urllib.error.URLError as e:
        print("[gemma-coder] cannot reach %s (%s). Is the server running? "
              "Re-run setup.py to reconfigure." % (base_url, e), file=sys.stderr)
        return 2

    code = extract_code(strip_thinking(response))
    if code is None:
        print("[gemma-coder] ERROR: no code block in response. Raw response follows:",
              file=sys.stderr)
        print(response, file=sys.stderr)
        return 1

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(code)
    print("[gemma-coder] wrote %s (%d lines)" % (out, len(code.splitlines())),
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
