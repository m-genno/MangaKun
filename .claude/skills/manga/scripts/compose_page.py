# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pillow>=11",
#     "pyyaml>=6",
# ]
# ///
"""manga.yaml の内容からページ画像（コマ配置・吹き出し・縦書きセリフ・効果音）を作る。

使い方:
    uv run compose_page.py <作品フォルダ> --page 1       # 1ページ合成 → pages/p01.jpg
    uv run compose_page.py <作品フォルダ> --all          # 全ページ
    uv run compose_page.py <作品フォルダ> --info         # 各コマの大きさと、生成に使うアスペクト比
    uv run compose_page.py --list-layouts                # コマ割りテンプレートの一覧

--debug を付けると、コマ番号と 10% 刻みの目盛りを重ねた確認用画像（pNN_debug.jpg）も出す。
コマ画像がまだ無いときは灰色の仮コマで合成する（ネーム段階の確認に使える）。
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lettering  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parents[1]
LAYOUT_DIR = SKILL_DIR / "layouts"
GEN_ASPECTS = ["1:1", "3:2", "2:3", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]
BUBBLE_KINDS = {"speech", "shout", "thought", "whisper", "narration"}


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------- コマ割り


def load_layout(name: str) -> dict:
    path = LAYOUT_DIR / f"{name}.yaml"
    if not path.exists():
        fail(f"レイアウト '{name}' がありません。--list-layouts で一覧を確認してください")
    return load_yaml(path)


def layout_fracs(layout: dict) -> list[tuple[float, float, float, float]]:
    """読む順のコマ枠 [x, y, w, h]（内枠に対する割合）。rows 形式は右→左・上→下の順に並べる。"""
    if "panels" in layout:
        return [tuple(p) for p in layout["panels"]]
    rows = layout["rows"]
    total_h = sum(r.get("height", 1) for r in rows)
    out, y = [], 0.0
    for r in rows:
        h = r.get("height", 1) / total_h
        cols = r.get("cols", [1])
        total_w = sum(cols)
        right = 1.0
        for c in cols:
            w = c / total_w
            out.append((right - w, y, w, h))
            right -= w
        y += h
    return out


def panel_rects(layout: dict, cfg: dict) -> list[tuple[int, int, int, int]]:
    """コマ枠をページのピクセル座標 (left, top, right, bottom) にする。内側の辺だけ間白の半分ずつ縮める。"""
    W, H = cfg["size"]
    mx, my = cfg["margin"][0] * W, cfg["margin"][1] * H
    lw, lh = W - 2 * mx, H - 2 * my
    gx, gy = cfg["gutter"]
    eps = 1e-6
    rects = []
    for x, y, w, h in layout_fracs(layout):
        l, t, r, b = mx + x * lw, my + y * lh, mx + (x + w) * lw, my + (y + h) * lh
        if x > eps:
            l += gx / 2
        if x + w < 1 - eps:
            r -= gx / 2
        if y > eps:
            t += gy / 2
        if y + h < 1 - eps:
            b -= gy / 2
        rects.append((round(l), round(t), round(r), round(b)))
    return rects


def best_aspect(w: int, h: int) -> str:
    target = math.log(w / h)

    def score(a: str) -> float:
        x, y = (int(v) for v in a.split(":"))
        return abs(math.log(x / y) - target)

    return min(GEN_ASPECTS, key=score)


# ---------------------------------------------------------------- コマ画像


def fit_image(img: Image.Image, w: int, h: int, focus=(0.5, 0.5), zoom: float = 1.0) -> Image.Image:
    """枠いっぱいに拡大して切り抜く。focus は画像内で枠の中心に来てほしい位置（割合）。"""
    scale = max(w / img.width, h / img.height) * max(zoom, 1.0)
    sw, sh = math.ceil(img.width * scale), math.ceil(img.height * scale)
    img = img.resize((sw, sh), Image.LANCZOS)
    left = min(max(focus[0] * sw - w / 2, 0), sw - w)
    top = min(max(focus[1] * sh - h / 2, 0), sh - h)
    return img.crop((round(left), round(top), round(left) + w, round(top) + h))


def placeholder(w: int, h: int, label: str) -> Image.Image:
    img = Image.new("RGB", (w, h), (225, 225, 225))
    d = ImageDraw.Draw(img)
    d.line([(0, 0), (w, h)], fill=(200, 200, 200), width=3)
    d.line([(0, h), (w, 0)], fill=(200, 200, 200), width=3)
    d.text((w / 2, h / 2), label, font=lettering.font(lettering.BOLD_FONT, 48), fill=(150, 150, 150), anchor="mm")
    return img


def panel_image_path(work: Path, panel: dict) -> Path:
    return work / panel.get("image", f"panels/{panel['id']}.png")


# ---------------------------------------------------------------- ページ合成


def compose(work: Path, manga: dict, page: dict, cfg: dict, debug: bool = False) -> list[Path]:
    num = page["page"]
    layout = load_layout(page["layout"])
    rects = panel_rects(layout, cfg)
    panels = page.get("panels", [])
    if len(panels) != len(rects):
        fail(f"{num}ページ: コマ数 {len(panels)} とレイアウト '{page['layout']}' のコマ数 {len(rects)} が合いません")

    W, H = cfg["size"]
    color = manga.get("color", True)
    canvas = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    missing = []

    for panel, (l, t, r, b) in zip(panels, rects):
        w, h = r - l, b - t
        path = panel_image_path(work, panel)
        if path.exists():
            img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
            img = fit_image(img, w, h, tuple(panel.get("focus", (0.5, 0.5))), panel.get("zoom", 1.0))
            if not color:
                img = img.convert("L").convert("RGB")
        else:
            missing.append(panel["id"])
            img = placeholder(w, h, panel["id"])
        canvas.paste(img, (l, t))
        draw.rectangle([l, t, r - 1, b - 1], outline=(0, 0, 0), width=cfg["border"])

    # 効果音 → 吹き出しの順に重ねる（吹き出しは枠からはみ出してもよい）
    for panel, (l, t, r, b) in zip(panels, rects):
        w, h = r - l, b - t

        def to_page(p):
            return (l + p[0] * w, t + p[1] * h)

        for sfx in panel.get("sfx", []):
            size = round(cfg["font_size"] * sfx.get("size", 2.5))
            col = sfx.get("color", "#141414")
            img = lettering.render_sfx(sfx["text"], size, color=col, vertical=sfx.get("vertical", True),
                                       angle=sfx.get("angle", 0))
            cx, cy = to_page(sfx["pos"])
            canvas.alpha_composite(img, (round(cx - img.width / 2), round(cy - img.height / 2)))

        for bub in panel.get("bubbles", []):
            kind = bub.get("type", "speech")
            if kind not in BUBBLE_KINDS:
                fail(f"{panel['id']}: 吹き出しの種類 '{kind}' は使えません（{', '.join(sorted(BUBBLE_KINDS))}）")
            size = round(cfg["font_size"] * bub.get("size", 1.0))
            tail = to_page(bub["tail"]) if bub.get("tail") and kind != "narration" else None
            pos = bub.get("pos", (1.0, 0.0) if kind == "narration" else None)
            if pos is None:
                fail(f"{panel['id']}: 吹き出し「{bub['text']}」に pos がありません")
            layer, (ox, oy) = lettering.render_bubble(kind, bub["text"], to_page(pos), tail, size,
                                                     bub.get("max_chars", cfg["max_chars"]))
            if kind == "narration":  # ナレーションはコマの内側に収める（pos 省略時は右上）
                inset = cfg["border"] + 12
                ox = min(max(ox, l + inset), r - inset - layer.width)
                oy = min(max(oy, t + inset), b - inset - layer.height)
            else:  # 吹き出しは枠からはみ出してよいが、ページの外には出さない
                ox = min(max(ox, 8), W - layer.width - 8)
                oy = min(max(oy, 8), H - layer.height - 8)
            canvas.alpha_composite(layer, (ox, oy))

    out_dir = work / "pages"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"p{num:02d}.jpg"
    rgb = canvas.convert("RGB")
    rgb.save(out, quality=cfg["jpeg_quality"], subsampling=0)
    saved = [out]

    if debug:
        dbg = rgb.copy()
        d = ImageDraw.Draw(dbg)
        f = lettering.font(lettering.BOLD_FONT, 28)
        for i, (panel, (l, t, r, b)) in enumerate(zip(panels, rects), 1):
            for k in range(1, 10):
                x, y = l + (r - l) * k / 10, t + (b - t) * k / 10
                d.line([(x, t), (x, b)], fill=(255, 0, 0), width=1)
                d.line([(l, y), (r, y)], fill=(255, 0, 0), width=1)
                d.text((x, t + 4), str(k / 10)[1:], font=f, fill=(255, 0, 0), anchor="mt")
                d.text((l + 6, y), str(k / 10)[1:], font=f, fill=(255, 0, 0), anchor="lm")
            d.text((r - 10, t + 10), f"{i}: {panel['id']}", font=lettering.font(lettering.BOLD_FONT, 40),
                   fill=(255, 0, 0), anchor="rt", stroke_width=4, stroke_fill=(255, 255, 255))
        dout = out_dir / f"p{num:02d}_debug.jpg"
        dbg.save(dout, quality=85)
        saved.append(dout)

    if missing:
        print(f"{num}ページ: 画像のないコマを仮コマで合成しました: {', '.join(missing)}")
    return saved


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="manga.yaml からページ画像を合成する")
    p.add_argument("work", nargs="?", type=Path, help="作品フォルダ（manga.yaml がある場所）")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--page", type=int, action="append", help="合成するページ番号（複数指定可）")
    g.add_argument("--all", action="store_true", help="全ページを合成")
    g.add_argument("--info", action="store_true", help="各コマの大きさと生成用アスペクト比を表示")
    g.add_argument("--list-layouts", action="store_true", help="コマ割りテンプレートの一覧")
    p.add_argument("--debug", action="store_true", help="コマ番号と目盛り入りの確認用画像も出す")
    args = p.parse_args()

    cfg = load_yaml(SKILL_DIR / "config.yaml")["page"]

    if args.list_layouts:
        for path in sorted(LAYOUT_DIR.glob("*.yaml")):
            lay = load_yaml(path)
            print(f"{path.stem:<16} {len(layout_fracs(lay))}コマ  {lay.get('description', '')}")
        return

    if not args.work:
        p.error("作品フォルダを指定してください")
    manga_path = args.work / "manga.yaml"
    if not manga_path.exists():
        fail(f"{manga_path} がありません")
    manga = load_yaml(manga_path)
    pages = manga.get("pages", [])

    if args.info:
        for page in pages:
            rects = panel_rects(load_layout(page["layout"]), cfg)
            print(f"{page['page']}ページ（{page['layout']}）")
            for i, (l, t, r, b) in enumerate(rects):
                pid = page["panels"][i]["id"] if i < len(page.get("panels", [])) else "(未定義)"
                print(f"  {pid}: {r - l}x{b - t}px → 生成アスペクト比 {best_aspect(r - l, b - t)}")
        return

    if args.all:
        targets = pages
    elif args.page:
        targets = [pg for pg in pages if pg["page"] in args.page]
        if len(targets) != len(set(args.page)):
            fail(f"manga.yaml に無いページ番号があります: {args.page}")
    else:
        p.error("--page N / --all / --info のどれかを指定してください")

    for page in targets:
        for out in compose(args.work, manga, page, cfg, debug=args.debug):
            print(f"SAVED: {out}")


if __name__ == "__main__":
    main()
