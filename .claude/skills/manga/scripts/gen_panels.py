# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "google-genai>=1.40",
#     "pillow>=11",
#     "python-dotenv>=1.0",
#     "pyyaml>=6",
# ]
# ///
"""manga.yaml の内容から、キャラ設定画・コマ・表紙の絵をまとめて生成する。

使い方:
    uv run gen_panels.py <作品フォルダ> --characters             # 設定画のないキャラの設定画を作る
    uv run gen_panels.py <作品フォルダ>                          # 絵のないコマを全部作る
    uv run gen_panels.py <作品フォルダ> --pages 3 4              # 指定ページの、絵のないコマだけ作る
    uv run gen_panels.py <作品フォルダ> --panels p03_02 --retake --extra "もっと笑顔で"
                                                                 # 指定コマを作り直す（旧版は残る）
    uv run gen_panels.py <作品フォルダ> --characters --only hana --retake
    uv run gen_panels.py <作品フォルダ> --cover                  # 表紙の絵を作る
    uv run gen_panels.py <作品フォルダ> --dry-run                # 生成せずに、プロンプト・枚数・概算費用を表示
    uv run gen_panels.py <作品フォルダ> --usage                  # これまでの生成枚数と費用

- 生成した絵のパスは manga.yaml（panels の image、characters の sheet、cover の image）に自動で書き込む
- 生成記録は <作品フォルダ>/gen_log.jsonl に残る
- 作品全体の生成枚数が上限（config.yaml の max_images_per_page から計算）を超えそうなら、
  生成せずに終了コード 3 で止まる。--force で上限を無視する
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compose_page import best_aspect, load_layout, panel_rects  # noqa: E402
from gen_image import GenError, generate_image, load_config, price_usd  # noqa: E402

NO_TEXT = ("Do not include any text, letters, numbers, signs with writing, sound effects, "
           "captions or speech bubbles anywhere in the image.")
FULL_BLEED = ("One single continuous illustration that fills the entire image edge to edge. "
              "No panel borders, no frames, no split panels, no empty boxes.")


@dataclass
class Job:
    kind: str  # panel / sheet / cover
    key: str  # コマ ID・キャラ ID・"cover"
    prompt: str
    out: Path
    aspect: str
    refs: list[Path] = field(default_factory=list)


# ---------------------------------------------------------------- manga.yaml の読み書き


def _str_presenter(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


yaml.SafeDumper.add_representer(str, _str_presenter)


def load_manga(work: Path) -> dict:
    with open(work / "manga.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_manga(work: Path, manga: dict) -> None:
    with open(work / "manga.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(manga, f, allow_unicode=True, sort_keys=False, default_flow_style=None, width=1000)


# ---------------------------------------------------------------- プロンプト


def style_lines(manga: dict) -> str:
    style = manga.get("style_prompt") or "Modern Japanese manga / anime style, clean black line art."
    color = ("Full color, soft cel shading." if manga.get("color", True)
             else "Black-and-white manga art with screentone shading and solid blacks. No color at all.")
    return f"Art style: {style}\n{color}"


def character_lines(manga: dict, ids: list[str]) -> tuple[str, list[Path]]:
    chars = {c["id"]: c for c in manga.get("characters", [])}
    lines, refs = [], []
    for cid in ids:
        c = chars.get(cid)
        if not c:
            raise GenError(f"characters に '{cid}' がありません")
        lines.append(f"- {c.get('name', cid)}: {c.get('appearance', '')}")
        if c.get("sheet"):
            refs.append(Path(c["sheet"]))
    if not lines:
        return "", refs
    head = ("Characters in this image. The attached reference sheets show them in this order: "
            + ", ".join(chars[c].get("name", c) for c in ids)
            + ". Each character must look exactly like their reference sheet: same face, hairstyle, hair color, "
              "eye color, accessories, outfit and body proportions.")
    return head + "\n" + "\n".join(lines), refs


def space_line(space: str | None) -> str:
    if not space or space == "none":
        return ""
    return (f"Composition: keep the {space} part of the image as simple, uncluttered background that belongs to "
            f"the same scene (sky, wall, or soft blur) so speech bubbles can be placed there later. "
            f"No important details or faces in that area.")


def panel_job(work: Path, manga: dict, panel: dict, aspect: str, extra: str | None) -> Job:
    chars, refs = character_lines(manga, panel.get("characters", []))
    parts = [
        "A single panel illustration for a Japanese manga.",
        style_lines(manga),
        f"Scene: {panel.get('scene', '')}",
        f"Camera: {panel['shot']}" if panel.get("shot") else "",
        chars,
        space_line(panel.get("space", "top")),
        FULL_BLEED,
        NO_TEXT,
        f"Additional direction: {extra}" if extra else "",
    ]
    refs += [Path(r) for r in panel.get("refs", [])]
    return Job("panel", panel["id"], "\n".join(p for p in parts if p), work / "panels" / f"{panel['id']}.png",
               aspect, [work / r for r in refs])


def sheet_job(work: Path, manga: dict, c: dict, extra: str | None) -> Job:
    parts = [
        "Character reference sheet for a Japanese manga.",
        style_lines(manga),
        f"Character: {c.get('name', c['id'])}. {c.get('appearance', '')}",
        f"Personality: {c['personality']}" if c.get("personality") else "",
        "Layout on a plain white background: full-body front view, full-body side view, full-body back view, "
        "and three head-and-shoulders close-ups showing a big smile, anger, and surprise.",
        "Do not include any text, letters, labels, captions or speech bubbles.",
        f"Additional direction: {extra}" if extra else "",
    ]
    return Job("sheet", c["id"], "\n".join(p for p in parts if p), work / "characters" / f"{c['id']}.png", "16:9")


def cover_job(work: Path, manga: dict, extra: str | None) -> Job:
    cov = manga.get("cover") or {}
    chars, refs = character_lines(manga, cov.get("characters", []))
    where = "top" if cov.get("title_position", "top") == "top" else "bottom"
    parts = [
        "Cover illustration for a Japanese manga book, portrait orientation, eye-catching and polished.",
        style_lines(manga),
        f"Scene: {cov.get('scene', '')}",
        chars,
        f"Composition: keep the {where} quarter of the image as simple background so the book title can be "
        f"placed there later.",
        FULL_BLEED,
        NO_TEXT,
        f"Additional direction: {extra}" if extra else "",
    ]
    return Job("cover", "cover", "\n".join(p for p in parts if p), work / "panels" / "cover.png",
               best_aspect(1600, 2560), [work / r for r in refs])


# ---------------------------------------------------------------- 上限・費用


def read_log(work: Path) -> list[dict]:
    log = work / "gen_log.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def budget(manga: dict) -> int:
    per_page = load_config().get("max_images_per_page", 8)
    return len(manga.get("pages", [])) * per_page + len(manga.get("characters", [])) * 2 + 2


def yen(usd: float) -> int:
    return round(usd * load_config()["image"].get("usd_to_jpy", 150))


def usage_text(work: Path, manga: dict) -> str:
    recs = read_log(work)
    usd = sum(r.get("cost_usd") or 0 for r in recs)
    return f"これまでの生成: {len(recs)}枚 / 約 ${usd:.2f}（約{yen(usd)}円）/ 上限 {budget(manga)}枚"


# ---------------------------------------------------------------- メイン


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="manga.yaml からキャラ設定画・コマ・表紙を生成する")
    p.add_argument("work", type=Path, help="作品フォルダ")
    what = p.add_mutually_exclusive_group()
    what.add_argument("--characters", action="store_true", help="キャラ設定画を作る")
    what.add_argument("--cover", action="store_true", help="表紙の絵を作る")
    what.add_argument("--usage", action="store_true", help="生成枚数と費用を表示")
    p.add_argument("--pages", type=int, nargs="+", help="対象ページ")
    p.add_argument("--panels", nargs="+", help="対象コマ ID")
    p.add_argument("--only", nargs="+", help="--characters の対象キャラ ID")
    p.add_argument("--retake", action="store_true", help="絵があっても作り直す（旧版は残す）")
    p.add_argument("--extra", help="今回だけ追加する指示（英語推奨）")
    p.add_argument("--dry-run", action="store_true", help="生成せずに内容と概算費用を表示")
    p.add_argument("--force", action="store_true", help="生成枚数の上限を無視する")
    args = p.parse_args()

    work = args.work
    if not (work / "manga.yaml").exists():
        print(f"ERROR: {work / 'manga.yaml'} がありません", file=sys.stderr)
        sys.exit(1)
    manga = load_manga(work)
    if args.usage:
        print(usage_text(work, manga))
        return
    if args.retake and not (args.pages or args.panels or args.only or args.cover):
        print("ERROR: --retake は --pages / --panels / --only / --cover と一緒に指定してください", file=sys.stderr)
        sys.exit(1)

    cfg = load_config()
    page_cfg = cfg["page"]
    jobs: list[Job] = []
    try:
        if args.characters:
            for c in manga.get("characters", []):
                if args.only and c["id"] not in args.only:
                    continue
                if c.get("sheet") and (work / c["sheet"]).exists() and not args.retake:
                    continue
                jobs.append(sheet_job(work, manga, c, args.extra))
        elif args.cover:
            cov = manga.get("cover") or {}
            if not (cov.get("image") and (work / cov["image"]).exists()) or args.retake:
                jobs.append(cover_job(work, manga, args.extra))
        else:
            missing_sheets = [c["id"] for c in manga.get("characters", [])
                              if not (c.get("sheet") and (work / c["sheet"]).exists())]
            for page in manga.get("pages", []):
                if args.pages and page["page"] not in args.pages:
                    continue
                rects = panel_rects(load_layout(page["layout"]), page_cfg)
                for panel, (l, t, r, b) in zip(page.get("panels", []), rects):
                    if args.panels and panel["id"] not in args.panels:
                        continue
                    img = panel.get("image", f"panels/{panel['id']}.png")
                    if (work / img).exists() and not args.retake:
                        continue
                    need = [c for c in panel.get("characters", []) if c in missing_sheets]
                    if need:
                        raise GenError(f"{panel['id']}: 設定画がまだないキャラがいます: {', '.join(need)}"
                                       "（先に --characters で作ってください）")
                    jobs.append(panel_job(work, manga, panel, best_aspect(r - l, b - t), args.extra))
    except GenError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if not jobs:
        print("生成するものはありません")
        print(usage_text(work, manga))
        return

    unit = price_usd(cfg["image"]["model"], cfg["image"]["size"]) or 0
    est = unit * len(jobs)
    print(f"生成予定: {len(jobs)}枚 / 概算 ${est:.2f}（約{yen(est)}円）")
    used, limit = len(read_log(work)), budget(manga)
    if args.dry_run:
        for j in jobs:
            print(f"\n=== {j.key}（{j.aspect}、参照 {len(j.refs)}枚）→ {j.out.relative_to(work).as_posix()}")
            print(j.prompt)
        print(f"\n{usage_text(work, manga)}")
        return
    if used + len(jobs) > limit and not args.force:
        print(f"STOP: 生成枚数の上限を超えます（これまで {used}枚 + 今回 {len(jobs)}枚 > 上限 {limit}枚）。"
              "ユーザーに確認してから --force を付けて実行してください")
        sys.exit(3)

    log = work / "gen_log.jsonl"

    def run(job: Job):
        try:
            out = generate_image(job.prompt, job.out, job.refs, job.aspect, log=log, label=job.key)
            return job, out, None
        except GenError as e:
            return job, None, str(e)
        except Exception as e:  # 予期しないエラーでも他の生成は続ける
            return job, None, f"{type(e).__name__}: {e}"

    results = []
    with ThreadPoolExecutor(max_workers=cfg["image"].get("parallel", 4)) as ex:
        for job, out, err in ex.map(run, jobs):
            results.append((job, out, err))
            print(f"OK  {job.key} → {out.relative_to(work).as_posix()}" if out else f"NG  {job.key}: {err}",
                  flush=True)

    # 採用版を manga.yaml に書き込む（生成中に Claude が編集していてもよいよう読み直す）
    manga = load_manga(work)
    done = {job.key: out.relative_to(work).as_posix() for job, out, _ in results if out}
    for c in manga.get("characters", []):
        if ("sheet", c["id"]) in {(j.kind, j.key) for j, o, _ in results if o}:
            c["sheet"] = done[c["id"]]
    if any(j.kind == "cover" and o for j, o, _ in results):
        manga.setdefault("cover", {})["image"] = done["cover"]
    for page in manga.get("pages", []):
        for panel in page.get("panels", []):
            if any(j.kind == "panel" and j.key == panel["id"] and o for j, o, _ in results):
                panel["image"] = done[panel["id"]]
    save_manga(work, manga)

    failed = [j.key for j, o, _ in results if not o]
    print(f"完了: 成功 {len(results) - len(failed)}枚 / 失敗 {len(failed)}枚")
    print(usage_text(work, manga))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
