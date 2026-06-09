# Installation

## Requirements

- **Python 3.10+**
- **Google Chrome** (recent stable).
  - Normal tasks: ChromeDriver is managed automatically by `webdriver-manager`.
  - Captcha tasks (Moodle): use `undetected-chromedriver`, pinned in `src/run_with_replay.py` to
    Chrome major version **144** (`uc.Chrome(..., version_main=144)`). Match your installed Chrome
    major version or edit that value. (We used version 144 for running tasks in the paper)

## Python dependencies

```bash
conda create -n webspeval python=3.10 -y
conda activate webspeval
pip install -r requirements.txt
```

Key pins: `selenium==4.15.2`, `pillow==10.1.0`. Also installed: `undetected-chromedriver`,
`selenium-stealth`, `webdriver-manager`, `python-dotenv`, and the model SDKs
(`openai`, `anthropic`, `google-genai`, `azure-ai-inference`/`azure-identity`/`azure-core`),
plus `huggingface_hub`, `datasets`, `boto3`, `tqdm`, `numpy`, `httpx`.

## Environment (`.env`)

A blank `.env` ships at the repo root — open it and fill what you need. Only the model providers you actually run need to be set; a selected provider with missing keys errors at startup.

| Group | Vars |
|---|---|
| OpenAI / Azure (GPT-5.x) | `OPENAI_API_KEY` (if direct OpenAI endpoint), and set both `AZURE_OPENAI_KEY` + `ENDPOINT_URL` for Azure Endpoints |
| Google Gemini | `GEMINI_API_KEY` (for AI studio endpoint) *or* `VERTEX_AI_LOCATION` + `VERTEX_AI_PROJECT_ID` for vertex endpoints |
| OpenRouter (e.g. Gemma) | `OPENROUTER_API_KEY` |
| Your sock-puppet account | `WEBSP_ACCOUNT_EMAIL`, `WEBSP_ACCOUNT_USERNAME`, `WEBSP_ACCOUNT_NAME` | (Please use consistent user name across all accounts)
| Code-hosting state reset | `HF_TOKEN`, `HF_USERNAME`, `GITHUB_TOKEN`, `GITHUB_USERNAME` |
| Optional captcha alerts | `NTFY_TOPIC_URL` |

The `WEBSP_ACCOUNT_*` values are substituted into the shipped `S0` traces for setting task initial state (which carry
`{{WEBSP_ACCOUNT_*}}` placeholders) at replay time — see [ACCOUNT_SETUP.md](ACCOUNT_SETUP.md).

## Chrome profiles (user-supplied)

Provide two Chrome user-data profiles, each **signed into your sock-puppet Google account**
(gitignored — you create them):

- `src/test_profile/` — used by all normal tasks.
- `src/test_profile_captcha/` — used by test profile with cloudflare captcha solver support. (Just for Moodle, please perform the first time login manually. This ensures no captcha during the task. Before the task a login trace is replayed to login to the account)

The agent copies a fresh temporary profile from these for each run.

## Notification system (optional for Moodle)

Long runs can hit reCAPTCHA / Cloudflare walls that need a manual solve. If you set
`NTFY_TOPIC_URL` in `.env` to a full webhook URL (e.g. an ntfy.sh topic
`https://ntfy.sh/<your-topic>`), the agent pushes an alert when it detects one and pauses for you
to solve it. Leave it blank to disable. (Used by `src/utils.py` and `src/state_reset/utils.py`.)

## Running

**Always run from the repository root** so the dataset's relative trace paths
(`dataset/state_traces/…`, `login_traces/…`) resolve:

```bash
python src/run_with_replay.py \
  --test_file dataset/tasks_without_navigation.jsonl \
  --api_model gemini-2.5-pro \
  --output_dir outputs/
```

Valid `--api_model` values:

- Gemini: `gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-3-pro-preview`, `gemini-3.1-pro-preview`, `gemma-3-27b-it`
- Claude: `claude-sonnet-4-5@20250929`, `claude-haiku-4-5@20251001`
- OpenAI: `gpt-5.1`, `gpt-5-mini`

Useful flags: `--web_names` / `--skip_web_names` (filter sites), `--task_id`, `--max_iter`,
`--max_task_time`, `--temperature`, `--text_only` (accessibility-tree mode), `--headless`,
`--run_gpt_with_azure`, `--run_with_openrouter`, `--test_profile_dir_name`, `--resume`.
Run `python src/run_with_replay.py --help` for the full list.
