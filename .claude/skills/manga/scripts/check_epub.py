# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "jdk4py>=21",
# ]
# ///
"""EPUB を W3C 公式の EPUBCheck で検証する（Java のインストール不要）。

使い方:
    uv run check_epub.py <EPUB ファイル>

初回だけ EPUBCheck を ~/.cache/mangakun/ にダウンロードする。
エラーが無ければ終了コード 0、あれば 1。
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

import jdk4py

VERSION = "5.4.0"
CACHE = Path.home() / ".cache" / "mangakun"
JAR = CACHE / f"epubcheck-{VERSION}" / "epubcheck.jar"
URL = f"https://github.com/w3c/epubcheck/releases/download/v{VERSION}/epubcheck-{VERSION}.zip"


def ensure_jar() -> Path:
    if not JAR.exists():
        print(f"EPUBCheck {VERSION} をダウンロードしています…")
        CACHE.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(URL) as r:
            zipfile.ZipFile(io.BytesIO(r.read())).extractall(CACHE)
    return JAR


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    epub = Path(sys.argv[1])
    report = CACHE / "last_report.json"
    jar = ensure_jar()
    subprocess.run([str(jdk4py.JAVA), "-jar", str(jar), str(epub), "--json", str(report)],
                   capture_output=True)
    data = json.loads(report.read_text(encoding="utf-8"))
    msgs = [m for m in data.get("messages", []) if m.get("severity") in ("FATAL", "ERROR", "WARNING")]
    for m in msgs:
        locs = ", ".join(f"{loc.get('path')}:{loc.get('line')}" for loc in m.get("locations", [])[:3])
        print(f"{m['severity']} {m['ID']}: {m['message']} ({locs})")
    errors = sum(1 for m in msgs if m["severity"] in ("FATAL", "ERROR"))
    warnings = len(msgs) - errors
    print(f"EPUBCheck: エラー {errors} 件 / 警告 {warnings} 件")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
