from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT
DATA_DIR = PACKAGE_ROOT / "data"
STATIC_DIR = PACKAGE_ROOT / "static"
BRAND_DIR = STATIC_DIR / "brand"


@dataclass(frozen=True)
class AppConfig:
    """저장소의 .env 파일에서 읽어 온 실행 설정입니다."""

    openai_api_key: str | None
    openai_model: str
    openai_embedding_model: str
    use_llm: bool
    llm_assist: bool
    app_db_path: Path
    external_db_path: Path
    chroma_dir: Path
    active_week: int

    @property
    def has_openai_key(self) -> bool:
        return bool(self.openai_api_key)


def _active_week_from_env() -> int:
    raw_value = os.getenv("KANANA_ACTIVE_WEEK", "6")
    try:
        value = int(raw_value)
    except ValueError:
        value = 6
    return max(1, min(value, 6))


def load_config() -> AppConfig:
    """비밀 값을 출력하거나 노출하지 않고 .env 설정을 불러옵니다."""

    load_dotenv(REPO_ROOT / ".env")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    use_llm = os.getenv("KANANA_USE_LLM", "0").lower() in {"1", "true", "yes", "on"}
    llm_assist = os.getenv("KANANA_LLM_ASSIST", os.getenv("KANANA_USE_LLM", "0")).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    return AppConfig(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        openai_embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        use_llm=use_llm,
        llm_assist=llm_assist,
        app_db_path=DATA_DIR / "kanana_app.sqlite3",
        external_db_path=DATA_DIR / "kanana_external_people.sqlite3",
        chroma_dir=DATA_DIR / "chroma",
        active_week=_active_week_from_env(),
    )


CONFIG = load_config()
