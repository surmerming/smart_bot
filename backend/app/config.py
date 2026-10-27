"""全局配置：从 .env 读取，缺省值兜底。"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

# 以 backend/ 为基准目录
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env_str(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


class Settings:
    # --- DeepSeek ---
    DEEPSEEK_API_KEY: str = _env_str("DEEPSEEK_API_KEY")
    DEEPSEEK_BASE_URL: str = _env_str("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL: str = _env_str("DEEPSEEK_MODEL", "deepseek-chat")
    LLM_MODE: str = _env_str("LLM_MODE", "auto")  # auto / real / mock

    # --- 品牌 ---
    BRAND_NAME: str = _env_str("BRAND_NAME", "小答")
    _default_chips = [
        {"label": "📦 怎么查物流", "value": "怎么查我的物流信息"},
        {"label": "🔄 7天无理由怎么退", "value": "怎么申请7天无理由退货"},
        {"label": "💳 退款多久到账", "value": "退款多久能到账"},
        {"label": "👤 忘记密码了", "value": "我忘记密码了怎么办"},
    ]
    QUICK_CHIPS: list = json.loads(_env_str("QUICK_CHIPS", "[]")) or _default_chips

    # --- 检索 ---
    # TF-IDF + 中文 bigram 量纲校准值（命中类分数中位 ~0.33、未命中 ~0.05）：
    # < LOW 直接转人工；LOW~HIGH 走 LLM 可回答性判断；> HIGH 高置信直接生成。
    # 切换真实 Embedding（豆包/BGE-M3 + Qdrant）后按 0.75 / 0.85 重调。
    SIM_THRESHOLD_LOW: float = _env_float("SIM_THRESHOLD_LOW", 0.22)
    SIM_THRESHOLD_HIGH: float = _env_float("SIM_THRESHOLD_HIGH", 0.40)
    RETRIEVE_TOP_K: int = _env_int("RETRIEVE_TOP_K", 3)
    RRF_K: int = _env_int("RRF_K", 60)
    # V1.5 检索精度：Query Rewrite 查询重写（口语化 → 标准问法，仅用于检索）
    QUERY_REWRITE_ENABLED: bool = _env_str("QUERY_REWRITE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
    # V1.5 缓存优化：高频问题秒回缓存（仅首轮、仅自动回答结果）
    CACHE_ENABLED: bool = _env_str("CACHE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
    CACHE_MAX_ENTRIES: int = _env_int("CACHE_MAX_ENTRIES", 20)

    # --- 会话与安全 ---
    SESSION_MAX_TURNS: int = _env_int("SESSION_MAX_TURNS", 30)
    MAX_INPUT_LEN: int = _env_int("MAX_INPUT_LEN", 2000)
    RATE_LIMIT_PER_MIN: int = _env_int("RATE_LIMIT_PER_MIN", 10)
    HISTORY_WINDOW_TURNS: int = _env_int("HISTORY_WINDOW_TURNS", 5)

    # --- 存储 ---
    DB_PATH: Path = BASE_DIR / _env_str("DB_PATH", "data/chat.db")
    KB_PATH: Path = BASE_DIR / _env_str("KB_PATH", "../knowledge_base/faq.json")

    # --- 访客 Token ---
    VISITOR_TOKEN_SECRET: str = _env_str("VISITOR_TOKEN_SECRET", "change-me-in-production")
    VISITOR_TOKEN_TTL_HOURS: int = _env_int("VISITOR_TOKEN_TTL_HOURS", 24)

    # 软转人工 / 红灯转人工时前端可点击的快捷回复
    HANDOVER_QUICK_REPLIES: list = [
        {"label": "继续咨询其他问题", "value": "好的，继续聊其他问题"},
    ]

    @property
    def use_real_llm(self) -> bool:
        """是否走真实 DeepSeek API。"""
        if self.LLM_MODE == "mock":
            return False
        if self.LLM_MODE == "real":
            return bool(self.DEEPSEEK_API_KEY)
        return bool(self.DEEPSEEK_API_KEY)


settings = Settings()
