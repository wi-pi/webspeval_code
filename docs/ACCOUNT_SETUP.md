# Account Setup

WebSP-Eval runs on **live websites tied to user accounts**. For ethical reasons the artifact
**does not contains accounts used in the paper and corresponding login traces** — you must create your own *sock-puppet* accounts (throwaway
accounts with non-real, unverifiable details) and record your own login traces.

## 1. Create a primary Google account

Most sites authenticate via **Google SSO**. Create one sock-puppet Google account and use it for
Single Sign-On wherever a site offers it. Creating it follows the normal Google account sign-up
process (https://accounts.google.com/signup) — use throwaway, non-real details. Sign your Chrome
profiles into this account (see [INSTALL.md](INSTALL.md) → *Chrome profiles*; you can use
`python src/selenium_browser_run.py --use_extension` to open the profile and sign in).

## 2. Set your account identity in `.env`

The shipped `S0` traces~(initial state for the tasks) reference your account via placeholders that are filled at replay time:

```
WEBSP_ACCOUNT_EMAIL=you@example.com      # your sock-puppet Google email
WEBSP_ACCOUNT_USERNAME=yourhandle        # your handle / username on the sites
WEBSP_ACCOUNT_NAME=Your Name             # display name (only if a trace needs it)
```

## 3. Create per-site accounts and record login traces

For the **login-required sites** below, create an account (via Google SSO or email+password as
indicated) and record a login trace with the extension (see [RECORDING_GUIDE.md](RECORDING_GUIDE.md)).
The **`ext`** column mirrors the dataset's `login_with_extension` flag: `yes` means that **while
running the task**, the login step replays the login trace with the recorder extension loaded (some
sites need its element indexing for the login to replay reliably); `–` runs the login without it.
It does not change how you record the trace — always record with the extension.

To record a login trace, run `python src/selenium_browser_run.py --use_extension` (opens Chrome
with the recorder loaded), go to the site's **Login URL** from the table, start a recording in the
extension popup, perform the login steps, then stop and save the trace (see
[RECORDING_GUIDE.md](RECORDING_GUIDE.md)).

| Website | Auth type | Login URL | ext |
|---|---|---|---|
| Airbnb | email + password | https://www.airbnb.com/login | yes |
| Amazon | email + password | https://www.amazon.com/ | yes |
| Coursera | Google SSO | https://www.coursera.org/login | – |
| Docker | Google SSO | https://www.docker.com/ | – |
| Duolingo | Google SSO | https://www.duolingo.com/log-in | yes |
| GitHub | Google SSO | https://github.com/login | yes |
| Goal | Google SSO | https://www.goal.com/en-us/login | – |
| Goodreads | Google SSO | https://www.goodreads.com/ | – |
| Grammarly | Google SSO | https://www.grammarly.com/signin | yes |
| HuggingFace | email + password | https://huggingface.co/ | – |
| Moodle | Google SSO | https://moodle.org/login/index.php | yes |
| OldReddit | Google SSO | https://old.reddit.com/ | – |
| OpenStreetMap | Google SSO | https://www.openstreetmap.org/login | – |
| Steam | Google SSO | https://store.steampowered.com/login/ | yes |
| Twitch | Google SSO | https://www.twitch.tv/login | yes |
| USAToday | email + password | https://login.usatoday.com/ | – |
| Wattpad | Google SSO | https://www.wattpad.com/ | yes |
| Wolfram | email + password | https://account.wolfram.com/login/oauth2/sign-in | – |

**Sites without a recorded login trace** (`login: false` in the dataset):

- **No account needed** (cookie-consent tasks): Al Jazeera, AllRecipes, BBC, IKEA, NVIDIA, Shein.
- **Authenticate via your base Google profile** (no separate trace; your Chrome profile must be
  signed into Google): GoogleAdCenter, Pinterest, Quora, Reddit.

## 4. Code-hosting tasks (API-based state reset)

Some GitHub / HuggingFace tasks set up their initial state via the official APIs (e.g. repo
visibility, access tokens). Create your own tokens and set `GITHUB_TOKEN`/`GITHUB_USERNAME` and
`HF_TOKEN`/`HF_USERNAME` in `.env`. You may also need to create the referenced empty repos under
your account.

## 5. Profiles

See [INSTALL.md](INSTALL.md) for `src/test_profile/` and `src/test_profile_captcha/`. Both must be
signed into your sock-puppet Google account before running.

> Use throwaway accounts only, respect each site's Terms of Service, and never put real personal
> information into these accounts.
