# AI 阪口源太 — 与那国町議会議員 AITuber

Streamlit Cloud で動作する AI 町政報告会システム。

## 機能

- 🎬 **WebM動画アバター**: idle / talking_normal / talking_strong の3状態を感情に応じて切替
- 🗣️ **Google Cloud TTS**: クラウド音声合成で高速レスポンス
- 🧠 **Gemini 2.0 Flash + FAISS RAG**: 政策ドキュメントに基づく正確な回答
- 💬 **ハイブリッド入力**: テキスト入力 + YouTube ライブチャット自動取得
- 📺 **OBS対応**: `?embed=1` パラメータでアバター部分のみ表示

## AIの信頼性とエビデンス

本AIアバターの回答ロジックは、阪口源太の過去の実績、NPO活動、および具体的な政策提言を多角的に解析し構築されています。
AIが単なる生成を行うのではなく、実務家としての「実装力」を基盤に回答している証跡は [docs/AI_CORE_STRATEGY.md](docs/AI_CORE_STRATEGY.md) に公式ドキュメントとして公開されています。

## セットアップ

### 1. Streamlit Cloud

1. このリポジトリを GitHub にプッシュ
2. [share.streamlit.io](https://share.streamlit.io) でデプロイ
3. Settings → Secrets に以下を設定:

```toml
GOOGLE_API_KEY = "your-gemini-api-key"
GOOGLE_APPLICATION_CREDENTIALS_JSON = '{"type":"service_account",...}'
YOUTUBE_API_KEY = "your-youtube-api-key"
YT_ID = "your-live-video-id"
ENABLE_YOUTUBE_MONITOR = false
```

### 2. ローカル開発

```bash
cd streamlit_app
pip install -r requirements.txt
# .streamlit/secrets.toml を作成（secrets.toml.example を参考）
streamlit run app.py
```

## OBS 配信設定

1. OBS に「ブラウザソース」を追加
2. URL: `https://your-app.streamlit.app/?embed=1`
3. 幅: 1280, 高さ: 720
4. 下部のテキストボックスは自動的に非表示になる
