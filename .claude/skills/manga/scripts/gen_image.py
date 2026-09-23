# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "google-genai>=1.40",
#     "pillow>=11",
#     "python-dotenv>=1.0",
#     "pyyaml>=6",
# ]
# ///
"""Gemini 画像モデルで1枚生成して保存する。

使い方:
    uv run gen_image.py --prompt "..." --out panels/p01_01.png [--ref characters/hana.png ...] [--aspect 3:4]

- 出力先に同名ファイルがあれば上書きせず、p01_01_v2.png のように番号を付けて保存する
- 保存したパスを標準出力の最終行に `SAVED: <path>` と出す
- --log を付けると、生成1回ごとに JSON 1行を追記する（枚数・費用の集計用）
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types
from PIL import Image

SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = SKILL_DIR.parents[2]
ASPECTS = ["1:1", "3:2", "2:3", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]
RETRY_STATUS = {429, 500, 502, 503, 504}


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def load_config() -> dict:
    with open(SKILL_DIR / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def next_free_path(out: Path) -> Path:
    """out が空いていればそのまま、使われていれば _v2, _v3 ... の空いている名前を返す。"""
    if not out.exists():
        return out
    n = 2
    while True:
        cand = out.with_name(f"{out.stem}_v{n}{out.suffix}")
        if not cand.exists():
            return cand
        n += 1


def generate(client: genai.Client, model: str, contents: list, config: types.GenerateContentConfig):
    for attempt in range(3):
        try:
            return client.models.generate_content(model=model, contents=contents, config=config)
        except errors.APIError as e:
            if e.code in RETRY_STATUS and attempt < 2:
                wait = 10 * (attempt + 1)
                print(f"API エラー {e.code}。{wait}秒後に再試行します", file=sys.stderr)
                time.sleep(wait)
                continue
            fail(f"API エラー {e.code}: {e.message}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    cfg = load_config()["image"]

    p = argparse.ArgumentParser(description="Gemini 画像モデルで1枚生成する")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--prompt", help="生成プロンプト")
    src.add_argument("--prompt-file", type=Path, help="プロンプトを書いたテキストファイル")
    p.add_argument("--ref", type=Path, action="append", default=[], help="参照画像（複数指定可。キャラ設定画など）")
    p.add_argument("--aspect", default=cfg["aspect"], choices=ASPECTS, help=f"アスペクト比（既定 {cfg['aspect']}）")
    p.add_argument("--size", default=cfg["size"], choices=["0.5K", "1K", "2K", "4K"], help=f"解像度（既定 {cfg['size']}）")
    p.add_argument("--model", default=cfg["model"], help=f"モデル名（既定 {cfg['model']}）")
    p.add_argument("--out", type=Path, required=True, help="保存先（.png / .jpg）")
    p.add_argument("--log", type=Path, help="生成記録を追記する JSONL ファイル")
    args = p.parse_args()

    load_dotenv(REPO_DIR / ".env")
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key or not key.isascii():
        fail(f"GEMINI_API_KEY が設定されていません。{REPO_DIR / '.env'} にキーを記入してください")

    prompt = args.prompt if args.prompt is not None else args.prompt_file.read_text(encoding="utf-8")
    contents: list = [prompt]
    for ref in args.ref:
        if not ref.exists():
            fail(f"参照画像が見つかりません: {ref}")
        contents.append(Image.open(ref))

    config = types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(aspect_ratio=args.aspect, image_size=args.size),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    client = genai.Client(api_key=key)
    started = time.time()
    resp = generate(client, args.model, contents, config)

    image_bytes = None
    texts = []
    for cand in resp.candidates or []:
        for part in (cand.content.parts if cand.content else None) or []:
            if part.inline_data and part.inline_data.data and image_bytes is None:
                image_bytes = part.inline_data.data
            elif part.text:
                texts.append(part.text)
    if image_bytes is None:
        reasons = []
        if resp.prompt_feedback and resp.prompt_feedback.block_reason:
            reasons.append(f"プロンプトがブロックされました: {resp.prompt_feedback.block_reason}")
        for cand in resp.candidates or []:
            if cand.finish_reason:
                reasons.append(f"終了理由: {cand.finish_reason}")
        reasons += [f"モデルの応答: {t}" for t in texts]
        fail("画像が返りませんでした。" + (" / ".join(reasons) or "理由不明"))

    out = next_free_path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(io.BytesIO(image_bytes))
    if out.suffix.lower() in (".jpg", ".jpeg"):
        img.convert("RGB").save(out, quality=95)
    else:
        img.save(out)

    if args.log:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "time": dt.datetime.now().isoformat(timespec="seconds"),
            "model": args.model,
            "size": args.size,
            "aspect": args.aspect,
            "out": str(out),
            "refs": [str(r) for r in args.ref],
            "seconds": round(time.time() - started, 1),
            "cost_usd": load_config()["image"].get("cost_per_image_usd"),
        }
        with open(args.log, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    for t in texts:
        print(f"モデルの応答: {t}")
    print(f"画像サイズ: {img.width}x{img.height}")
    print(f"SAVED: {out}")


if __name__ == "__main__":
    main()
