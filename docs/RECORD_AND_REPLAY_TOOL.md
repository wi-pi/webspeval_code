# Architecture: Record-and-Replay for Initial-State Management

WebSP-Eval puts each task relevant part of a website into a consistent **initial state (`S0`)** before the agent runs, so
different models are evaluated fairly. This is done with a two-stage record-and-replay system:

1. a Chrome **extension** (`extension/`) that records user interactions with high semantic
   fidelity, and
2. a Selenium **replay engine** (`src/state_reset/extension_reset.py`) that reconstructs those
   interactions and can deterministically force stateful elements ON/OFF.

## 1. Recording (the extension)

A content script (Manifest V3) injected into every page, including iframes.

**WebSP index (`data-websp-index`).** A deterministic DOM traversal (a custom `TreeWalker` that
descends into shadow roots) enumerates all focusable/interactive elements per WCAG criteria
(native interactive tags, non-negative `tabindex`, interactive ARIA roles like `switch`/`checkbox`/
`radio`, `contenteditable`, `onclick`+cursor), excluding disabled/hidden/`opacity:0` elements.
Each gets a sequential index stored as a JS property (`webspIndex`) and a `data-websp-index`
attribute. A continuous `MutationObserver` re-indexes (debounced ~500 ms) so dynamically injected
elements stay indexed. The WebSP index is a robust **last-resort** locator when DOM structure
changes between record and replay.

**Semantic capture.** For each interacted element the extension records: intrinsic attrs
(`id`/`name`/`class`, ARIA `role`/`aria-label`/`aria-checked`/…, `data-testid`/`data-cy`/
`data-automation`), form state (input type, value, checked, associated label), locators (CSS
selector path with `::shadow` markers, XPath, frame path), textual context (`innerText`,
`nearbyLabelText`, `parentTextContext`, heading text), and truncated `outerHTML`/`innerHTML`.

**Events.** Clicks are captured via parallel `mousedown`/`pointerdown`/`click` handlers (with
~500 ms timestamp dedup); `change` events for form controls and custom toggles (`role="switch"`,
`aria-checked`) with a short settle delay; `keydown` for keyboard-responsive elements. Shadow DOM
is handled via `event.composedPath()` and recursive `shadowRoot` traversal. Recording state is
held in the background service worker via `chrome.storage.local` so it survives navigations.

The extension exports a session as a structured JSON file (an ordered list of events, each with
the fields above) — this is what the replay engine consumes.

## 2. Replay (the Selenium engine)

`replay_events()` in `src/state_reset/extension_reset.py` processes the recorded events
sequentially. `load_json_file()` loads a session and fills `{{WEBSP_ACCOUNT_*}}` placeholders from
the environment before parsing (see the PII-templatization note below).

**Multi-tier element location.** For each event it tries locators in order of stability, e.g.:
shadow-DOM aria-label search → `data-testid`/`data-cy`/`data-automation` → `id` (with explicit
wait for SPA content) → `name` → `aria-label` → label-text association → option/button innerText →
CSS selector path (sanitizing invalid generated IDs) → overlay-trigger matching → **WebSP index**
as the final fallback. (There is also site-specific handling, e.g. Google Ad Center topic
switches.)

**Frame & OAuth handling.** Iframe context is resolved by id/name/source-segment/selector and
switched before each event; popup/OAuth flows (accounts.google.com, login.microsoftonline.com) are
detected and the driver switches to the popup automatically.

**Click & change processing.** Clicks verify recorded text (skip on mismatch), scroll into view,
and execute via Selenium click → JS `element.click()` → ActionChains, with longer waits after
`href` navigations. Change/toggle events read current state from `checked`/`aria-checked`/
`aria-pressed`/`aria-selected` (or parent label classes) and, if it differs from target, click or
JS-force-set the state (dispatching synthetic `input`/`change` events) with up to 3 retries.

**State determinism.** `replay_events(..., set_checked_state=...)`:
- `True` → force all toggle/checkbox/switch elements **ON**,
- `False` → force them **OFF**,
- `None` → replay the originally recorded states.

Elements already in the target state are skipped. This is how a single recorded trace yields both
the `ON` and `OFF` initial-state variants used in the dataset.

**Robustness.** Stale-element re-finding using accumulated DOM-change history (rolling ~50
changes), interaction dedup (~500 ms window), DOM-change clearing + WebSP re-indexing after
navigation, and popup detection after iframe interactions.

## 3. Verifying a trace replays (`src/state_reset_check.py`)

`src/state_reset_check.py` replays a **single** recorded trace in both `ON` and `OFF` states so you
can visually confirm the engine still reproduces the initial state on the live site — useful after a
site UI change, or to sanity-check a freshly recorded `S0` trace. It calls the same `replay_events`
the agent uses (no duplicated locator logic), and is run from the repo root:

```bash
# a shipped (templatized) trace — fills {{WEBSP_ACCOUNT_*}} from .env
python src/state_reset_check.py --templatized_trace \
  --session_json dataset/state_traces/Wolfram_task-7/<session-folder>/session-<...>.json

# your own recording (no placeholders)
python src/state_reset_check.py --session_json path/to/your/session-<...>.json
```

It opens the page and forces every toggle ON, then OFF, leaving the browser open briefly each time
so you can observe the result. Key flags:

- `--session_json` *(required)* — path (absolute or relative to the repo root) to one
  `session-*.json` trace.
- `--templatized_trace` — to substitute `{{WEBSP_ACCOUNT_*}}` from `.env`; use for the shipped
  `dataset/state_traces`, omit for your own recordings.
- `--state_mode on|off|both` (default `both`) — which state(s) to force.
- `--test_profile_dir_name` (default `test_profile`) — the `src/` Chrome profile to use.

## 4. PII templatization

The shipped `S0` traces in `dataset/state_traces/` have the sock-puppet identity replaced with
`{{WEBSP_ACCOUNT_EMAIL}}` / `{{WEBSP_ACCOUNT_USERNAME}}` / `{{WEBSP_ACCOUNT_NAME}}`. At load time
`load_json_file()` substitutes these from `WEBSP_ACCOUNT_*` in your `.env` (JSON-escaped), so the
fallback text locators carry your account's values. Unset variables are left as literal
placeholders; third-party emails captured incidentally from page content are `[redacted]`.

## 5. Key files

- Extension: `extension/{manifest,background,content,popup}.*`
- Replay engine: `src/state_reset/extension_reset.py`
  (`replay_events`, `load_json_file`, element-finding + state-enforcement helpers)
- State-reset dispatch + agent loop: `src/run_with_replay.py` (`execute_state_reset`, the agent loop)
- Verify a trace replays: `src/state_reset_check.py` (replays one trace ON/OFF; reuses `replay_events`)

## 6. Known limitations

Cross-origin iframe contents are inaccessible (browser security); WebSP indices and selector paths
are viewport-specific (replay at a different size may miss elements); async content that loads
between record and replay can cause misses; framework-generated random IDs reduce selector
stability (partly mitigated by the WebSP-index fallback); and server-side state not reflected in the
UI may be unreproducible. 

**Webpages often modify the UI and users may have to record new state replay
execution and login traces whenever such changes occur.**