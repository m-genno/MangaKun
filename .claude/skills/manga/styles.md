# 画風プリセット

画風の指定がなければ、あらすじに合うものを1つ選んで提案する。迷ったら「ほのぼの」。
選んだプリセットの `style_prompt` を manga.yaml の `style_prompt` にそのまま写す（必要なら言葉を足して調整してよい）。
モノクロ指定のときも同じプリセットを使う（色の指示は gen_panels.py が `color: false` を見て自動で差し替える）。

| id | 名前 | 向いている話 |
|---|---|---|
| honobono | ほのぼの | 日常・お仕事・家族・動物。**既定** |
| shoujo | 少女漫画 | 恋愛・青春・学園 |
| shounen | 少年漫画 | バトル・スポーツ・冒険 |
| gekiga | 劇画 | 大人向けドラマ・サスペンス・歴史 |
| ehon | 絵本風 | 子ども向け・童話・やさしい話 |
| gag | ギャグ | コメディ・4コマ的なノリ |

## honobono（ほのぼの）

```
Modern Japanese manga / anime style, clean black line art, soft cel shading, bright pastel colors, warm and gentle atmosphere, expressive faces.
```

## shoujo（少女漫画）

```
Classic Japanese shoujo manga style, delicate thin line art, large sparkling expressive eyes, flowing hair, soft pastel colors, subtle floral and sparkle accents in backgrounds, romantic and emotional atmosphere.
```

## shounen（少年漫画）

```
Japanese shounen manga style, bold dynamic line art, strong contrast, energetic poses and dramatic camera angles, speed lines in action scenes, vivid saturated colors.
```

## gekiga（劇画）

```
Japanese gekiga style, realistic adult proportions, detailed ink hatching and cross-hatching, heavy shadows, cinematic lighting, gritty mature atmosphere, muted desaturated colors.
```

## ehon（絵本風）

```
Children's picture-book style, soft watercolor textures, gentle rounded shapes, simple thin outlines, warm paper texture, soft cheerful colors, cute and friendly characters.
```

## gag（ギャグ）

```
Japanese comedy manga style, super-deformed chibi proportions with big heads, simple bold outlines, exaggerated funny expressions, flat bright colors.
```

## 調整のコツ

- ユーザーの言葉（「もっと大人っぽく」「線を太く」「水彩っぽく」など）は英語にして `style_prompt` の末尾に足す
- 実在の漫画家・作品・キャラクターの名前は入れない（権利の問題があり、KDP でも問題になりうる）
- 画風を変えたら、キャラ設定画から作り直す（設定画の画風に各コマが引っぱられるため）
