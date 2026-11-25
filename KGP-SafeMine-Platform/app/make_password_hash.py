"""Create a bcrypt password hash for the login.   python -m app.make_password_hash

Prompts for the password (hidden), prints the hash and the [auth] block for .streamlit/secrets.toml. The password is never printed or saved.
"""
import getpass
import sys

import bcrypt

MIN_LEN, MAX_BYTES = 12, 72


def main() -> int:
    pw = getpass.getpass("New password (hidden): ")
    if getpass.getpass("Repeat password: ") != pw:
        print("Passwords do not match.")
        return 1
    if len(pw) < MIN_LEN:
        print(f"Use at least {MIN_LEN} characters.")
        return 1
    if len(pw.encode("utf-8")) > MAX_BYTES:
        print(f"Use at most {MAX_BYTES} bytes (bcrypt limit).")
        return 1
    h = bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt(12)).decode()
    print("\nPut this in .streamlit/secrets.toml (single quotes keep the $ signs literal):\n")
    print("[auth]\nusername = \"admin\"\n" + f"password_hash = '{h}'\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
