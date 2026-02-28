
```markdown
# AI阪口源太 システム仕様書 ＆ アセット作成マニュアル (v20.0 Stable)

本ドキュメントは、Streamlitをベースとした完全非同期・爆速AIアバターシステム（v20.0）のアーキテクチャと、フロントエンドで描画されるアバター動画素材（`static` フォルダ）の作成プロンプトを定義するものです。

---

## 1. システム・アーキテクチャ概要 (v20.0 安定版)

本システムは、「待たせないUX」と「Streamlit Cloudでのメモリ/通信制限の完全クリア」を両立するため、以下の独自アーキテクチャを採用しています。

### 1.1 コアコンポーネント
* **Frontend (UI)**: Streamlit
  * `st.components.v1.html` を用いた直接描画。動画データはモジュールレベルでBase64キャッシュされ、再描画時のiframe破壊（チラつき）をReactのハッシュ比較ハックにより完全に防いでいます。
* **Backend Worker (`core_ai_worker.py`)**:
  * メインスレッド（UI）をブロックしないよう、`threading.Thread` と `queue.Queue` を用いた完全非同期処理。
* **Brain (推論 & RAG)**: Gemini 2.0 Flash + FAISS
  * 過去のQ&Aや政策コアデータをFAISSでベクトル検索し、Geminiにコンテキストとして渡すRAG構成。
  * **爆速キャッシュ機構**: 一度回答した質問は `faq_cache.json` に音声ごと保存し、次回以降はLLMもTTSもスキップして「0秒」で回答を返します。
* **Voice (音声合成)**: Google Cloud TTS
* **Video (映像)**: 状態に応じた4つのWebM動画をJavaScript側でシームレスに切り替え。

### 1.2 v20.0における安定化の工夫（特記事項）
* `st_autorefresh` や `st.empty()` といったDOMを破壊するコンポーネントを完全排除。
* `time.sleep()` と `st.rerun()` を組み合わせた、最もシンプルで安全な「ネイティブ・ポーリングループ」を実装。これにより無限リロードやOOM（メモリ不足）を根絶。

---

## 2. `static` フォルダの構成

アバターの描画には、軽量で透過処理やループ再生に強い `WebM` 形式の動画ファイルを使用します。ルートディレクトリの `static/` フォルダに以下の構成で配置してください。

```text
static/
 ├── idle.webm     # [待機] 瞬きや微かな呼吸のみ（デフォルト状態）
 ├── thinking.webm # [思考] 目線を逸らす、考える仕草（LLM推論中）
 ├── talking.webm  # [発話] 口を動かして話している状態（音声再生中）
 └── nodding.webm  # [共感] 深く頷く仕草（ユーザー入力の受付時など）

```

*推奨スペック*: 解像度 720p または 1080p / フレームレート 30fps / ファイルサイズ 各1〜3MB程度に圧縮（Streamlitの通信負荷を下げるため）。

---

## 3. アバター動画生成プロンプト (Sora等 動画生成AI用)

動画生成AI（Sora, Luma, Kling, Runway Gen-3等）を使用して、阪口源太の参照画像（Base Image）からアバターの4つの状態を生成する際の**プロンプト（指示文）の最適解**です。

**【共通の前提条件（ネガティブプロンプト・システム指示）】**

* カメラは完全に固定（No camera movement, static framing）。
* 背景は固定またはグリーンバック（Solid green background / Consistent background）。
* 照明の変化なし（Consistent cinematic lighting）。
* ループ再生を前提とするため、動画の開始フレームと終了フレームの姿勢が一致するように生成すること。

### パターン1：待機 (idle.webm)

**目的：** 話を聞いている、または待機している時の自然な静止状態。
**プロンプト (Prompt):**

> "Cinematic portrait of a Japanese male politician in a professional suit. He is looking directly into the camera with a calm, trustworthy expression. The camera is perfectly static. He is completely still, only showing very subtle natural breathing and occasional natural blinking. No mouth movement. Seamless loop."
> （プロスーツを着た日本の男性政治家のシネマティックなポートレート。穏やかで信頼できる表情でカメラを真っ直ぐ見つめている。カメラは完全に固定。体は全く動かさず、ごくわずかな自然な呼吸と、時折の自然な瞬きのみ。口は動かさない。シームレスループ。）

### パターン2：発話 (talking.webm)

**目的：** 音声に合わせて口パクをしている状態。（※口の動きは後からリップシンクAIで合わせる場合もありますが、ベースとして口を動かしている動画を作ります）
**プロンプト (Prompt):**

> "Cinematic portrait of a Japanese male politician in a professional suit. He is looking directly into the camera and speaking confidently. His lips are moving naturally as if delivering a calm speech. Subtle head movements for emphasis, but maintaining direct eye contact. Camera is perfectly static."
> （プロスーツを着た日本の男性政治家のシネマティックなポートレート。カメラを真っ直ぐ見つめ、自信を持って話している。穏やかなスピーチをしているかのように、唇が自然に動いている。強調するためのわずかな頭の動きはあるが、カメラ目線は外さない。カメラは完全に固定。）

### パターン3：思考 (thinking.webm)

**目的：** 質問を受け取り、AIが回答を生成している数秒間に再生する「考え中」の仕草。
**プロンプト (Prompt):**

> "Cinematic portrait of a Japanese male politician in a professional suit. He is deep in thought. He slowly breaks eye contact, looking slightly upward and to the side. His brow furrows slightly in contemplation. His mouth is closed. Slowly returns gaze to the center at the end. Camera is perfectly static."
> （プロスーツを着た日本の男性政治家のシネマティックなポートレート。深く考えている。ゆっくりと目線を外し、少し斜め上を見る。思案するように眉をわずかにひそめる。口は閉じている。最後はゆっくりと目線を中央に戻す。カメラは完全に固定。）

### パターン4：共感・頷き (nodding.webm)

**目的：** ユーザーの意見や質問に対し、理解を示している状態。
**プロンプト (Prompt):**

> "Cinematic portrait of a Japanese male politician in a professional suit. He is looking directly into the camera with a warm, empathetic expression. He slowly and deeply nods his head twice, showing understanding and agreement. Camera is perfectly static."
> （プロスーツを着た日本の男性政治家のシネマティックなポートレート。温かく共感的な表情でカメラを見つめている。理解と同意を示すように、ゆっくりと深く2回頷く。カメラは完全に固定。）

---

## 4. メンテナンスとアップデート

* 新しい動画素材を作成した場合は、動画編集ソフト等で開始と終了のフレームが繋がるようにカット編集を行い、`ffmpeg` 等でWebM形式（VP9コーデック等）に軽量化・変換してから `static/` に上書きしてください。
* キャッシュが強く効くため、動画を差し替えた際はブラウザのスーパーリロード（Ctrl+Shift+R）、またはStreamlit Cloud上での「Reboot」を実施してください。

```

```