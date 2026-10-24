#!/usr/bin/env python3
"""Install development dependencies and create local storage directories."""

import subprocess
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["uv", "sync", "--frozen"], cwd=root, check=True)
    subprocess.run(["npm", "ci"], cwd=root, check=True)
    for directory in ("storage/channels", "storage/temp"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    print("Setup complete. Run npm run dev, then create your login in the browser.")


if __name__ == "__main__":
    main()
