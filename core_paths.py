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
    @st.cache_data
    def get_video_base64_map(cls):
        """動画ファイルをBase64文字列のマップとして取得 (インメモリ注入用)"""
        import base64
        video_map = {}
        files = {
            "idle": "idle_blink.webm",
            "normal": "talking_normal.webm",
            "strong": "talking_strong.webm",
            "wait": "talking_wait.webm"
        }
        for key, filename in files.items():
            path = cls.LOCAL_STATIC / filename
            if path.exists():
                try:
                    b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
                    video_map[key] = f"data:video/webm;base64,{b64}"
                    st.write(f"Encoded {filename}") # Diagnostic
                except Exception as e:
                    st.error(f"Failed to encode {filename}: {e}")
            else:
                st.warning(f"Video not found: {filename}")
        return video_map

    @classmethod
    def ensure_safe_deployment(cls):
        """【廃止予定】インメモリ方式への移行により、物理コピーは不要になりました。"""
        return str(cls.LOCAL_STATIC)

APP_DIR = Path(__file__).parent
LOCAL_STATIC_DIR = APP_DIR / "static"
