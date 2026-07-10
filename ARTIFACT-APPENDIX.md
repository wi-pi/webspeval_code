# Artifact Appendix

Paper title: **WebSP-Eval: Evaluating Web Agents on Website Security and Privacy Tasks**

Requested Badge(s):
  - [x] **Available**
  - [x] **Functional**
  - [ ] **Reproduced**

These steps cover install, setup, and one self-contained functional test. Reproducing the
paper's full quantitative results (the whole 200-instance benchmark across backbones on live
sites) is out of scope and not requested.

## Description

This artifact accompanies the PETS 2026 paper *WebSP-Eval: Evaluating Web Agents on Website
Security and Privacy Tasks* (Guruprasad Viswanathan Ramesh, Asmit Nayak, Basieem Siddique,
and Kassem Fawaz; University of Wisconsin–Madison).

WebSP-Eval measures how well LLM-powered web agents perform *website security and privacy
tasks* (managing cookies, configuring privacy settings, revoking sessions, controlling
newsletter/marketing preferences, etc.) on **live websites tied to user accounts**.

Contents:
- `dataset/` — 200 task instances (138 tasks, 28 sites; WithNav / W/oNav variants) + ground
  truth + initial-state (`S0`) traces.
- `src/` — the web agent (adapted from WebVoyager) + the Selenium record-and-replay state-reset
  engine (`src/state_reset/`).
- `extension/` — Chrome MV3 recorder for login / state traces.
- `judge/` — automated MLLM judge (not used by the functional test).

### Security/Privacy and Ethical Concerns

- **The agent changes real account state** on live sites. Use a throwaway **sock-puppet**
  account, never a personal one. We ship **no accounts or login traces** — you create your own
  ([docs/ACCOUNT_SETUP.md](docs/ACCOUNT_SETUP.md)).
- **No PII is shipped.** The `S0` traces are templatized: identities are replaced by
  `{{WEBSP_ACCOUNT_*}}` placeholders filled from your local `.env` at replay time.
- **No malware or exploits**, and nothing disables host security.

This is not a human-subjects study (no participants, no IRB).

## Requirements

- **Hardware:** any laptop; network access; no GPU (a display, or `--headless` Chrome).
- **Software:** Python 3.10+, Google Chrome (stable), then `pip install -r requirements.txt`.
  Tested on macOS 15 / Ubuntu 24.04.3 with Python 3.10.18. ChromeDriver is auto-managed; no
  Docker (the agent drives a real Chrome under live login).
- **Model access:** use the **OpenRouter API key we provide in the submission portal** — set it
  as `OPENROUTER_API_KEY` in `.env`. No other model keys are needed.
- **Time / disk:** ~30–60 min setup (incl. one account + login trace); the test runs in a few
  minutes; under 1 GB total.

## Accessibility

Public GitHub repository: `https://github.com/wi-pi/webspeval_code` (evaluate the latest `main` commit). 

Archived on Zenodo: [doi:10.5281/zenodo.21292894](https://doi.org/10.5281/zenodo.21292894).

Project website:
https://wiscprivacy.com/webspeval.

## Setup

```bash
git clone https://github.com/wi-pi/webspeval_code.git
cd webspeval_code
conda create -n webspeval python=3.10 -y
conda activate webspeval
pip install -r requirements.txt
```

Then (full detail in [docs/INSTALL.md](docs/INSTALL.md) and
[docs/ACCOUNT_SETUP.md](docs/ACCOUNT_SETUP.md)): (Only Google and Wolfram account are enough for the artifact evaluation)

1. **`.env`** (blank template at the repo root): set `OPENROUTER_API_KEY` (from the portal) and
   your sock-puppet values `WEBSP_ACCOUNT_EMAIL` / `WEBSP_ACCOUNT_USERNAME` / `WEBSP_ACCOUNT_NAME`.
2. **Account + profile:** create a sock-puppet **Wolfram** account and put a Chrome profile
   signed into it at `src/test_profile/` (gitignored — you create it).
3. **Login trace:** load `extension/` unpacked in Chrome (`chrome://extensions` → Developer mode
   → *Load unpacked*), record a Wolfram login, and save it under `login_traces/`
   ([docs/RECORDING_GUIDE.md](docs/RECORDING_GUIDE.md)).
4. **Register it:** put the trace path in the `Wolfram` row of `dataset/login_files.csv`, then
   run `python tools/fill_login_files.py`.

Quick install check (no account needed): `python src/run_with_replay.py --help` prints the
options with no import errors.

## Functional Test

<!-- Artifact-review update (added for the rebuttal): a one-command alternative,
     setup_for_artifact_eval.sh, is now offered IN ADDITION TO the original manual command below.
     The previous manual instructions are unchanged; reviewers may use EITHER path, and both run the
     same Wolfram_task-7 ON/OFF functional test. -->

You can run the functional test **either** way — both produce the same result:

- **(A) One command (easiest):** after providing the prerequisites (`.env` with `OPENROUTER_API_KEY`
  + `WEBSP_ACCOUNT_EMAIL`, the `src/test_profile/` Chrome profile, and the Wolfram login trace), run
  `bash setup_for_artifact_eval.sh`. It creates the conda env, installs the pinned dependencies,
  registers the login trace, and runs the functional test below.
- **(B) Manual:** follow the Setup steps above, then run the command below.

Run from the repo root. `dataset/artifact_test.jsonl` holds `Wolfram_task-7_ON` and
`Wolfram_task-7_OFF` — the *same* task run from two opposite initial states
(`set_checked_state` true vs false), showing the replay engine sets the start state
deterministically.

```bash
python src/run_with_replay.py \
  --test_file dataset/artifact_test.jsonl \
  --model_type gemini \
  --api_model google/gemma-3-27b-it \
  --run_with_openrouter \
  --max_iter 20 \
  --max_attached_imgs 3 \
  --temperature 1 \
  --force_light_mode \
  --seed 42 \
  --output_dir outputs/ 2>&1 | tee -a outputs/artifact_test.log
```

**Expected:** for each task the agent (a) replays the Wolfram login and signs in, (b) replays
the `S0` trace to set the newsletter checkboxes to the ON/OFF baseline, (c) performs the
requested toggles, and (d) writes a trajectory (screenshots, step log, result JSON) to
`outputs/`. Both tasks complete with no setup or replay errors.

## Limitations

- **Live-site drift** — selectors and layouts change; a task may need its `S0` trace re-recorded.
- **Region** — cookie/privacy UIs differ by jurisdiction (GDPR/CCPA).
- **Accounts and traces are not shipped** (for ethics), so exact outcomes depend on your own
  account — hence Functional, not Reproduced.
- **Model availability** — swap models via `--api_model` if one is deprecated.

## Reusability

The record-and-replay engine and extension generalize to any web-agent benchmark that needs a
deterministic initial state on live, account-bound sites: new tasks are added as JSONL rows and
new model providers in `src/api_utils.py`.


## Note

A coding agent was used in preparing this artifact and its documentation from the
development version of the code used in the paper. The authors reviewed all the steps
— including the code, dataset, and documentation — for correctness and for the removal
of PII.
