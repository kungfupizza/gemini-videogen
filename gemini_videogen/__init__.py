"""
gemini-videogen — Idea to Video CLI powered by Google Veo3.

Loads .env automatically on import so GOOGLE_API_KEY is available
before any submodule tries to create a genai.Client.
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv() -> None:
    """Read a .env file in the current working directory (or any parent up to HOME)."""
    # First try cwd, then walk up looking for .env so the tool works from
    # subdirectories of the project root.
    search = [Path.cwd()]
    try:
        home = Path.home()
        p = Path.cwd()
        while p != home and p != p.parent:
            search.append(p)
            p = p.parent
    except Exception:
        pass

    for base in search:
        env_path = base / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
            break


_load_dotenv()
