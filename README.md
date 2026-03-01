# 🎙️ Fast AI Avatar Framework (Streamlit)

**「評論するより、実装する。」**
わずか数ステップで、あなたの「AIアバター（政治家・VTuber・広報担当）」を爆速・超軽量でWeb上にデプロイできる、Streamlitベースのオープンソース・フレームワークです。

## ✨ なぜこのフレームワークなのか？（3つの圧倒的強み）

既存のAIアバター開発（React + WebGLなど）の複雑さを排除し、Pythonのみで構築されています。

* ⚡ **爆速（0秒レスポンス）**
  * FAISS（ベクトル検索）を用いた強力なキャッシュ機構（`faq_cache.json`）を搭載。
  * 過去に回答した質問には、LLMの推論も音声合成（TTS）もスキップして**「0秒」**で即答します。
* 🪶 **超軽量（Streamlit Cloudで安定動作）**
  * 重い3Dモデルは使わず、4つの軽量WebM動画（待機・思考・発話・頷き）を非同期JavaScriptでシームレスに切り替え。
  * Streamlit特有の「画面のチラつき」や「無限リロードによるメモリ爆発」を完全に制圧した独自アーキテクチャ（v20.0 Stable）。1GBメモリの無料クラウドでも絶対に落ちません。
* 🛠️ **簡単導入（ノーコードで着せ替え可能）**
  * `static` フォルダ内のWebM動画を差し替え、`Secrets`（環境変数）の名前とURLを書き換えるだけで、**誰でも自分のAIアバターとしてシステムを丸ごと流用**できます。

## 🏗️ システムアーキテクチャ
* **Frontend:** Streamlit + Custom HTML/JS (iframe DOM破壊防止ロジック)
* **Backend Worker:** Python `threading` による完全非同期処理
* **Brain (LLM & RAG):** Gemini 2.0 Flash + FAISS (ベクトル検索による回答生成)
* **Voice:** Google Cloud TTS

## 🚀 クイックスタート (ローカル構築)

1. リポジトリのクローン
```bash
git clone https://github.com/genta2223/ai-sakguchi.git
cd ai-sakguchi
```

2. 依存関係のインストール

```bash
pip install -r requirements.txt
```

3. 環境変数（`.streamlit/secrets.toml`）の設定

```toml
# 必須APIキーと設定
GEMINI_API_KEY = "your_gemini_api_key"
GCP_SERVICE_ACCOUNT_JSON = '{ "type": "service_account", ... }'
AVATAR_NAME = "あなたの名前"
SOCIAL_X_URL = "https://x.com/your_id"
GITHUB_REPO_URL = "https://github.com/your-username/your-repo"
```

4. アプリの起動

```bash
streamlit run app.py
```

## 📝 カスタマイズ方法（あなたの脳を移植する）

`docs/TUNING_MANUAL.md` を参照してください。経歴や政策（あるいはキャラクター設定）をNotebookLM等で構造化し、プロンプトとRAGデータに流し込むだけで、あなたと全く同じ思考で語り出すAIが完成します。
