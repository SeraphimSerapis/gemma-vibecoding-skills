---
name: gemma-coder
description: Delegate code-writing to a local model (Gemma, Qwen, etc.) running on the user's machine. Use for any request to build or change application code when the user wants a local model to write the code while the agent plans and reviews. The agent must NOT write application source files directly.
---

# gemma-coder: the agent plans, a local model codes

Division of labor (strict):
- **You (the agent)**: requirements, architecture, task decomposition, prompts, code
  review, running tests, deciding retries. You write only: task specs under `tasks/`,
  test files, and glue such as configs when the local model repeatedly fails.
- **The local model** (via `scripts/gemma_worker.py` in this skill's directory):
  writes ALL application source files.

## First run

Check that a backend is configured: `python3 <skill-dir>/scripts/setup.py --list`

- If it prints backends and models but `~/.config/gemma-coder/config.json` does not
  exist yet: show the user the model list, ask which model to use, then run
  `python3 <skill-dir>/scripts/setup.py --save <model>`.
- If it reports no backend: show the user its install hints (ollama is the easiest;
  LM Studio, llama.cpp `llama-server`, and `mlx_lm.server` also work) and stop until
  one is available.

## Loop

1. **Plan.** Write `tasks/PLAN.md` in the user's project: goal, file tree, and a
   numbered task list. Each task = exactly ONE output file, ordered so dependencies
   come first.
2. **Spec each task** as `tasks/NN-<name>.md`. A good spec includes: file purpose,
   exact public function/class signatures, behavior details, edge cases, and libraries
   allowed. The local model cannot see the repo — the spec plus `--context` files must
   be fully self-contained. State the target language version and any syntax it must
   avoid.
3. **Delegate** each task in dependency order:
   ```
   python3 <skill-dir>/scripts/gemma_worker.py --task tasks/NN-name.md \
       --out src/file.py --context src/dep1.py src/dep2.py
   ```
   Pass as `--context` every file the new code must interface with.
4. **Review** the generated file against the spec, then run it / run tests.
   Prefer writing the test file yourself before delegating, so review is independent.
5. **On failure**: do NOT silently fix the code yourself. Improve the spec (state what
   was wrong, add the failing case as an explicit requirement) and re-run the worker —
   up to 2 retries per task. After 2 failed retries, fix it directly and note in the
   final summary that the local model needed a manual fix on that file.
6. **Summarize**: what the local model wrote, what passed, what needed retries or
   manual fixes.

## Notes

- Exit code 2 from the worker means backend/config trouble (not a code failure):
  re-run setup or check the server, don't burn a retry.
- Model choice per task: `--model NAME` overrides the configured default. Use a small
  fast model for trivial files, the strongest local model for core logic.
