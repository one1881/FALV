from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    API_V1_PREFIX: str = "/api"
    PROJECT_NAME: str = "Contract Management System"

    # 主模型配置（优先使用 Qwen / 阿里百炼；DEEPSEEK_* 仅作兼容回退）
    QWEN_API_KEY: str = ""
    QWEN_MODEL: str = "qwen-plus"
    QWEN_API_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_MODEL: str = "deepseek-chat"
    DEEPSEEK_API_URL: str = "https://api.deepseek.com"
    MINERU_API_URL: str = ""
    MINERU_API_KEY: str = ""
    ASR_API_URL: str = ""
    ASR_API_KEY: str = ""
    ASR_PROVIDER: str = "generic"
    ALIYUN_ACCESS_KEY_ID: str = ""
    ALIYUN_ACCESS_KEY_SECRET: str = ""
    ALIYUN_TINGWU_APP_KEY: str = ""
    ALIYUN_TINGWU_ENDPOINT: str = ""
    ASR_MAX_CHUNK_SECONDS: int = 300
    # 视频画面理解（多模态视觉，qwen-vl）
    QWEN_VL_API_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    QWEN_VL_API_KEY: str = ""
    QWEN_VL_MODEL: str = "qwen-vl-plus"

    @property
    def primary_llm_api_key(self) -> str:
        return self.QWEN_API_KEY or self.DEEPSEEK_API_KEY

    @property
    def primary_llm_api_url(self) -> str:
        return self.QWEN_API_URL or self.DEEPSEEK_API_URL

    @property
    def primary_llm_model(self) -> str:
        return self.QWEN_MODEL or self.DEEPSEEK_MODEL

    VIDEO_UNDERSTAND_MAX_FRAMES: int = 6
    VIDEO_UNDERSTAND_FRAME_INTERVAL: int = 3
    YOLO_API_URL: str = ""
    YOLO_MODEL_PATH: str = ""
    YOLO_FRAME_INTERVAL_SECONDS: int = 3
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 500
    # Redis 缓存（可选；未装/未启动时自动降级进程内缓存）
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
