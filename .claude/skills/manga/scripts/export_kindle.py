# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pillow>=11",
#     "pyyaml>=6",
# ]
# ///
"""完成ページから Kindle 用ファイルを書き出す。

使い方:
    uv run export_kindle.py <作品フォルダ>              # 表紙・EPUB・PDF・一覧画像をまとめて出す
    uv run export_kindle.py <作品フォルダ> --cover-only # 表紙だけ作り直す

出力（<作品フォルダ>/output/）:
    cover.jpg            表紙（KDP の「表紙」欄にもこれをアップロードする）
    <タイトル>.epub      EPUB3 固定レイアウト・右綴じ（KDP にアップロードする本体）
    <タイトル>.pdf       確認・予備用
    preview.jpg          全ページの一覧（カラー）
    preview_gray.jpg     全ページの一覧（白黒）… E-ink 端末で人物と背景が見分けられるかの確認用

manga.yaml の該当部分:
    title: パン屋のハナ
    author: 作者名
    cover:
      image: panels/cover.png      # 表紙の絵（文字なし）。省略時は1ページ目のコマ画像
      focus: [0.5, 0.4]
      title_position: top          # top / bottom
      title_color: "#ffffff"
      title_outline: "#3a2a1a"
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import math
import re
import sys
import uuid
import zipfile
from pathlib import Path

import yaml
from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lettering  # noqa: E402
from compose_page import fit_image  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parents[1]


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def hex_rgba(c: str) -> tuple[int, int, int, int]:
    c = c.lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), 255)


# ---------------------------------------------------------------- 表紙


def make_cover(work: Path, manga: dict, size: tuple[int, int], quality: int) -> Path:
    W, H = size
    cov = manga.get("cover", {}) or {}
    src = cov.get("image")
    if not src:
        first = manga["pages"][0]["panels"][0]
        src = first.get("image", f"panels/{first['id']}.png")
    path = work / src
    if not path.exists():
        fail(f"表紙の絵がありません: {path}")
    art = fit_image(ImageOps.exif_transpose(Image.open(path)).convert("RGB"), W, H,
                    tuple(cov.get("focus", (0.5, 0.5))))
    if not manga.get("color", True):
        art = art.convert("L").convert("RGB")
    canvas = art.convert("RGBA")

    title = manga.get("title", "無題")
    fill = hex_rgba(cov.get("title_color", "#ffffff"))
    outline = hex_rgba(cov.get("title_outline", "#222222"))
    # タイトルは幅の 88% に収まる最大サイズ（上限は高さの 9%）
    size_px = int(H * 0.09)
    while size_px > 40:
        img = lettering.text_line(title, size_px, fill=fill, stroke=max(4, size_px // 12), stroke_fill=outline)
        if img.width <= W * 0.88:
            break
        size_px = int(size_px * 0.92)
    top = cov.get("title_position", "top") == "top"
    y = int(H * 0.06) if top else int(H * 0.94) - img.height
    canvas.alpha_composite(img, ((W - img.width) // 2, y))

    author = manga.get("author")
    if author:
        a_size = int(H * 0.028)
        a_img = lettering.text_line(author, a_size, fill=fill, stroke=max(3, a_size // 10), stroke_fill=outline)
        ay = int(H * 0.94) - a_img.height if top else y - a_img.height - int(H * 0.02)
        canvas.alpha_composite(a_img, ((W - a_img.width) // 2, ay))

    out = work / "output" / "cover.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out, quality=quality, subsampling=0)
    return out


# ---------------------------------------------------------------- EPUB


def xhtml_page(title: str, img_href: str, w: int, h: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="ja">
<head>
<title>{html.escape(title)}</title>
<meta name="viewport" content="width={w}, height={h}"/>
<link rel="stylesheet" type="text/css" href="../style.css"/>
</head>
<body>
<div class="page"><img src="{img_href}" width="{w}" height="{h}" alt=""/></div>
</body>
</html>
"""


def build_epub(out: Path, manga: dict, cover: Path, pages: list[Path], size: tuple[int, int]) -> None:
    W, H = size
    title = manga.get("title", "無題")
    author = manga.get("author", "")
    book_id = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, 'mangakun:' + title)}"
    modified = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    items = [("cover", "Images/cover.jpg", cover)] + [(f"p{i:03d}", f"Images/p{i:03d}.jpg", p)
                                                        for i, p in enumerate(pages, 1)]
    manifest, spine = [], []
    for n, (pid, href, _) in enumerate(items):
        props = ' properties="cover-image"' if pid == "cover" else ""
        manifest.append(f'<item id="img_{pid}" href="{href}" media-type="image/jpeg"{props}/>')
        manifest.append(f'<item id="page_{pid}" href="Text/{pid}.xhtml" media-type="application/xhtml+xml"/>')
        # 右綴じ: 表紙は単独、本文は右ページから始めて右・左の順に交互
        if pid == "cover":
            spread = "rendition:page-spread-center"
        else:
            spread = "page-spread-right" if n % 2 == 1 else "page-spread-left"
        spine.append(f'<itemref idref="page_{pid}" properties="{spread}"/>')

    opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="BookID" xml:lang="ja">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="BookID">{book_id}</dc:identifier>
