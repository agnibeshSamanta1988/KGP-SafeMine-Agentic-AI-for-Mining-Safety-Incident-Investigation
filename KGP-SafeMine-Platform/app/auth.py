"""Password-protected login for the KGP-SafeMine console.

Call `require_login()` once in app/ui.py, before anything else is rendered: it shows the login page and stops the script until
the user has authenticated, so no page, chart or setting is ever built for an anonymous visitor (hiding the sidebar is NOT the
boundary: the script itself stops).

Credentials come from `.streamlit/secrets.toml` ([auth] username, password_hash) or the environment (AUTH_USERNAME,
AUTH_PASSWORD_HASH). The password is never stored: only a bcrypt hash. Generate one with:  python -m app.make_password_hash

Optional settings (secrets.toml [auth] or environment):
  timeout_minutes / AUTH_TIMEOUT_MINUTES   inactivity timeout, default 30
  max_attempts    / AUTH_MAX_ATTEMPTS      failed logins allowed per window before a lock-out, default 5
  lock_minutes    / AUTH_LOCK_MINUTES      lock-out length, default 5
  role            / AUTH_ROLE              label shown under the username in the sidebar, default "Authorised user" (display only)
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
import time

import bcrypt
import streamlit as st

HASH_RE = re.compile(r"^\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}$")
MAX_PASSWORD_BYTES = 72          # bcrypt ignores/rejects anything longer
WINDOW_S = 15 * 60               # failed attempts are counted over this window
SESSION_KEYS = ("_auth_user", "_auth_token", "_auth_nonce", "_auth_login_ts", "_auth_last_active", "_auth_boot")


# ------------------------------------------------------------------ configuration
def _setting(key: str, env: str, default: str = "") -> str:
    try:
        v = st.secrets.get("auth", {}).get(key)
    except Exception:  # noqa: BLE001  no secrets file at all
        v = None
    return str(v).strip() if v not in (None, "") else os.getenv(env, default).strip()


def _num(key: str, env: str, default: float) -> float:
    try:
        return float(_setting(key, env, str(default)))
    except ValueError:
        return default


def load_config() -> tuple[dict | None, str | None]:
    """(config, None) when usable, else (None, reason). Reasons never contain the credential values."""
    user, h = _setting("username", "AUTH_USERNAME"), _setting("password_hash", "AUTH_PASSWORD_HASH")
    if not user or not h:
        return None, "missing"
    if not HASH_RE.match(h):
        return None, "invalid_hash"
    role = _setting("role", "AUTH_ROLE", "Authorised user")[:40]
    return {"username": user, "hash": h.encode(),
            "timeout_s": max(1.0, _num("timeout_minutes", "AUTH_TIMEOUT_MINUTES", 30)) * 60,
            "max_attempts": max(1, int(_num("max_attempts", "AUTH_MAX_ATTEMPTS", 5))),
            "lock_s": max(1.0, _num("lock_minutes", "AUTH_LOCK_MINUTES", 5)) * 60,
            "role": role, "users": {user: {"hash": h.encode(), "role": role}, **_extra_users(user)}}, None


def _extra_users(primary: str) -> dict:
    """Further accounts from secrets.toml, one table per user (only a bcrypt hash is stored):
         [auth.users.alice]
         password_hash = '$2b$12$...'
         role = "Team member"
    Entries with a missing or malformed hash are ignored; the primary [auth] account cannot be overridden here."""
    try:
        raw = st.secrets.get("auth", {}).get("users", {}) or {}
    except Exception:  # noqa: BLE001  no secrets file
        return {}
    out = {}
    for name, entry in dict(raw).items():
        try:
            h = str(dict(entry).get("password_hash", "")).strip()
            role = str(dict(entry).get("role") or "Authorised user")[:40]
        except Exception:  # noqa: BLE001  not a table
            continue
        name = str(name).strip()
        if name and name != primary and HASH_RE.match(h):
            out[name] = {"hash": h.encode(), "role": role}
    return out


# ------------------------------------------------------------------ process-wide state (shared by all browser sessions)
@st.cache_resource
def _state() -> dict:
    return {"lock": threading.Lock(), "fails": [], "locked_until": 0.0, "secret": secrets.token_bytes(32),
            "dummy": bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt(12))}


def lock_remaining(now: float | None = None) -> int:
    s = _state()
    with s["lock"]:
        return max(0, int(s["locked_until"] - (now or time.time()) + 0.999))


def _record_failure(cfg: dict, now: float) -> None:
    s = _state()
    with s["lock"]:
        s["fails"] = [t for t in s["fails"] if now - t < WINDOW_S] + [now]
        if len(s["fails"]) >= cfg["max_attempts"]:
            s["locked_until"] = now + cfg["lock_s"]
            s["fails"] = []


def _clear_failures() -> None:
    s = _state()
    with s["lock"]:
        s["fails"] = []
        s["locked_until"] = 0.0


def authenticate(username: str, password: str, cfg: dict) -> str | None:
    """The account name on success, else None. Every configured username is compared in constant time (no early exit), then exactly
    one bcrypt check runs (against a dummy hash when no username matched or the password is unusable), so the response time does not
    reveal whether the username or the password was wrong, nor how many accounts exist."""
    users = cfg.get("users") or {cfg["username"]: {"hash": cfg["hash"]}}
    given = username.strip().encode("utf-8")
    found = None
    for name, entry in users.items():
        if hmac.compare_digest(given, name.encode("utf-8")):
            found = (name, entry["hash"])
    pw = password.encode("utf-8")
    usable = 0 < len(pw) <= MAX_PASSWORD_BYTES
    try:
        match = bcrypt.checkpw(pw if usable else b"x", found[1] if (found and usable) else _state()["dummy"])
    except ValueError:      # malformed stored hash
        return None
    return found[0] if (found and usable and match) else None


def check_credentials(username: str, password: str, cfg: dict) -> bool:
    return authenticate(username, password, cfg) is not None


# ------------------------------------------------------------------ session
def _token(user: str, login_ts: float, nonce: str) -> str:
    return hmac.new(_state()["secret"], f"{user}|{login_ts}|{nonce}".encode(), hashlib.sha256).hexdigest()


def _grant(user: str) -> None:
    ss, now = st.session_state, time.time()
    nonce = secrets.token_hex(16)
    ss["_auth_user"], ss["_auth_nonce"], ss["_auth_login_ts"], ss["_auth_last_active"] = user, nonce, now, now
    ss["_auth_token"] = _token(user, now, nonce)


def _valid_token() -> bool:
    ss = st.session_state
    try:
        return hmac.compare_digest(str(ss.get("_auth_token", "")), _token(ss["_auth_user"], ss["_auth_login_ts"], ss["_auth_nonce"]))
    except KeyError:
        return False


def logout(notice: str | None = None) -> None:
    """Drop everything this session holds (chat, analyses, settings widgets, auth keys), optionally leaving a message for the login page."""
    st.session_state.clear()
    if notice:
        st.session_state["_auth_notice"] = notice


# ------------------------------------------------------------------ UI
LOGIN_CSS = """
<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"], header[data-testid="stHeader"] { display: none !important; }
.stApp { background: linear-gradient(160deg, #0B2545 0%, #13315C 55%, #1b4276 100%); }
.block-container { max-width: 400px !important; padding: max(1rem, calc(50vh - 240px)) 1rem 1rem 1rem !important; }
.block-container > [data-testid="stVerticalBlock"] { gap: .55rem; }
.block-container [data-testid="stMarkdownContainer"] { margin-bottom: 0 !important; }
.lg-brand { display:flex; align-items:center; justify-content:center; margin: 0 0 .1rem 0; }
.lg-brand img { width: clamp(84px, 17vh, 120px); max-width: 40vw; height:auto; filter: drop-shadow(0 6px 14px rgba(0,0,0,.4)); }
.lg-sub { color:#F2A900; text-align:center; font-size:.74rem; letter-spacing:.14em; text-transform:uppercase; font-weight:700; margin-bottom:.15rem; }
.lg-welcome { color:#DCE6F5; text-align:center; font-size:.84rem; line-height:1.4; margin-bottom:.35rem; }
[data-testid="stForm"] { background:#fff; border:0; border-top:4px solid #F2A900; border-radius:12px; padding:1rem 1.2rem .85rem 1.2rem; box-shadow:0 14px 32px rgba(0,0,0,.33); }
[data-testid="stForm"] [data-testid="stVerticalBlock"] { gap: .6rem; }
[data-testid="stForm"] [data-testid="stTextInputRootElement"], [data-testid="stForm"] [data-baseweb="input"], [data-testid="stForm"] [data-baseweb="base-input"], [data-testid="stForm"] input { background:#F3F6FA !important; color:#0B2545 !important; -webkit-text-fill-color:#0B2545 !important; }
[data-testid="stForm"] [data-baseweb="input"] button, [data-testid="stForm"] [data-baseweb="input"] button:hover { background:#F3F6FA !important; color:#5B6B80 !important; }
[data-testid="stForm"] [data-testid="stTextInputRootElement"] button, [data-testid="stForm"] [data-testid="stTextInputRootElement"] svg { color:#5B6B80 !important; fill:#5B6B80 !important; }
[data-testid="stForm"] label p { color:#0B2545; font-weight:600; font-size:.82rem; }
[data-testid="stForm"] [data-testid="stWidgetLabel"] { margin-bottom: .1rem; min-height: 0; }
[data-testid="stForm"] button[kind="primaryFormSubmit"], [data-testid="stForm"] button[kind="secondaryFormSubmit"] { background:#0B2545; color:#fff; border:0; font-weight:700; width:100%; padding:.45rem; }
[data-testid="stForm"] button:hover { background:#F2A900; color:#0B2545; }
.lg-foot { color:#9FB3D1; text-align:center; font-size:.7rem; margin-top:.2rem; }
@media (max-height: 640px) { .block-container { padding-top: .8rem !important; } .block-container > [data-testid="stVerticalBlock"] { gap: .4rem; } .lg-welcome { display: none; } }
@media (max-width: 480px) { .block-container { padding-top: .8rem !important; } .lg-brand img { width: clamp(80px, 22vw, 104px); } }
</style>
"""


# ------------------------------------------------------------------ seamless login -> application hand-over
# Why a curtain: after a correct password the browser used to show, for a moment, the application's sidebar next to the greyed-out login form
# (Streamlit keeps the previous page's elements on screen until the new run has finished, and the sidebar is built before the page content).
# The hand-over is therefore covered by ONE full-screen panel in the login's own colours: it appears in the same render as the successful
# check, is the very first element of the authenticated run, and is removed only after the first page has been completely built. Nothing
# in between (login form, stale elements, half-built sidebar, blank screen) can be seen. It is shown only for this first run after a login.
BOOT_CSS = (
    "#sm-boot{position:fixed;inset:0;z-index:2147483000;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1.1rem;"
    "background:linear-gradient(160deg,#0B2545 0%,#13315C 55%,#1b4276 100%);color:#DCE6F5;font-family:'Source Sans Pro','Segoe UI',system-ui,sans-serif;"
    "animation:sm-boot-failsafe 0s linear 25s forwards}"
    "#sm-boot img{width:clamp(84px,17vh,120px);max-width:40vw;height:auto;filter:drop-shadow(0 6px 14px rgba(0,0,0,.4))}"
    "#sm-boot .sm-boot-t{color:#F2A900;font-size:.74rem;letter-spacing:.14em;text-transform:uppercase;font-weight:700}"
    "#sm-boot .sm-boot-s{font-size:.84rem;opacity:.85}"
    "#sm-boot .sm-boot-bar{width:150px;height:3px;border-radius:3px;background:rgba(255,255,255,.18);overflow:hidden}"
    "#sm-boot .sm-boot-bar i{display:block;height:100%;width:40%;border-radius:3px;background:#F2A900;animation:sm-boot-run 1.1s ease-in-out infinite}"
    "@keyframes sm-boot-run{0%{transform:translateX(-110%)}100%{transform:translateX(380%)}}"
    "@keyframes sm-boot-failsafe{to{opacity:0;visibility:hidden;pointer-events:none}}"   # if a run ever dies, the curtain lifts by itself
    "@media (prefers-reduced-motion:reduce){#sm-boot .sm-boot-bar i{animation:none;width:100%}}"
)


def boot_html() -> str:
    from app import brand
    return (f"<style>{BOOT_CSS}</style>"
            f'<div id="sm-boot" role="status" aria-live="polite" aria-label="Loading KGP-SafeMine">{brand.logo_img("login")}'
            '<div class="sm-boot-t">Mining Safety Intelligence Platform</div>'
            '<div class="sm-boot-s">Preparing your workspace</div><div class="sm-boot-bar"><i></i></div></div>')


BOOT_MAX_RUNS = 4   # a run that keeps dying must not hold the curtain for ever (the CSS fail-safe lifts it as well)


def boot_begin():
    """First call of the authenticated run: while the hand-over after a login is not finished, put the curtain up before anything else is drawn.
    Returns the placeholder to hand to boot_end(), or None (every later run, and anonymous visitors).

    The flag is NOT consumed here. It is consumed by boot_end(), which is reached only when a run completes. A run can be interrupted by a
    second one (the browser asks for a rerun while the first page is still being built); the interrupting run then raises the curtain again,
    instead of showing whatever the interrupted run left on screen."""
    ss = st.session_state
    n = int(ss.get("_auth_boot") or 0)
    if n <= 0:
        return None
    if n > BOOT_MAX_RUNS:
        ss.pop("_auth_boot", None)
        return None
    ss["_auth_boot"] = n + 1
    ph = st.empty()
    ph.markdown(boot_html(), unsafe_allow_html=True)
    return ph


def boot_end(ph) -> None:
    """Last call of a COMPLETED run: the page behind the curtain is whole, so lift it and the application appears all at once."""
    st.session_state.pop("_auth_boot", None)
    if ph is not None:
        ph.empty()


def _brand() -> None:
    from app import brand
    st.markdown(LOGIN_CSS + f'<div class="lg-brand">{brand.logo_img("login")}</div>'
                '<div class="lg-sub">Mining Safety Intelligence Platform</div>', unsafe_allow_html=True)


def _config_problem(reason: str) -> None:
    _brand()
    st.error("Sign-in is not available: authentication has not been set up correctly. Contact your administrator.")
    with st.expander("Administrator instructions"):
        st.markdown("Set a username and a bcrypt password hash in `.streamlit/secrets.toml` under `[auth]` (or the `AUTH_USERNAME` and "
                    "`AUTH_PASSWORD_HASH` environment variables), then restart the app. Create the hash with "
                    "`python -m app.make_password_hash`. See `docs/AUTH.md`." + ("  \nThe configured hash is not a valid bcrypt hash." if reason == "invalid_hash" else ""))


def _login_page(cfg: dict) -> None:
    """The login screen, drawn inside ONE container so that on success the whole screen can be taken away in a single step. Without that, the
    form stayed on screen (stale) until the first authenticated run had finished, re-styled by the application's CSS: that was the flicker."""
    shell = st.empty()
    with shell.container():
        granted = _login_form(cfg)
    if granted:
        st.session_state["_auth_boot"] = 1                # the authenticated run starts behind the curtain ...
        st.markdown(boot_html(), unsafe_allow_html=True)  # ... which goes up in this very render, above the login ...
        shell.empty()                                     # ... and nothing of the login screen is left on screen or in the browser
        st.rerun()


def _login_form(cfg: dict) -> bool:
    """Draw the form and check a submission. True only when the credentials were correct (the session has been granted)."""
    _brand()
    st.markdown('<div class="lg-welcome">Welcome to KGP-SafeMine. Please authenticate to access the Mining Safety Intelligence Platform.</div>',
                unsafe_allow_html=True)
    # The notice ("You have been logged out", "Your session expired") exists on ONE render only, so it must not move anything below it: Streamlit
    # keeps the previous run's elements on screen until the new run finishes and matches them by position. A conditional element above the form
    # shifted the form up by one place on the next run, and for as long as that run lasted (the password check) the old form and the new one were
    # both visible: two login forms. The slot below is always there, with or without a notice, so the form never changes position.
    notice_slot = st.empty()
    notice = st.session_state.pop("_auth_notice", None)
    if notice:
        notice_slot.warning(notice)
    wait = lock_remaining()
    with st.form("login", clear_on_submit=False):
        user = st.text_input("Username", autocomplete="username")
        pw = st.text_input("Password", type="password", autocomplete="current-password")   # Streamlit adds the show/hide toggle
        go = st.form_submit_button("Log in", type="primary", use_container_width=True, disabled=wait > 0)
    if wait > 0:
        st.error(f"Too many failed attempts. Try again in {max(1, -(-wait // 60))} minute(s).")
    elif go:
        if not user.strip() or not pw:
            st.error("Enter your username and password.")
        else:
            sub = hashlib.sha256(f"{user}|{pw}".encode()).hexdigest()
            last = st.session_state.get("_auth_last_sub")
            if last and last[0] == sub and time.time() - last[1] < 3:
                # the same submission arriving twice (double click): it was already checked and failed (a success would not be here),
                # so show the same answer without checking or counting it a second time
                st.error("Incorrect username or password.")
                st.markdown('<div class="lg-foot">Authorised use only. Sessions end after a period of inactivity.</div>', unsafe_allow_html=True)
                return False
            st.session_state["_auth_last_sub"] = (sub, time.time())
            with st.spinner("Authenticating securely …"):
                who = authenticate(user, pw, cfg)
                if who is None:
                    time.sleep(0.6)          # slows scripted guessing
            if who is not None:
                _clear_failures()
                _grant(who)
                return True
            _record_failure(cfg, time.time())
            if lock_remaining() > 0:
                st.rerun()                   # redraw at once with the form disabled and the lock-out message
            st.error("Incorrect username or password.")
    st.markdown('<div class="lg-foot">Authorised use only. Sessions end after a period of inactivity.</div>', unsafe_allow_html=True)
    return False


def _login_view() -> None:
    cfg, _ = load_config()
    if cfg is not None:
        _login_page(cfg)


def _problem_view() -> None:
    _config_problem(load_config()[1] or "missing")


def _gate(view, paths=()) -> None:
    """Show `view` as the ONLY content an anonymous visitor can reach, and stop. The login is a page of its own (not elements of the application's
    page), so the browser drops the whole login screen the moment the authenticated run starts: no leftover login form between the two. The
    application's own URL paths are registered too (all showing the login) so that a bookmarked deep link shows the login, not a 'page not found'."""
    def mk(name: str):
        def sign_in():
            view()
        sign_in.__name__ = f"sign_in_{name}"
        return sign_in
    pages = [st.Page(mk("main"), title="Sign in", url_path="login", default=True)]
    pages += [st.Page(mk(p), title="Sign in", url_path=p) for p in dict.fromkeys(paths) if p and p != "login"]
    st.navigation(pages, position="hidden").run()
    st.stop()


def require_login(paths=()) -> dict:
    """Central authentication guard. Returns the auth config for an authenticated, unexpired session; otherwise renders the login page
    (nothing of the application is built for an anonymous visitor) and stops the script. `paths`: the application's url paths."""
    cfg, problem = load_config()
    if cfg is None:
        _gate(_problem_view, paths)
    ss = st.session_state
    if ss.get("_auth_token"):
        if _valid_token() and ss.get("_auth_user") in (cfg.get("users") or {cfg["username"]: {}}):   # a removed account is signed out
            if time.time() - float(ss.get("_auth_last_active", 0)) <= cfg["timeout_s"]:
                ss["_auth_last_active"] = time.time()
                return cfg
            logout("Your session expired after a period of inactivity. Please log in again.")
        else:
            logout()
    _gate(_login_view, paths)


@st.fragment(run_every="30s")
def _expiry_watch(timeout_s: float) -> None:
    """Every 30 s: if the session has been idle past the limit, force a full rerun, which runs require_login() and logs out.
    This fragment never updates the activity time, so it cannot keep an idle session alive."""
    if time.time() - float(st.session_state.get("_auth_last_active", 0)) > timeout_s:
        st.rerun()


def render_sidebar(cfg: dict) -> None:
    """Compact user chip (initial, username, role) and the Log out button; plus the idle-expiry watcher."""
    from html import escape
    user = str(st.session_state.get("_auth_user", ""))
    role = escape(str(((cfg.get("users") or {}).get(user) or {}).get("role") or cfg.get("role") or "Authorised user"))
    st.markdown(f'<div class="sb-user" title="Signed in as {escape(user, quote=True)} ({role})"><div class="sb-avatar">{escape(user[:1].upper() or "?")}</div>'
                f'<div style="min-width:0"><div class="sb-uname">{escape(user)}</div><div class="sb-role">{role}</div></div></div>', unsafe_allow_html=True)
    if st.button("Log out", key="_auth_logout", icon=":material/logout:", use_container_width=True, help="End this session and clear its chat and analyses"):
        logout("You have been logged out.")
        st.rerun()
    _expiry_watch(cfg["timeout_s"])
