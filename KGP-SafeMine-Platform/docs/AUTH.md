# Login (password protection)

The whole console sits behind a login. `app/ui.py` calls `auth.require_login()` first; until it succeeds the script stops, so no page,
chart or setting is built. Direct links such as `/settings` show the login page too.

## First start

There is no default account. Before the first start, copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`, create a bcrypt
hash with `python -m app.make_password_hash` (see "Change the username or password" below) and paste it in. Without a valid hash the
login page shows an error and the console does not open.

## Change the password (easiest)

```powershell
..\.venv\Scripts\python -m app.set_password          # asks twice, hidden; add --user NAME to rename the user too
docker compose up -d --force-recreate                # applies it (a running container may still hold the old file)
```

Check it worked: log in with the new password, and confirm the old one is rejected. `.streamlit/secrets.toml` should show a new "last
modified" time.

## Change the username or password

1. Create a hash (the password is typed hidden and is never printed or stored; use 12+ characters):
   ```powershell
   ..\.venv\Scripts\python -m app.make_password_hash
   ```
2. Paste the printed block into `.streamlit/secrets.toml` (copy `secrets.toml.example` if the file does not exist):
   ```toml
   [auth]
   username = "admin"
   password_hash = '$2b$12$...'      # keep the single quotes
   ```
3. Restart the app. No source code changes are needed.

Environment variables work instead of the file: `AUTH_USERNAME`, `AUTH_PASSWORD_HASH` (in `.env`, or the shell). In Docker Compose
use `secrets.toml`: it is mounted read-only into the container (compose does not treat `$` in `.env` values safely).

| Setting (`[auth]` key / environment variable) | Default | Meaning |
|---|---|---|
| `timeout_minutes` / `AUTH_TIMEOUT_MINUTES` | 30 | log out after this much inactivity |
| `max_attempts` / `AUTH_MAX_ATTEMPTS` | 5 | failed logins in 15 minutes before a lock-out |
| `lock_minutes` / `AUTH_LOCK_MINUTES` | 5 | lock-out length |
| `role` / `AUTH_ROLE` | Authorised user | label shown under the username in the sidebar footer (display only, grants nothing) |

## How it behaves

- **Passwords:** only a bcrypt hash is stored. Checks use bcrypt plus a constant-time username comparison, and a bcrypt check always runs,
  so timing does not reveal whether the username or the password was wrong. Both give the same message.
- **Sessions:** kept in Streamlit's server-side session state with a signed token that is re-checked on every page run. Logging out clears
  all of the session (chat, analyses, settings fields) and returns to the login page.
- **Login to Home transition:** `require_login()` is the one guard. An anonymous visitor only ever reaches the login, which is a Streamlit page
  of its own (also registered under each application URL, so a bookmarked deep link shows the login, not "page not found"). After a correct
  password the session is granted and one rerun starts the application, so the browser swaps the login for the application in one step with
  no leftover login form. A submission that arrives twice (double click) is checked and counted once. After login you land on the page the
  URL asked for, or on Home from the bare address.
- **Seamless hand-over (no flicker):** the login screen is drawn inside one container. On a correct password the session is granted, a full-screen
  "Preparing your workspace" curtain (the login's own navy) is drawn **above** the login, the login container is emptied in the same render, and
  `st.rerun()` starts the authenticated run, whose first element is the curtain again. The curtain is lifted by the last line of `app/ui.py`
  (`auth.boot_end`), which only a **completed** run reaches. If a run is interrupted by another one (the browser asking for a rerun while the first
  page is still being built), the flag `_auth_boot` is still set and the next run raises the curtain again, so the user never sees a stale login
  form or a half-built sidebar. The flag allows at most 4 runs and the curtain has a CSS fail-safe that lifts it after 25 s. The device-theme
  box is filled before the page is drawn, so the browser probe no longer causes an extra run right after login. No `time.sleep()` is used for any of this.
- **Refresh:** reloading the browser tab starts a new Streamlit session, so you must log in again. This is by design (nothing is
  stored in the browser that could be reused).
- **Inactivity:** a background check every 30 s logs out an idle tab; any click that reruns the page counts as activity.
- **Brute force:** after `max_attempts` failures the login is locked for everyone for `lock_minutes` (the app has one shared account,
  so the lock is global; a determined attacker can therefore also lock you out briefly).
- **Missing or invalid configuration:** the app refuses to open and shows a generic message; credentials are never printed or logged.

## Not covered

- The REST API (`app/api.py`, port 8000) has **no login**. Keep it on localhost, or put it behind an authenticating proxy.
- One shared account; no roles or per-user history.
- Passwords travel unencrypted over plain `http://`. For anything beyond localhost, serve over HTTPS (reverse proxy such as Caddy or nginx)
  and consider a real identity provider (SSO / OAuth2 proxy) in front of the app.
- Never commit `.streamlit/secrets.toml` or `.env`; both are in `.gitignore`, and `secrets.toml` is excluded from the Docker image.
