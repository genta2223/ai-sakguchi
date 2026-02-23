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
    def ensure_safe_deployment(cls):
        """Physical Reset: Direct deployment to root and forced cleanup."""
        internal_static = cls.get_internal_static()
        if not internal_static or not internal_static.parent.exists():
            return str(cls.LOCAL_STATIC)

        try:
            # 玄関フォルダが存在しなければ作成
            internal_static.mkdir(exist_ok=True)
            
            # Direct Deployment: Copy all to the publicly exposed folder
            for f in cls.LOCAL_STATIC.glob("*"):
                if f.suffix.lower() == ".js" or f.suffix.lower() == ".map" or f.name.startswith("index"):
                    continue
                target = internal_static / f.name
                if target.exists():
                    target.unlink()
                shutil.copy2(f, target)
            return str(internal_static)
        except Exception as e:
            return str(cls.LOCAL_STATIC)

APP_DIR = Path(__file__).parent
LOCAL_STATIC_DIR = APP_DIR / "static"
