# MangaKun

Claude Code に「以下の漫画を作って」と伝えると、Kindle 出版用の漫画を作るスキル。
仕組みと詳しい手順は [PLAN.md](PLAN.md) を参照。

## セットアップ

1. 必要なもの
   - Claude の有料プラン（Pro 以上）と Claude Code
   - [uv](https://docs.astral.sh/uv/)（Python スクリプトの実行に使う。Python 本体やライブラリの個別インストールは不要）
   - Google AI Studio の API キー（Gemini）
   - Git
2. このリポジトリを clone する（OneDrive や iCloud の同期フォルダの外に置く）
3. `.env.example` を `.env` にコピーし、`GEMINI_API_KEY` にキーを記入する
4. このフォルダで Claude Code を開き、「以下の漫画を作って」と話しかける

Windows / Mac ごとの詳しい手順は PLAN.md の10章を参照。

## スキルの更新

Claude に「スキルを更新して」と言うと `git pull` で最新版を取り込む。
