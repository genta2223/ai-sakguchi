import shutil
import streamlit as st
from pathlib import Path

# ============================================================
# Path Management
# ============================================================

class PathManager:
    """Centralized path management for static assets and environment safety."""
    APP_DIR = Path(__file__).parent
    LOCAL_STATIC = APP_DIR / "static"
    
    @classmethod
    def get_internal_static(cls):
        """【真の解決策】StreamlitがWeb公開を許可している '玄関' のフォルダへ直結"""
        try:
            import streamlit as st_pkg
            return Path(st_pkg.__path__[0]) / "static" / "static"
        except:
            return None

    @classmethod
    def get_web_base_url(cls):
        return "/static/"

    @classmethod
    def get_video_url_map(cls):
        """動画ファイルのURLマップを取得 (ハイブリッド配信用)"""
        return {
            "idle": "/static/idle_blink.webm",
            "normal": "/static/talking_normal.webm",
            "strong": "/static/talking_strong.webm",
            "wait": "/static/talking_wait.webm"
        }

    @classmethod
    def get_video_base64_map(cls):
        """【廃止予定】動画の軽量化により、URL参照(キャッシュ有効)に移行しました。"""
        return {}

    @classmethod
    def ensure_safe_deployment(cls):
        """【廃止予定】インメモリ方式への移行により、物理コピーは不要になりました。"""
        return str(cls.LOCAL_STATIC)

APP_DIR = Path(__file__).parent
LOCAL_STATIC_DIR = APP_DIR / "static"
