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
        """動画ファイルのURLマップを取得 (ハイブリッド配信用)
        StreamlitのenableStaticServing=trueにより、/app/static/filename.webm でアクセス可能。
        """
        return {
            "idle": "app/static/idle_blink.webm",
            "normal": "app/static/talking_normal.webm",
            "strong": "app/static/talking_strong.webm",
            "wait": "app/static/talking_wait.webm"
        }

    @classmethod
    def get_video_base64_map(cls):
        """動画ファイルをBase64エンコードして返す (Streamlit Cloudのパス回避のため)"""
        import base64
        import logging
        logger = logging.getLogger(__name__)
        
        video_files = {
            "idle": "idle_blink.webm",
            "normal": "talking_normal.webm",
            "strong": "talking_strong.webm",
            "wait": "talking_wait.webm"
        }
        
        b64_map = {}
        for key, filename in video_files.items():
            filepath = cls.LOCAL_STATIC / filename
            if filepath.exists():
                try:
                    with open(filepath, "rb") as f:
                        b64_data = base64.b64encode(f.read()).decode("utf-8")
                        b64_map[key] = f"data:video/webm;base64,{b64_data}"
                except Exception as e:
                    logger.error(f"Failed to base64 encode {filename}: {e}")
            else:
                logger.warning(f"Video file not found: {filepath}")
                b64_map[key] = ""
                
        return b64_map

    @classmethod
    def ensure_safe_deployment(cls):
        """【廃止予定】インメモリ方式への移行により、物理コピーは不要になりました。"""
        return str(cls.LOCAL_STATIC)

APP_DIR = Path(__file__).parent
LOCAL_STATIC_DIR = APP_DIR / "static"
