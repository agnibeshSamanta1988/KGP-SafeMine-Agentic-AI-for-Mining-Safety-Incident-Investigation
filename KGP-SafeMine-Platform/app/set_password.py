"""Change the console password in one step.   python -m app.set_password   [--user NEWNAME]

Asks for the new password twice (typed hidden, never printed or stored), writes only its bcrypt hash into .streamlit/secrets.toml, and
leaves every other setting in the file alone. The file is rewritten IN PLACE (same file, not a replacement): a container that has the file
mounted keeps seeing it, though restarting with `docker compose up -d --force-recreate` is still the safe way to apply the change.
"""
from __future__ import annotations

import argparse
import getpass
import re
import sys
from pathlib import Path

import bcrypt

SECRETS = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"
MIN_LEN, MAX_BYTES = 12, 72


def check_password(pw: str) -> str | None:
    """None if the password is acceptable, else the reason."""
    if len(pw) < MIN_LEN:
        return f"Use at least {MIN_LEN} characters."
    if len(pw.encode("utf-8")) > MAX_BYTES:
        return f"Use at most {MAX_BYTES} bytes (bcrypt limit)."
    return None


def update_secrets(path: Path, password: str, username: str | None = None) -> None:
    """Write the bcrypt hash of `password` (and optionally a new username) into the [auth] block of `path`, keeping all other lines."""
    h = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(12)).decode()
    text = path.read_text(encoding="utf-8") if path.exists() else "[auth]\n"
    if "[auth]" not in text:
        text += "\n[auth]\n"
    line = f"password_hash = '{h}'"          # single quotes keep the $ signs literal in TOML
    if re.search(r"^\s*password_hash\s*=", text, re.M):
        text = re.sub(r"^\s*password_hash\s*=.*$", lambda m: line, text, count=1, flags=re.M)
    else:
        text = re.sub(r"^\[auth\]\s*$", lambda m: "[auth]\n" + line, text, count=1, flags=re.M)
    if username:
        if re.search(r"^\s*username\s*=", text, re.M):
            text = re.sub(r"^\s*username\s*=.*$", lambda m: f'username = "{username}"', text, count=1, flags=re.M)
        else:
            text = re.sub(r"^\[auth\]\s*$", lambda m: f'[auth]\nusername = "{username}"', text, count=1, flags=re.M)
    with open(path, "w", encoding="utf-8", newline="\n") as f:     # in place: same file, not a rename
        f.write(text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", help="also change the username")
    a = ap.parse_args()
    pw = getpass.getpass("New password (hidden): ")
    if getpass.getpass("Repeat password: ") != pw:
        print("Passwords do not match. Nothing was changed.")
        return 1
    why = check_password(pw)
    if why:
        print(why + " Nothing was changed.")
        return 1
    update_secrets(SECRETS, pw, a.user)
    print(f"Done: the new password hash is saved in {SECRETS}.")
    print("Apply it now:   docker compose up -d --force-recreate     (if you run without Docker, restart streamlit)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
