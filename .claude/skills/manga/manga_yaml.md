# manga.yaml の書き方

作品フォルダ（リポジトリ直下、**半角英数字**の名前。例: `panya-no-hana/`）に置く台本ファイル。
作品の状態はすべてここに保存する。セッションが切れても、このファイルを読めば続きから作業できる。

- `scene`・`shot`・`appearance`・`style_prompt` など**画像生成に渡す項目は英語**で書く
- セリフ・`note` など**読者やユーザーが見る項目は日本語**で書く
- gen_panels.py は生成後に `image`・`sheet`・`cover.image` を自動で書き込む（そのときコメントは消える）

## 全体の例

```yaml
title: パン屋のハナ               # 本のタイトル（表紙・EPUB に使う）
file_name: panya-no-hana          # 出力ファイル名。半角英数字（通常は作品フォルダ名と同じ）
author: 作者名                    # 表紙と EPUB の著者名。未定なら省略
status: panels                    # input / name / characters / panels / pages / exported（どこまで進んだか）
mode: confirm                     # confirm（確認モード） / omakase（おまかせモード）
color: true                       # false でモノクロ
style: honobono                   # styles.md のプリセット id
style_prompt: Modern Japanese manga / anime style, clean black line art, ...   # 実際に使う画風（英語）
synopsis: |                       # あらすじ（ユーザーの入力を整理したもの）
  小さなパン屋で働くハナは…
decisions: |                      # おまかせモードで Claude が補って決めたこと（最後に報告する）
  - 登場人物の年齢と見た目を決めた
characters:
  - id: hana                      # 半角英小文字（コマの characters で使う）
    name: ハナ
    role: 主人公
    personality: 明るくておっちょこちょい
    appearance: >-                # 英語。髪型・髪色・目・アクセサリー・服の色と形まで具体的に（服装は固定）
      24-year-old Japanese woman, shoulder-length wavy chestnut-brown hair, yellow flower hair clip on the
      left side, big round brown eyes, light freckles, white blouse, mustard-yellow apron, dark-green long skirt
    sheet: characters/hana.png    # 設定画（gen_panels.py --characters が書き込む）
cover:
  scene: Hana smiling in front of her bakery holding a basket of fresh bread, morning light   # 英語
  characters: [hana]
  title_position: top             # タイトルを入れる位置 top / bottom（絵もそこを空けて描かれる）
  title_color: "#ffffff"
  title_outline: "#5a3a1a"
  image: panels/cover.png         # gen_panels.py --cover が書き込む
pages:
  - page: 1
    layout: 3_tall_right          # layouts/ のテンプレート名（compose_page.py --list-layouts）
    note: ハナがパンを運んでいて転びそうになる   # このページの内容（日本語・ユーザー確認用）
    panels:                       # 読む順（右上から）。数はレイアウトのコマ数と同じにする
      - id: p01_01                # p<ページ2桁>_<コマ2桁>
        note: 店の前でクロワッサンの天板を持ってつまずくハナ（全身）   # 日本語・ユーザー確認用
        characters: [hana]        # 登場キャラ（設定画が参照画像として渡される。最大4人）
        scene: >-                 # 英語。誰が・どこで・何をして・どんな表情か
          Hana stumbles forward in front of the bakery entrance, holding a large tray of croissants,
          surprised face, one foot lifted
        shot: full body, low angle from her left side   # 英語。構図・カメラ
        space: top                # 吹き出し用に空ける場所（top / top-left / top-right / left / right / none）
        refs: []                  # 追加の参照画像（背景をそろえたいときに前のコマなど）
        image: panels/p01_01.png  # 採用版（gen_panels.py が書き込む。旧版に戻すときはここを書き換える）
        focus: [0.45, 0.5]        # コマ枠に切り抜くとき中心に来てほしい位置（画像に対する割合）
        zoom: 1.0                 # 1より大きいと寄る
        bubbles:
          - type: shout           # speech / shout / thought / whisper / narration
            text: "わわっ!!"
            pos: [0.3, 0.2]       # 吹き出しの中心（コマに対する割合 0〜1）
            tail: [0.38, 0.33]    # しっぽが向く先（話し手の頭の外側）
            size: 1.0             # 文字の大きさの倍率（省略可）
          - type: narration
            text: "パン屋「こむぎ」の\n朝は早い。"     # pos を省略するとコマの右上
        sfx:
          - text: ツルッ
            pos: [0.82, 0.72]
            size: 2.5             # セリフ文字の何倍か
            angle: -12            # 反時計回りの角度
            color: "#141414"
            vertical: true
```

## 吹き出しの種類

| type | 見た目 | 使いどころ |
|---|---|---|
| speech | 楕円・しっぽ | 普通のセリフ |
| shout | ギザギザ・太字 | 叫び・驚き |
| thought | 雲形・小さな丸のしっぽ | 心の声 |
| whisper | 点線の楕円 | ささやき・小声 |
| narration | 四角・しっぽなし | ナレーション・時間や場所の説明 |

## セリフの書き方

- 縦書き。`\n` で列を改行する。**改行は必ず自分で入れる**（自動折り返しは意味の切れ目を知らない）
  - 文節の切れ目で改行する。例: `"今日も\n10時から\n開いてますよ。"`
  - 1列は 10 文字まで。1つの吹き出しは 3〜4 列、30 文字くらいまで。長いときは吹き出しを分ける
- 半角の `!!` `!?` は自動で組文字（‼ ⁉）に、2桁の数字は縦中横になる
- 「ー」「…」「（ ）」「「 」」は自動で縦書き用に回転する
- 1コマの吹き出しは 3 個まで。1ページのセリフは合計 150 文字くらいまで

## 吹き出しの置き方（compose_page.py --debug の目盛り画像を見て決める）

- 顔・手元・大事な小物にかぶせない。コマの `space` に指定した空き部分を使う
- 読む順は **右→左、上→下**。先に話す人の吹き出しを右・上に置く
- しっぽ（`tail`）は話し手の**頭の外側**を指す。顔の中を指さない（長さは自動で制限される）
- 吹き出しはコマ枠からはみ出してもよい（ページの外には出ない）。ナレーションはコマの内側に収まる
- 絵の切り抜き位置は `focus`（どこを中心にするか）と `zoom` で調整する
