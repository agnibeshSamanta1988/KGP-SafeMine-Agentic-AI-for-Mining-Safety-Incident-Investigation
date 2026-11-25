"""Login flow end to end (Streamlit AppTest, whole console): what an anonymous visitor can see, the transition to Home, errors, double submit,
expiry and logout. Credentials are a throwaway user created here; the real secrets file is never read."""
from __future__ import annotations

import time
from pathlib import Path

import bcrypt
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
UI = (ROOT / "app" / "ui.py").as_posix()
PW = "a-test-passphrase-1"


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    from app import auth
    cfg = {"username": "tester", "hash": bcrypt.hashpw(PW.encode(), bcrypt.gensalt(4)), "timeout_s": 1800.0, "max_attempts": 50, "lock_s": 60.0,
           "role": "Safety Analyst"}
    monkeypatch.setattr(auth, "load_config", lambda: (cfg, None))
    auth._clear_failures()
    calls = {"n": 0}
    real = auth.authenticate   # the login page's credential check

    def counting(u, p, c):
        calls["n"] += 1
        return real(u, p, c)
    monkeypatch.setattr(auth, "authenticate", counting)
    return calls


def _open() -> AppTest:
    at = AppTest.from_file(UI, default_timeout=120)
    at.run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]
    return at


def _login(at: AppTest, user="tester", pw=PW) -> AppTest:
    at.text_input[0].input(user)
    at.text_input[1].input(pw)
    [b for b in at.button if b.label == "Log in"][0].click()
    at.run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]
    return at


def _html(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown)


def test_anonymous_visitors_get_only_the_login_screen():
    at = _open()
    html = _html(at)
    assert "Welcome to KGP-SafeMine" in html and [b for b in at.button if b.label == "Log in"]
    assert len(at.sidebar) == 0                                               # no sidebar, navigation or footer
    assert "Mining Safety Intelligence Platform</h2>" not in html and "sb-brandrow" not in html and "hm-card" not in html   # nothing of the app
    assert not [b for b in at.button if b.key == "_auth_logout"]


def test_correct_credentials_lead_directly_to_home_in_one_run(_cfg):
    at = _login(_open())
    html = _html(at)
    assert "Mining Safety Intelligence Platform" in html and "hm-card" in html                   # Home content
    assert "Welcome to KGP-SafeMine" not in html and [t.key for t in at.text_input] == ["theme_dev"]   # the login form is gone (only the hidden device probe remains)
    assert len(at.sidebar) > 0 and [b for b in at.button if b.key == "_auth_logout"]
    assert _cfg["n"] == 1                                                                         # credentials were checked exactly once


def test_wrong_password_shows_a_clear_error_on_the_login_screen():
    at = _login(_open(), pw="not-the-password")
    assert any("Incorrect username or password" in e.value for e in at.error)
    assert [b for b in at.button if b.label == "Log in"] and len(at.sidebar) == 0
    assert "_auth_token" not in at.session_state


def test_empty_fields_are_rejected_without_a_check(_cfg):
    at = _open()
    [b for b in at.button if b.label == "Log in"][0].click()
    at.run()
    assert any("Enter your username and password" in e.value for e in at.error) and _cfg["n"] == 0


def test_a_double_submit_is_checked_and_counted_once(_cfg):
    from app import auth
    at = _open()
    at.text_input[0].input("tester")
    at.text_input[1].input("wrong-one")
    btn = [b for b in at.button if b.label == "Log in"][0]
    btn.click()
    at.run()
    [b for b in at.button if b.label == "Log in"][0].click()                  # the same submission again, straight away
    at.run()
    assert _cfg["n"] == 1 and len(auth._state()["fails"]) == 1                  # one check, one failure on record
    assert any("Incorrect username or password" in e.value for e in at.error)   # and the answer is still on screen


def test_an_expired_session_returns_to_the_login_with_a_notice():
    at = _login(_open())
    at.session_state["_auth_last_active"] = time.time() - 10_000
    at.run()
    assert not at.exception
    assert len(at.sidebar) == 0 and "_auth_token" not in at.session_state
    assert any("expired" in w.value for w in at.warning)


