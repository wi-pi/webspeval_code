# judge/ — automated LLM-as-a-judge (ensemble)

Each agent run is scored by comparing its trajectory (per-step thoughts + screenshots + log)
against the task's ground-truth steps, yielding a binary `CORRECT` verdict. The paper uses the
three judges below as an **ensemble** — run all three and aggregate their verdicts:

- `eval_binary_with_gt_text_gemini.py` — Gemini (`GEMINI_API_KEY`, or `--use_vertex` + `VERTEX_AI_PROJECT_ID`)
- `eval_binary_with_gt_text_claude.py` — Claude via Vertex (`VERTEX_AI_PROJECT_ID`, `VERTEX_AI_LOCATION`)
- `eval_binary_with_gt_text_gpt5.py` — GPT-5, OpenAI/Azure (`OPENAI_API_KEY`, or `AZURE_OPENAI_KEY` + `ENDPOINT_URL`)

Keys are read from the repo-root `.env`; the judge prompt is embedded in each script.

## Inputs

- `--ground_truth_file` *(required)*: `{ "<task_id>": ["step", ...] }` — ships at `../dataset/ground_truth_actions.json`.
- `--run_json_file`: `{ "<task_id>%%<run-label>": "<run output dir>" }` — you build this (see `run_args.example.json`).
- `--task_ids_file`: IDs to score (default `with_navigation_task_ids.json`; also `without_navigation_task_ids.json`).
- `--experiment_dir`: writes `outputs.json` (per-task verdicts) + `stats.json` here. `--api_model`, `--n-proc` as needed.

Each run-output dir (written by `run_with_replay.py`) must contain `interact_messages.json`,
`thoughts.json`, `agent.log`, and `screenshot<N>.png`.

## Run (from `judge/`)

```bash
cd judge
python eval_binary_with_gt_text_gemini.py \
  --ground_truth_file ../dataset/ground_truth_actions.json \
  --task_ids_file with_navigation_task_ids.json \
  --run_json_file run_args.json \
  --api_model gemini-2.5-pro --n-proc 5
```

Repeat with the Claude and GPT-5 scripts; aggregate the three `outputs.json` verdicts for the
final ensemble label.
