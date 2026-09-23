"""縦書きセリフ・吹き出し・効果音の描画。compose_page.py / export_kindle.py から import して使う。

縦書きは1文字ずつ配置する（Pillow の縦組みは環境によって使えないため）。
- 長音・括弧・三点リーダなどは 90° 回転する
- 句読点と小書き仮名は右上に寄せる
- 「!!」「!?」は源暎アンチックの組文字（‼ ⁉）に、2桁の半角数字は縦中横にする
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path(__file__).resolve().parents[1] / "fonts"
SERIF_FONT = FONT_DIR / "GenEiAntiqueNv6-M.ttf"  # セリフ用アンチック体
BOLD_FONT = FONT_DIR / "DelaGothicOne-Regular.ttf"  # 叫び・効果音・タイトル用
SS = 2  # 吹き出しを2倍で描いて縮小し、線を滑らかにする

ROTATE = set("ー－―—‐-~〜～…‥=＝(（)）[［]］{｛}｝「」『』【】〈〉《》＜＞<>→←:：;；|｜")
SHIFT_PUNCT = set("、。，．")
SMALL_KANA = set("ぁぃぅぇぉっゃゅょゎゕゖァィゥェォッャュョヮヵヶ")
NO_START = set("、。，．」』）)】〉》ー～〜…‥！？‼⁉⁈⁇・：；") | SMALL_KANA
NO_END = set("「『（(【〈《")
BREAK_AFTER = set("、。，．」』）)！？‼⁉⁈⁇…")
LIGATURES = {"！！": "‼", "！？": "⁉", "？！": "⁈", "？？": "⁇"}

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    key = (str(path), int(size))
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(str(path), int(size))
    return _font_cache[key]


# ---------------------------------------------------------------- 文字の並び


def tokenize(text: str) -> list[str]:
    """文字列を縦書きの1マス単位に分ける。改行は "\\n" のまま残す。"""
    out: list[str] = []
    i = 0
    while i < len(text):
        c = text[i]
        # 2桁の半角数字は縦中横（1マスに横並び）
        if c.isascii() and c.isdigit() and i + 1 < len(text) and text[i + 1].isascii() and text[i + 1].isdigit() \
                and not (i + 2 < len(text) and text[i + 2].isascii() and text[i + 2].isdigit()) \
                and not (i > 0 and text[i - 1].isascii() and text[i - 1].isdigit()):
            out.append(text[i:i + 2])
            i += 2
            continue
        if c == "\n":
            out.append(c)
        elif c == " ":
            out.append("　")
        elif "!" <= c <= "~":
            out.append(chr(ord(c) + 0xFEE0))  # 半角 → 全角
        else:
            out.append(c)
        i += 1
    # ！！ ！？ などを組文字に
    merged: list[str] = []
    for t in out:
        if merged and merged[-1] + t in LIGATURES:
            merged[-1] = LIGATURES[merged[-1] + t]
        else:
            merged.append(t)
    return merged


def wrap(tokens: list[str], max_chars: int) -> list[list[str]]:
    """列に分ける。明示の改行を優先し、長い行は均等に割って禁則処理をする。"""
    segments: list[list[str]] = [[]]
    for t in tokens:
        if t == "\n":
            segments.append([])
        else:
            segments[-1].append(t)
    cols: list[list[str]] = []
    for seg in segments:
        n = len(seg)
        if n <= max_chars:
            cols.append(seg)
            continue
        target = math.ceil(n / math.ceil(n / max_chars))
        i = 0
        while i < n:
            j = min(i + target, n)
            if j < n:  # 近くに句読点や括弧があればそこで切る
                cands = [k for k in range(j - 2, j + 2) if i < k < n and k - i <= max_chars
                         and (seg[k - 1] in BREAK_AFTER or seg[k] in NO_END)]
                if cands:
                    j = min(cands, key=lambda k: abs(k - j))
            while j < n and seg[j] in NO_START and j - i < max_chars + 2:  # 追い込み
                j += 1
            while j < n and j - 1 > i and seg[j - 1] in NO_END:  # 追い出し
                j -= 1
            cols.append(seg[i:j])
            i = j
    return cols


def _draw_token(img: Image.Image, tok: str, xc: float, yc: float, size: int, fpath: Path,
                fill, stroke: int, stroke_fill) -> None:
    f = font(fpath, size)
    d = ImageDraw.Draw(img)
    kw = dict(fill=fill, stroke_width=stroke, stroke_fill=stroke_fill, anchor="mm")
    if len(tok) == 2 and tok.isascii():  # 縦中横
        w = f.getlength(tok)
        fs = size if w <= size * 0.95 else int(size * size * 0.95 / w)
        d.text((xc, yc), tok, font=font(fpath, fs), **kw)
    elif tok in ROTATE:
        box = size * 2 + stroke * 2
        tmp = Image.new("RGBA", (box, box), (0, 0, 0, 0))
        ImageDraw.Draw(tmp).text((box / 2, box / 2), tok, font=f, **kw)
        tmp = tmp.rotate(-90)
        img.alpha_composite(tmp, (round(xc - box / 2), round(yc - box / 2)))
    elif tok in SHIFT_PUNCT:
        d.text((xc + size * 0.5, yc - size * 0.5), tok, font=f, **kw)
    elif tok in SMALL_KANA:
        d.text((xc + size * 0.1, yc - size * 0.1), tok, font=f, **kw)
    else:
        d.text((xc, yc), tok, font=f, **kw)


def text_block(text: str, size: int, fpath: Path = SERIF_FONT, max_chars: int = 8, fill=(0, 0, 0, 255),
               stroke: int = 0, stroke_fill=None, gap: float = 0.3, pitch: float = 1.0) -> Image.Image:
    """縦書きのテキストを透明背景の画像にする。列は右から左、各列は上揃え。"""
    cols = wrap(tokenize(text), max_chars)
    gap_px = size * gap
    w = len(cols) * size + (len(cols) - 1) * gap_px + stroke * 2
    h = max((len(c) for c in cols), default=1) * size * pitch + stroke * 2
    img = Image.new("RGBA", (math.ceil(w), math.ceil(h)), (0, 0, 0, 0))
    # フチ付きのときは、先に全文字のフチを描いてから本体を描く（隣の文字のフチで欠けないように）
    passes = [(stroke_fill, stroke, stroke_fill), (fill, 0, None)] if stroke else [(fill, 0, None)]
    for p_fill, p_stroke, p_sfill in passes:
        for k, col in enumerate(cols):
            xc = w - stroke - size / 2 - k * (size + gap_px)
            for i, tok in enumerate(col):
                _draw_token(img, tok, xc, stroke + (i + 0.5) * size * pitch, size, fpath, p_fill, p_stroke, p_sfill)
    return img


def text_line(text: str, size: int, fpath: Path = BOLD_FONT, fill=(0, 0, 0, 255), stroke: int = 0,
              stroke_fill=None) -> Image.Image:
    """横書き1行（表紙タイトル・横書き効果音用）。"""
    f = font(fpath, size)
    l, t, r, b = f.getbbox(text, stroke_width=stroke)
    img = Image.new("RGBA", (r - l, b - t), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((-l, -t), text, font=f, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
    return img


# ---------------------------------------------------------------- 図形


def offset_polygon(pts: list[tuple[float, float]], d: float) -> list[tuple[float, float]]:
    """多角形の各辺を外側へ d だけ平行移動した多角形（角はとがらせる）。"""
    n = len(pts)
    area = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))
    sign = 1 if area > 0 else -1
    lines = []
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        ex, ey = x1 - x0, y1 - y0
        ln = math.hypot(ex, ey) or 1
        nx, ny = ey / ln * sign, -ex / ln * sign
        lines.append(((x0 + nx * d, y0 + ny * d), (ex, ey)))
    out = []
    for i in range(n):
        (p, r), (q, s) = lines[i - 1], lines[i]
        cross = r[0] * s[1] - r[1] * s[0]
        if abs(cross) < 1e-9:
            out.append(q)
            continue
        t = ((q[0] - p[0]) * s[1] - (q[1] - p[1]) * s[0]) / cross
        out.append((p[0] + r[0] * t, p[1] + r[1] * t))
    return out


def _ellipse_fit(bw: float, bh: float, pad: float) -> tuple[float, float]:
    """幅 bw・高さ bh の文字ブロックが収まる楕円の半径。"""
    p, q = bw / 2, bh / 2
    k = math.sqrt((p / (p + pad)) ** 2 + (q / (q + pad)) ** 2)
    return k * (p + pad) + pad * 0.5, k * (q + pad) + pad * 0.5


def _toward(cx, cy, a, b, tx, ty, max_out):
    """中心から (tx, ty) へ向かう単位ベクトル、楕円の縁までの距離、しっぽの先までの距離。

    しっぽは話し手の方向を指せばよいので、縁から max_out より先へは伸ばさない（顔に刺さらないように）。
    先が吹き出しの中なら None。
    """
    dx, dy = tx - cx, ty - cy
    ln = math.hypot(dx, dy)
    if ln == 0 or (dx / a) ** 2 + (dy / b) ** 2 <= 1.0:
        return None
    ux, uy = dx / ln, dy / ln
    edge = 1 / math.sqrt((ux / a) ** 2 + (uy / b) ** 2)
    return ux, uy, edge, min(ln, edge + max_out)


def _tail(cx, cy, a, b, tx, ty, width, max_out) -> list[tuple[float, float]] | None:
    d = _toward(cx, cy, a, b, tx, ty, max_out)
    if not d:
        return None
    ux, uy, _, reach = d
    bx, by = cx + ux * min(a, b) * 0.5, cy + uy * min(a, b) * 0.5
    return [(bx - uy * width, by + ux * width), (cx + ux * reach, cy + uy * reach), (bx + uy * width, by - ux * width)]


def render_bubble(kind: str, text: str, center: tuple[float, float], tail: tuple[float, float] | None,
                  size: int, max_chars: int) -> tuple[Image.Image, tuple[int, int]]:
    """吹き出しを描いた透明レイヤーと、その貼り付け位置（ページ座標）を返す。

    kind: speech（通常） / shout（叫び・ギザギザ） / thought（心の声・雲形） / whisper（ささやき・点線） / narration（ナレーション・四角）
    """
    s = size * SS
    t = max(2, round(size * 0.085)) * SS  # 線の太さ
    fpath = BOLD_FONT if kind == "shout" else SERIF_FONT
    block = text_block(text, s, fpath=fpath, max_chars=max_chars)
    bw, bh = block.size
    cx, cy = center[0] * SS, center[1] * SS
    tp = (tail[0] * SS, tail[1] * SS) if tail else None

    black: list = []  # (種類, 図形) … 先に黒で太らせて描き、後から白で塗ると外周だけ線が残る
    white: list = []
    extra_lines: list = []

    if kind == "narration":
        pad = s * 0.5
        a, b = bw / 2 + pad, bh / 2 + pad
        box = [cx - a, cy - b, cx + a, cy + b]
        black.append(("rect", [box[0] - t * 0.7, box[1] - t * 0.7, box[2] + t * 0.7, box[3] + t * 0.7]))
        white.append(("rect", box))
    else:
        a, b = _ellipse_fit(bw, bh, s * 0.55)
        if kind == "shout":
            a, b = a * 1.08, b * 1.08
            rnd = random.Random(text)
            per = math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))
            n = max(10, int(per / (s * 1.4)))
            pts = []
            for i in range(n * 2):
                th = math.pi * i / n
                f = (1.32 + rnd.uniform(-0.1, 0.1)) if i % 2 == 0 else 1.04
                pts.append((cx + a * f * math.cos(th), cy + b * f * math.sin(th)))
            black.append(("poly", offset_polygon(pts, t)))
            white.append(("poly", pts))
        elif kind == "thought":
            r = s * 0.55
            per = math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))
            n = max(8, int(per / (r * 1.3)))
            for i in range(n):
                th = 2 * math.pi * i / n
                px, py = cx + a * math.cos(th), cy + b * math.sin(th)
                black.append(("circle", (px, py, r + t)))
                white.append(("circle", (px, py, r)))
        if kind != "shout":
            black.append(("ellipse", [cx - a - t, cy - b - t, cx + a + t, cy + b + t]))
            white.append(("ellipse", [cx - a, cy - b, cx + a, cy + b]))
        if kind == "whisper":
            black = [x for x in black if x[0] != "ellipse"]
            extra_lines.append(("dash_ellipse", [cx - a, cy - b, cx + a, cy + b]))
        if tp:
            if kind == "thought":
                d = _toward(cx, cy, a, b, tp[0], tp[1], s * 2.6)
                if d and d[3] > d[2] + s:
                    ux, uy, edge, reach = d
                    for frac, rr in ((0.3, 0.4), (0.62, 0.28), (0.9, 0.18)):
                        dd = edge + s * 0.6 + (reach - edge - s * 0.6) * frac
                        black.append(("circle", (cx + ux * dd, cy + uy * dd, rr * s + t)))
                        white.append(("circle", (cx + ux * dd, cy + uy * dd, rr * s)))
            else:
                reach = s * (2.4 if kind == "shout" else 1.6)
                tri = _tail(cx, cy, a, b, tp[0], tp[1], min(a, b, s * 1.4) * 0.35, reach)
                if tri:
                    black.append(("poly", offset_polygon(tri, t)))
                    white.append(("poly", tri))

    # レイヤーの範囲
    xs, ys = [], []
    for kind_, g in black + white + extra_lines:
        if kind_ == "poly":
            xs += [p[0] for p in g]
            ys += [p[1] for p in g]
        elif kind_ == "circle":
            xs += [g[0] - g[2], g[0] + g[2]]
            ys += [g[1] - g[2], g[1] + g[2]]
        else:
            xs += [g[0], g[2]]
            ys += [g[1], g[3]]
    ox, oy = math.floor(min(xs)) - 2, math.floor(min(ys)) - 2
    W, H = math.ceil(max(xs)) - ox + 4, math.ceil(max(ys)) - oy + 4
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(layer)

    def draw(items, color):
        for kind_, g in items:
            if kind_ == "poly":
                dr.polygon([(x - ox, y - oy) for x, y in g], fill=color)
            elif kind_ == "circle":
                dr.ellipse([g[0] - g[2] - ox, g[1] - g[2] - oy, g[0] + g[2] - ox, g[1] + g[2] - oy], fill=color)
            elif kind_ == "ellipse":
                dr.ellipse([g[0] - ox, g[1] - oy, g[2] - ox, g[3] - oy], fill=color)
            elif kind_ == "rect":
                dr.rectangle([g[0] - ox, g[1] - oy, g[2] - ox, g[3] - oy], fill=color)

    draw(black, (0, 0, 0, 255))
    draw(white, (255, 255, 255, 255))
    for _, g in extra_lines:  # ささやきの点線
        box = [g[0] - ox, g[1] - oy, g[2] - ox, g[3] - oy]
        for deg in range(0, 360, 12):
            dr.arc(box, deg, deg + 7, fill=(0, 0, 0, 255), width=t)
    layer.alpha_composite(block, (round(cx - ox - bw / 2), round(cy - oy - bh / 2)))
    layer = layer.resize((math.ceil(W / SS), math.ceil(H / SS)), Image.LANCZOS)
    return layer, (round(ox / SS), round(oy / SS))


def render_sfx(text: str, size: int, color=(20, 20, 20, 255), vertical: bool = True, angle: float = 0,
               outline=(255, 255, 255, 255)) -> Image.Image:
    """効果音（描き文字）。白いフチ付きの太字。angle は反時計回りの角度。"""
    stroke = max(3, round(size * 0.12))
    if vertical:
        img = text_block(text, size, fpath=BOLD_FONT, max_chars=99, fill=color, stroke=stroke,
                         stroke_fill=outline, pitch=0.92)
    else:
        img = text_line(text, size, fill=color, stroke=stroke, stroke_fill=outline)
    if angle:
        img = img.rotate(angle, resample=Image.BICUBIC, expand=True)
    return img