def test_logout_goes_straight_back_to_the_login_and_clears_the_session():
    at = _login(_open())
    at.session_state["keep"] = "chat"
    [b for b in at.button if b.key == "_auth_logout"][0].click()
    at.run()
    assert not at.exception and len(at.sidebar) == 0 and [b for b in at.button if b.label == "Log in"]
    assert "keep" not in at.session_state and "_auth_token" not in at.session_state


def test_a_forged_session_does_not_pass_the_guard():
    at = _open()
    at.session_state["_auth_user"] = "tester"
    at.session_state["_auth_token"] = "forged"
    at.session_state["_auth_last_active"] = time.time()
    at.run()
    assert len(at.sidebar) == 0 and [b for b in at.button if b.label == "Log in"]


def test_every_app_path_is_registered_for_the_login_so_deep_links_do_not_error():
    from app import nav
    paths = nav.url_paths()
    assert "dashboard" in paths and "settings" in paths and "home" not in paths
    assert all((Path(nav.V) / f"{p}.py").exists() for p in paths)


# ------------------------------------------------------------------ several accounts ([auth.users.<name>] in secrets.toml)
def test_a_second_account_can_log_in_and_shows_its_own_role(monkeypatch):
    from app import auth
    h2 = bcrypt.hashpw(b"second-passphrase-2", bcrypt.gensalt(4))
    cfg = {"username": "tester", "hash": bcrypt.hashpw(PW.encode(), bcrypt.gensalt(4)), "timeout_s": 1800.0, "max_attempts": 50,
           "lock_s": 60.0, "role": "Safety Analyst"}
    cfg["users"] = {"tester": {"hash": cfg["hash"], "role": "Safety Analyst"}, "second": {"hash": h2, "role": "Team member"}}
    assert auth.authenticate("second", "second-passphrase-2", cfg) == "second"
    assert auth.authenticate("tester", PW, cfg) == "tester"
    assert auth.authenticate("second", PW, cfg) is None                 # one account's password does not open another
    assert auth.authenticate("nobody", "second-passphrase-2", cfg) is None
    assert auth.check_credentials("second", "second-passphrase-2", cfg) is True


# ---- seamless hand-over: the full-screen curtain between the login and the first page -------------------------------------------------
def test_the_curtain_is_lifted_once_the_first_page_is_complete_and_never_returns():
    at = _login(_open())
    assert "sm-boot" not in _html(at)                      # lifted: the page behind it is complete
    assert "_auth_boot" not in at.session_state            # consumed: no later run shows it again
    at.run()                                               # an ordinary rerun
    assert not at.exception and "sm-boot" not in _html(at)


def test_the_curtain_runs_only_after_a_login_and_leaves_the_application_intact():
    at = _login(_open())
    at.session_state["_auth_boot"] = True                  # as if a login had just happened
    at.run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]
    assert "_auth_boot" not in at.session_state and "sm-boot" not in _html(at)
    assert "hm-card" in _html(at) and len(at.sidebar) > 0  # Home and sidebar are complete once it is gone


def test_the_curtain_markup_covers_the_whole_screen_and_lifts_by_itself_if_a_run_dies():
    from app import auth
    h = auth.boot_html()
    assert 'id="sm-boot"' in h and "position:fixed" in h and "inset:0" in h and 'role="status"' in h
    assert "z-index:2147483000" in h                       # above the sidebar, the header and any stale element
    assert "sm-boot-failsafe" in h and "forwards" in h     # fail-safe: never a permanent blank screen
    assert "prefers-reduced-motion" in h                   # accessibility: no animation for users who ask for none
    assert "Authenticating" not in h and "password" not in h.lower()


def test_an_anonymous_visitor_never_sees_the_curtain():
    at = _open()
    assert "sm-boot" not in _html(at) and "_auth_boot" not in at.session_state


