# /// script
# requires-python = ">=3.11"
# ///
"""ファイルやフォルダを OS 標準のアプリで開く（Windows: 既定のアプリ / Mac: open）。

使い方:
    uv run open_file.py <パス> [<パス> ...]
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    paths = [Path(a) for a in sys.argv[1:]]
    if not paths:
        print(__doc__)
        sys.exit(2)
    missing = [p for p in paths if not p.exists()]
    for p in missing:
        print(f"見つかりません: {p}", file=sys.stderr)
    for p in paths:
        if not p.exists():
            continue
        if sys.platform == "win32":
            os.startfile(p.resolve())  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["open", str(p)], check=False)
        else:
            subprocess.run(["xdg-open", str(p)], check=False)
        print(f"開きました: {p}")
    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
