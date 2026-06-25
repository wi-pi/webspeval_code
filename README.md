# WebSP-Eval

**Evaluating Web Agents on Website Security and Privacy Tasks** — artifact for the PETS 2026 paper.

**Project website:** https://wiscprivacy.com/webspeval

WebSP-Eval measures how well LLM-powered web agents perform *website security and privacy
tasks* (managing cookies, configuring privacy settings, revoking sessions, etc.) on **live
websites tied to user accounts**. This repository contains the benchmark dataset, the agent that
executes the tasks with account/initial-state management, and the record-and-replay browser
extension. The automated judge is added under `judge/`.

## Repository layout

```
webspeval_code/
├── src/                    # the web agent (built on WebVoyager) + replay engine
│   ├── run_with_replay.py  #   main agent loop + CLI (run from repo root)
│   ├── state_reset_check.py #  replay one S0 trace in ON/OFF to verify state reset
│   ├── selenium_browser_run.py #  open Chrome on a profile to sign in (sock-puppet account)
│   ├── api_utils.py prompts.py utils.py utils_webarena.py
│   └── state_reset/        #   Selenium record-and-replay state-reset engine
├── extension/              # Chrome MV3 record-and-replay extension
├── dataset/                # the benchmark (200 instances) + ground truth + S0 traces
│   ├── tasks_with_navigation.jsonl       # WithNav prompts (200)
│   ├── tasks_without_navigation.jsonl    # W/oNav prompts (200)
│   ├── ground_truth_actions.json         # ground-truth action sequences (200)
│   ├── ground_truth_ui_elements.csv      # target UI-element annotations
│   ├── task_categorization.csv           # task / website categories
│   └── state_traces/                     # recorded initial-state (S0) traces (JSON, PII-templatized)
├── login_traces/           # YOU record these (not shipped) — see docs/RECORDING_GUIDE.md
├── judge/                  # automated MLLM-as-a-judge (added separately)
├── docs/                   # INSTALL, ACCOUNT_SETUP, RECORDING_GUIDE, RECORD_AND_REPLAY_TOOL
├── .env                    # blank template — fill with your keys/account (see docs/INSTALL.md)
├── requirements.txt  LICENSE-code  LICENSE-dataset
```

## The dataset

- **200 task instances / 138 unique tasks across 28 websites**, in two prompt variants:
  **WithNav** (includes navigation hints) and **W/oNav** (instruction only).
- Each record carries the website, prompt, login requirement, the initial-state (`S0`) reset
  operations, and (for login-required sites) a `login_click_file` reference.
- `state_traces/` holds the recorded `S0` traces used to put each site into a consistent initial
  state before the agent runs. Sock-puppet identity in these traces is replaced with
  `{{WEBSP_ACCOUNT_*}}` placeholders that are filled from your `.env` at replay time.

## Quickstart

1. **Install** — see [docs/INSTALL.md](docs/INSTALL.md).
2. **Configure `.env`** — fill the model API keys for the providers you'll run, plus your
   sock-puppet account vars (`WEBSP_ACCOUNT_*`). See [docs/ACCOUNT_SETUP.md](docs/ACCOUNT_SETUP.md).
3. **Accounts, profiles, login traces** — create your own sock-puppet accounts, provide the Chrome
   profiles, and record your own login traces:
   [docs/ACCOUNT_SETUP.md](docs/ACCOUNT_SETUP.md) + [docs/RECORDING_GUIDE.md](docs/RECORDING_GUIDE.md).
4. **Run from the repository root** (so `dataset/state_traces/…` and `login_traces/…` resolve):

   ```bash
   python src/run_with_replay.py \
     --test_file dataset/tasks_without_navigation.jsonl \
     --model_type gemini \
     --api_model gemini-2.5-pro \
     --output_dir outputs/
   ```

   Filter to a subset with `--web_names Docker,Reddit` or `--task_id Docker_task-1_ON`.
   Missing API keys for the selected provider error out at startup.

## Accounts & live websites (please read)

This is a **live-website** benchmark tied to **user accounts**. For ethical reasons the artifact
ships **no accounts and no login traces** — you create your own sock-puppet accounts and record
your own login traces with the included extension. See [docs/ACCOUNT_SETUP.md](docs/ACCOUNT_SETUP.md).

## Captcha (Moodle) tasks

Moodle instances are flagged `"captcha_setup": true` and run with undetected-chromedriver +
`selenium-stealth` using a separate `src/test_profile_captcha/` profile and an active
`check_cloudflare` hook; every other task uses the plain Selenium driver and `src/test_profile/`.
Optional captcha/bot-wall push alerts via `NTFY_TOPIC_URL` (see [docs/INSTALL.md](docs/INSTALL.md)).

## Reproducibility caveats

- **Live sites drift.** Selectors, labels, and layouts change over time; the replay engine uses
  multi-tier fallbacks but cannot guarantee against site redesigns. You can replay a single `S0`
  trace in ON/OFF states to check it still reproduces on the live site:
  `python src/state_reset_check.py --templatized_trace --session_json dataset/state_traces/<task>/<session>/session-*.json`
  (see [docs/RECORD_AND_REPLAY_TOOL.md](docs/RECORD_AND_REPLAY_TOOL.md)).
- **Region matters.** Cookie/privacy UIs differ by jurisdiction (GDPR/CCPA), so results can vary
  by location.
- **Models evolve.** Some backbones/judges may be deprecated; substitute an available model via
  `--api_model`.

## License & acknowledgment

This artifact is **dual-licensed**:

- **Code** — everything under `src/`, `extension/`, `judge/`, and `tools/` — is licensed under the
  **Apache License 2.0** (see [LICENSE-code](LICENSE-code)).
- **Dataset and recorded artifacts** — everything under `dataset/` (task prompts,
  initial-state `S0` traces, ground-truth actions, and the UI-element / categorization
  CSVs) — is licensed under **Creative Commons Attribution-NonCommercial 4.0 International
  (CC BY-NC 4.0)** (see [LICENSE-dataset](LICENSE-dataset)).

### WebVoyager attribution

Parts of the agent are adapted from **WebVoyager** (He et al., 2024 —
https://github.com/MinorJerry/WebVoyager), licensed under Apache-2.0; our thanks to its
authors. The following files are **modified versions of WebVoyager source** and remain under
Apache-2.0 with its attribution:

- `src/run_with_replay.py`
- `src/agent/actions.py`
- `src/prompts.py`
- `src/utils.py`
- `src/utils_webarena.py`
- `src/api_utils.py`

Everything else is original to WebSP-Eval — including the record-and-replay state-reset engine
(`src/state_reset/`), the captcha handling, `src/agent/driver.py`, `src/agent/state.py`,
`src/agent/storage.py`, and the `extension/` recorder.

## Citation

@article{ramesh2026websp,
  title={WebSP-Eval: Evaluating Web Agents on Website Security and Privacy Tasks},
  author={Ramesh, Guruprasad Viswanathan and Nayak, Asmit and Siddique, Basieem and Fawaz, Kassem},
  journal={arXiv preprint arXiv:2604.06367},
  year={2026}
}