# ---- the curtain survives an interrupted run (a second run starting before the first page was finished) ----------------------------------
def _boot_probe(finish: bool) -> AppTest:
    code = ("import streamlit as st\nfrom app import auth\n_b = auth.boot_begin()\nst.write('page')\n"
            + ("auth.boot_end(_b)\n" if finish else ""))
    return AppTest.from_string(code, default_timeout=30)


def test_an_interrupted_run_leaves_the_curtain_flag_so_the_next_run_raises_it_again():
    at = _boot_probe(finish=False)
    at.session_state["_auth_boot"] = 1
    at.run()
    assert "sm-boot" in _html(at) and at.session_state["_auth_boot"] == 2          # drawn, and NOT consumed: the run never completed
    at.run()                                                                         # the run that interrupted it
    assert "sm-boot" in _html(at) and at.session_state["_auth_boot"] == 3          # raises the curtain again instead of exposing stale content


def test_a_completed_run_lifts_the_curtain_and_consumes_the_flag():
    at = _boot_probe(finish=True)
    at.session_state["_auth_boot"] = 1
    at.run()
    assert "sm-boot" not in _html(at) and "_auth_boot" not in at.session_state


def test_a_run_that_keeps_dying_cannot_hold_the_curtain_for_ever():
    from app import auth
    at = _boot_probe(finish=False)
    at.session_state["_auth_boot"] = auth.BOOT_MAX_RUNS + 1
    at.run()
    assert "sm-boot" not in _html(at) and "_auth_boot" not in at.session_state


def test_the_device_theme_box_is_filled_before_the_page_so_no_second_run_is_needed():
    at = _login(_open())
    assert at.session_state["theme_dev"] in ("light", "dark")                       # the browser probe finds nothing to change


def test_no_part_of_the_login_screen_survives_a_successful_login():
    at = _login(_open())
    html = _html(at)
    assert "Welcome to KGP-SafeMine" not in html and "lg-foot" not in html and "lg-brand" not in html and "lg-welcome" not in html
    assert not [b for b in at.button if b.label == "Log in"]


# ---- exactly one login form: the form must keep its position whether or not a notice is shown above it ------------------------------------
def _flatten(node, out=None):
    out = [] if out is None else out
    for child in getattr(node, "children", {}).values():
        out.append(child)
        _flatten(child, out)
    return out


def _elements_before_the_form(at: AppTest) -> list[str]:
    seq = [getattr(n, "type", type(n).__name__) for n in _flatten(at.main)]
    assert "form" in seq, seq
    return seq[: seq.index("form")]


def test_the_login_form_keeps_its_position_with_and_without_a_notice():
    """Streamlit matches the previous run's elements to the new run's by position and keeps the old ones on screen until the run ends. A notice
    above the form (shown on one render only) used to shift the form by one place, so the old and the new form were both visible: two login forms."""
    plain = _elements_before_the_form(_open())
    at = AppTest.from_file(UI, default_timeout=120)
    at.session_state["_auth_notice"] = "You have been logged out."
    at.run()
    assert not at.exception
    with_notice = _elements_before_the_form(at)
    assert len(with_notice) == len(plain), (plain, with_notice)       # same number of elements above the form: it cannot move
    assert any("logged out" in w.value for w in at.warning)            # ...and the notice is still shown


def test_a_failed_login_after_a_notice_leaves_exactly_one_form_in_the_same_place():
    at = AppTest.from_file(UI, default_timeout=120)
    at.session_state["_auth_notice"] = "Your session expired after a period of inactivity. Please log in again."
    at.run()
    before = _elements_before_the_form(at)
    at = _login(at, pw="not-the-password")
    assert _elements_before_the_form(at) == before or len(_elements_before_the_form(at)) == len(before)
    assert len([n for n in _flatten(at.main) if getattr(n, "type", "") == "form"]) == 1
    assert any("Incorrect username or password" in e.value for e in at.error)
    assert not any("expired" in w.value for w in at.warning)           # the notice was shown once, not again
