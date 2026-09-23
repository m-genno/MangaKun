# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "jdk4py>=21",
# ]
# ///
"""EPUB を W3C 公式の EPUBCheck で検証し、Kindle Previewer 4 があれば KDP と同じ変換も試す。
Java のインストールは不要（uv が自動で用意する）。

使い方:
    uv run check_epub.py <EPUB ファイル>

初回だけ EPUBCheck を ~/.cache/mangakun/ にダウンロードする。
エラーが無ければ終了コード 0、あれば 1。
"""

from __future__ import annotations

import csv
import io
import json
import shutil
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


def find_kindle_previewer() -> Path | None:
    """Kindle Previewer 4 のコマンドライン版を探す（無ければ None）。"""
    found = shutil.which("kindlepreviewer4")  # Windows ではストアアプリのエイリアスとして登録される
    if found:
        return Path(found)
    if sys.platform == "darwin":
        cands = sorted(Path("/Applications").glob("Kindle Previewer*.app/Contents/MacOS/*"))
        cands = [c for c in cands if "cli" in c.name.lower()]
        return cands[-1] if cands else None
    return None


def kindle_convert(epub: Path) -> bool | None:
    """Kindle Previewer で KDP と同じ変換を試す。成功 True / 失敗 False / 未インストール None。"""
    cli = find_kindle_previewer()
    if not cli:
        print("Kindle Previewer 4 が見つからないため、Kindle 変換の確認は省略しました")
        return None
    if not str(epub.resolve()).isascii():
        print("Kindle 変換: 失敗（保存場所に全角文字が含まれているため Kindle Previewer が開けません）")
        return False
    out = CACHE / "kindle_check"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)  # 出力先は既存のフォルダでないと受け付けない
    subprocess.run([str(cli), str(epub.resolve()), "--convert", "--output", str(out), "--locale", "ja"],
                   capture_output=True, timeout=600)
    summary = out / "Summary_Log.csv"
    if not summary.exists():
        print("Kindle 変換: 失敗（ログが出力されませんでした）")
        return False
    rows = list(csv.DictReader(summary.read_text(encoding="utf-8-sig").splitlines()))
    ok = bool(rows) and rows[0].get("Conversion Status") == "Success"
    print(f"Kindle 変換: {'成功' if ok else '失敗'}（エラー {rows[0].get('Error Count', '?') if rows else '?'} 件）")
    if rows and rows[0].get("Log File Path") and Path(rows[0]["Log File Path"]).exists():
        # 列名は --locale で変わる（ja なら「タイプ」「内容紹介」）ので位置で読む
        for r in list(csv.reader(Path(rows[0]["Log File Path"]).read_text(encoding="utf-8-sig").splitlines()))[1:]:
            print(f"  {' / '.join(r)}")
    return ok


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
    kindle_ok = kindle_convert(epub)
    sys.exit(1 if errors or kindle_ok is False else 0)


if __name__ == "__main__":
    main()
