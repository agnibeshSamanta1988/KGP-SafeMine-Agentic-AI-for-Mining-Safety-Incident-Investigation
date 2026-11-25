"""UI regression tests (Streamlit AppTest, no model call): the assistant page with a canned agent result."""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
VIEW = (ROOT / "app" / "views" / "assistant.py").as_posix()

SCRIPT = f"""
import sys
sys.path.insert(0, r"{ROOT.as_posix()}")
from app import lib
from safemine import config

import builtins
REVIEWS = builtins.SAFEMINE_TEST_REVIEWS = []
RESULT = {{"status": "answered", "answer": "Management failed to block the equipment [E1].", "turn_id": "turn-1",
          "evidence": [{{"id": "E1", "label": "2019 | x", "text": "management failed to block the equipment"}}],
          "trace": [], "latency_s": 1.0, "tool_calls": 1, "usage": {{"llm_calls": 1, "prompt_tokens": 1, "completion_tokens": 1}},
          "claim_map": [{{"sentence": "Management failed to block the equipment [E1].", "status": "supported", "citations": ["E1"], "issues": [],
                         "grounding": 1.0, "weak_support": False, "sources": [{{"id": "E1", "event_id": "2019/x"}}]}}],
          "verification_report": {{"claims": 1, "supported": 1, "unsupported": 0, "uncited": 0, "weak_support": 0, "removed": 0, "rounds": 1,
                                  "support_ratio": 1.0, "traceability": 1.0, "mean_grounding": 1.0}},
          "agent_trail": [{{"t": 0.0, "from": "supervisor", "to": "planner", "kind": "task", "action": "plan"}}]}}

class _Store:
    def set_review(self, turn_id, decision):
        REVIEWS.append((turn_id, decision)); return 1
class _Agent:
    store = _Store()
lib.ask = lambda q, sid, mode="grounded": dict(RESULT)
lib.get_agent = lambda: _Agent()
lib.ready = lambda: True
exec(open(r"{VIEW}", encoding="utf-8").read())
"""


def _app():
    at = AppTest.from_string(SCRIPT, default_timeout=60)
    for k, v in (("provider", "upgrad"), ("sleep_on", False), ("sleep_s", 1.0), ("temperature", 0.1)):
        at.session_state[k] = v
    return at


def test_review_click_on_a_fresh_answer_is_not_lost():
    """Regression: the buttons of a just-written answer used a different widget key than on the next rerun, so the click vanished."""
    at = _app()
    at.run()
    at.chat_input[0].set_value("What does 30 CFR 56.14211 require?").run()
    assert not at.exception
    [b for b in at.button if b.label == "Approve"][0].click()
    at.run()
    assert not at.exception
    # the script keeps the calls in the module global REVIEWS of the exec'd namespace: read it through a second run's side effect
    import builtins
    assert ("turn-1", "approve") in builtins.SAFEMINE_TEST_REVIEWS      # the decision reached the store
    assert any(b.label == "Approve" for b in at.button)                   # and the answer is still on screen


def test_answer_shows_verification_and_agent_panels():
    at = _app()
    at.run()
    at.chat_input[0].set_value("What does 30 CFR 56.14211 require?").run()
    labels = [e.label for e in at.expander]
    assert any("Verification detail" in x for x in labels) and any("Agent messages" in x for x in labels)
    assert not at.exception


# ------------------------------------------------------------------ password change tool
def test_set_password_updates_only_the_hash_and_keeps_the_file(tmp_path):
    """Regression: the login hash was never replaced (editing a text file does nothing); the tool must write a working hash in place."""
    import os
    import tomllib

    import bcrypt

    from app.set_password import check_password, update_secrets
    f = tmp_path / "secrets.toml"
    f.write_text('# keep me\n[auth]\nusername = "admin"\npassword_hash = \'$2b$12$OLDOLDOLDOLDOLDOLDOLDOLDOLDOLDOLDOLDOLDOLDOLDOLDOLDOLD\'\ntimeout_minutes = 30\nmax_attempts = 5\n')
    inode = os.stat(f).st_ino
    update_secrets(f, "a-brand-new-passphrase-9")
    cfg = tomllib.loads(f.read_text())["auth"]
    assert bcrypt.checkpw(b"a-brand-new-passphrase-9", cfg["password_hash"].encode())
    assert cfg["username"] == "admin" and cfg["timeout_minutes"] == 30 and cfg["max_attempts"] == 5      # nothing else touched
    assert "# keep me" in f.read_text() and os.stat(f).st_ino == inode                                  # comments kept, same file
    update_secrets(f, "another-passphrase-12", username="reviewer")
    assert tomllib.loads(f.read_text())["auth"]["username"] == "reviewer"
    assert check_password("short") and check_password("x" * 100) and check_password("long-enough-password") is None


def test_the_login_accepts_only_the_hash_in_the_file(tmp_path, monkeypatch):
    import bcrypt

    from app import auth
    from app.set_password import update_secrets
    f = tmp_path / "s.toml"
    f.write_text('[auth]\nusername = "admin"\npassword_hash = \'x\'\n')
    update_secrets(f, "the-new-password-123")
    import tomllib
    h = tomllib.loads(f.read_text())["auth"]["password_hash"]
    cfg = {"username": "admin", "hash": h.encode()}
    assert auth.check_credentials("admin", "the-new-password-123", cfg) is True
    assert auth.check_credentials("admin", "the-original-password", cfg) is False


# ------------------------------------------------------------------ logo
def test_the_logo_is_embedded_on_the_login_page_and_the_old_badge_is_gone():
    from app import brand
    at = AppTest.from_file((ROOT / "app" / "ui.py").as_posix(), default_timeout=60)
    at.run()
    html = " ".join(m.value for m in at.markdown)
    assert "data:image/png;base64," in html and 'alt="KGP SafeMine"' in html          # the new logo
    assert "lg-logo" not in html and 'class="lg-name"' not in html                     # the old amber text badge
    assert "Welcome to KGP-SafeMine" in html and "Mining Safety Intelligence Platform" in html
    assert all((brand.ASSETS / f).exists() for f in ("logo.png", "logo_sm.png", "favicon.png"))


def test_logo_files_are_small_enough_to_embed():
    from app import brand
    assert (brand.ASSETS / "logo_sm.png").stat().st_size < 150_000 and (brand.ASSETS / "logo.png").stat().st_size < 400_000