<dc:title>{html.escape(title)}</dc:title>
<dc:creator>{html.escape(author)}</dc:creator>
<dc:language>ja</dc:language>
<meta property="dcterms:modified">{modified}</meta>
<meta name="cover" content="img_cover"/>
<meta property="rendition:layout">pre-paginated</meta>
<meta property="rendition:orientation">portrait</meta>
<meta property="rendition:spread">landscape</meta>
<meta name="fixed-layout" content="true"/>
<meta name="original-resolution" content="{W}x{H}"/>
<meta name="book-type" content="comic"/>
<meta name="primary-writing-mode" content="horizontal-rl"/>
<meta name="orientation-lock" content="portrait"/>
<meta name="region-mag" content="false"/>
<meta name="zero-gutter" content="true"/>
<meta name="zero-margin" content="true"/>
</metadata>
<manifest>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
<item id="css" href="style.css" media-type="text/css"/>
{chr(10).join(manifest)}
</manifest>
<spine toc="ncx" page-progression-direction="rtl">
{chr(10).join(spine)}
</spine>
</package>
"""
    nav = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="ja">
<head><title>目次</title></head>
<body>
<nav epub:type="toc" id="toc"><h1>目次</h1><ol>
<li><a href="Text/cover.xhtml">表紙</a></li>
<li><a href="Text/p001.xhtml">本文</a></li>
</ol></nav>
<nav epub:type="landmarks" hidden=""><ol>
<li><a epub:type="cover" href="Text/cover.xhtml">表紙</a></li>
<li><a epub:type="bodymatter" href="Text/p001.xhtml">本文</a></li>
</ol></nav>
</body>
</html>
"""
    ncx = f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="ja">
<head><meta name="dtb:uid" content="{book_id}"/></head>
<docTitle><text>{html.escape(title)}</text></docTitle>
<navMap>
<navPoint id="n1" playOrder="1"><navLabel><text>表紙</text></navLabel><content src="Text/cover.xhtml"/></navPoint>
<navPoint id="n2" playOrder="2"><navLabel><text>本文</text></navLabel><content src="Text/p001.xhtml"/></navPoint>
</navMap>
</ncx>
"""
    css = "html, body { margin: 0; padding: 0; }\n.page { margin: 0; padding: 0; }\nimg { display: block; margin: 0; }\n"
    container = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", container, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/nav.xhtml", nav, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/toc.ncx", ncx, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/style.css", css, compress_type=zipfile.ZIP_DEFLATED)
        for pid, href, src in items:
            with Image.open(src) as im:
                w, h = im.size
            label = "表紙" if pid == "cover" else f"{int(pid[1:])}ページ"
            z.writestr(f"OEBPS/Text/{pid}.xhtml", xhtml_page(label, f"../{href}", w, h),
                       compress_type=zipfile.ZIP_DEFLATED)
            z.write(src, f"OEBPS/{href}", compress_type=zipfile.ZIP_STORED)  # JPEG は圧縮しない


# ---------------------------------------------------------------- PDF・一覧


def build_pdf(out: Path, cover: Path, pages: list[Path]) -> None:
    imgs = [Image.open(p).convert("RGB") for p in [cover] + pages]
    imgs[0].save(out, save_all=True, append_images=imgs[1:], resolution=300)


def contact_sheet(out: Path, cover: Path, pages: list[Path], gray: bool) -> None:
    """全ページの一覧画像。右綴じなので右から左へ並べる。"""
    files = [cover] + pages
    cols = min(5, len(files))
    rows = math.ceil(len(files) / cols)
    tw, th, gap = 320, 512, 16
    sheet = Image.new("RGB", (cols * tw + (cols + 1) * gap, rows * th + (rows + 1) * gap), (90, 90, 90))
    for i, f in enumerate(files):
        im = Image.open(f).convert("L" if gray else "RGB").resize((tw, th), Image.LANCZOS)
        r, c = divmod(i, cols)
        x = sheet.width - (c + 1) * (tw + gap)
        sheet.paste(im.convert("RGB"), (x, gap + r * (th + gap)))
    sheet.save(out, quality=85)


# ---------------------------------------------------------------- メイン


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "manga"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Kindle 用ファイル（表紙・EPUB・PDF）を書き出す")
    p.add_argument("work", type=Path, help="作品フォルダ（manga.yaml がある場所）")
    p.add_argument("--cover-only", action="store_true", help="表紙だけ作る")
    args = p.parse_args()

    cfg = load_yaml(SKILL_DIR / "config.yaml")["page"]
    size = tuple(cfg["size"])
    manga_path = args.work / "manga.yaml"
    if not manga_path.exists():
        fail(f"{manga_path} がありません")
    manga = load_yaml(manga_path)

    cover = make_cover(args.work, manga, size, cfg["jpeg_quality"])
    print(f"SAVED: {cover}")
    if args.cover_only:
        return

    pages = []
    for pg in sorted(manga.get("pages", []), key=lambda x: x["page"]):
        f = args.work / "pages" / f"p{pg['page']:02d}.jpg"
        if not f.exists():
            fail(f"{pg['page']}ページがまだ合成されていません: {f}（compose_page.py --all を先に実行）")
        with Image.open(f) as im:
            if im.size != size:
                fail(f"{f} の大きさ {im.size} が設定 {size} と違います")
        pages.append(f)
    if not pages:
        fail("ページがありません")

    out_dir = args.work / "output"
    name = safe_filename(manga.get("title", "manga"))
    epub = out_dir / f"{name}.epub"
    build_epub(epub, manga, cover, pages, size)
    pdf = out_dir / f"{name}.pdf"
    build_pdf(pdf, cover, pages)
    contact_sheet(out_dir / "preview.jpg", cover, pages, gray=False)
    contact_sheet(out_dir / "preview_gray.jpg", cover, pages, gray=True)
    for f in (epub, pdf, out_dir / "preview.jpg", out_dir / "preview_gray.jpg"):
        print(f"SAVED: {f}")
    print(f"ページ数: 表紙 + {len(pages)}ページ / EPUB {epub.stat().st_size / 1024 / 1024:.1f}MB")


if __name__ == "__main__":
    main()
