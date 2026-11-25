"""The KGP SafeMine logo, embedded as data so it needs no file serving (works the same locally and in Docker)."""
from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"
FAVICON = str(ASSETS / "favicon.png")


@lru_cache(maxsize=4)
def _data_uri(name: str) -> str:
    return "data:image/png;base64," + base64.b64encode((ASSETS / name).read_bytes()).decode()


def logo_img(kind: str = "sidebar", width: int | None = None) -> str:
    """<img> tag of the logo. kind: 'sidebar' (small file) or 'login' (large file)."""
    f = "logo_sm.png" if kind == "sidebar" else "logo.png"
    w = f' style="width:{width}px"' if width else ""
    return f'<img class="sm-logo" src="{_data_uri(f)}" alt="KGP SafeMine"{w}>'
