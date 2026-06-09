# Recording Guide (login traces)

The agent replays a recorded **login trace** to sign into each login-required site before running
its tasks. We ship none of these (they would contain your credentials/session). Use the included
Chrome extension to record your own.

## 1. Load the extension

1. Open `chrome://extensions`.
2. Enable **Developer mode** (top right).
3. Click **Load unpacked** and select the `extension/` directory.

The popup lets you **start**, **name**, and **stop** a recording session; on stop it exports a
session JSON of the captured interactions.

## 2. Record a login

1. Sign **out** of the target site (so you capture the full sign-in).
2. Start a recording in the extension popup and name it (e.g. `Docker_login`).
3. Perform the normal sign-in (Google SSO or email+password — see
   [ACCOUNT_SETUP.md](ACCOUNT_SETUP.md) for each site's URL and auth type).
4. Stop the recording and save the exported JSON.

## 3. Register your traces (the login-files CSV)

The dataset ships **no** login paths — each login-required task's `login_click_file` is a per-site
placeholder, `<LOGIN_FILE_{site}>` (e.g. `<LOGIN_FILE_Wolfram>`). To plug in your own recordings:

1. Save each exported login trace somewhere stable, e.g. `login_traces/<Site>_login/…json`
   (`login_traces/` is gitignored, so your traces are never committed).
2. Open `dataset/login_files.csv` and fill the `login_file` column with the path to your trace for
   each site you'll run, e.g.:

   ```
   site,login_file
   Wolfram,login_traces/Wolfram_login/session_xxx/session-xxx.json
   ```

3. Run the one-time fill script from the repo root:

   ```bash
   python tools/fill_login_files.py
   ```

   It replaces every `<LOGIN_FILE_{site}>` placeholder in the dataset JSONLs (and
   `artifact_test.jsonl`) with your paths. Sites left blank keep their placeholder, so you only
   need to fill in the sites you intend to run.

## 4. Notes

- Login traces are loaded through the same engine as the state-reset traces, so any
  `{{WEBSP_ACCOUNT_*}}` placeholders are filled from `.env` at load time — but since you record
  login traces yourself with your own account, they will simply contain your real values.
- You can also use the extension to (re-)record **initial-state (`S0`)** traces if a site's UI has
  changed and a shipped trace no longer replays; export and point the relevant `replay_click_file`
  at your new recording.
- See [ARCHITECTURE.md](ARCHITECTURE.md) for what the extension captures and how replay matches it.
