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
    # 起草/审核专用模型（留空则回落到 QWEN_MODEL）
    DRAFT_REVIEW_MODEL: str = ""
    ROOT_AGENT_MODEL: str = ""  # 主控根代理专用模型；留空回落 DRAFT_REVIEW_MODEL
    # A2A 多智能体（起草 :8001 / 审核 :8002 独立子代理服务）
    A2A_ENABLED: bool = True
    A2A_TOKEN: str = ""          # 留空=不鉴权（本机开发）；设置后 message/send 须带同值 X-A2A-Token
    # A2A 等待上限按业务区分：起草目标 5 分钟，审核允许更长。
    A2A_TIMEOUT_SECONDS: float = 600.0
    A2A_DRAFTING_TIMEOUT_SECONDS: float = 300.0
    # 模型单次请求上限按业务区分：起草 180 秒，审核保留 600 秒。
    DRAFTING_MODEL_TIMEOUT_SECONDS: float = 180.0
    REVIEW_MODEL_TIMEOUT_SECONDS: float = 600.0
    ROOT_MODEL_TIMEOUT_SECONDS: float = 180.0
    # False=httpx 忽略 HTTP_PROXY 环境变量：本机代理无 no_proxy，
    # 会把 127.0.0.1 的回环 A2A 调用也绕去代理中转，纯属浪费。
    A2A_TRUST_ENV: bool = False
    DRAFTING_AGENT_PORT: int = 8001
    REVIEW_AGENT_PORT: int = 8002
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

    @property
    def draft_review_llm_model(self) -> str:
        """文书起草/审核专用模型；未配置时回落主模型。"""
        return self.DRAFT_REVIEW_MODEL or self.primary_llm_model

    @property
    def root_agent_llm_model(self) -> str:
        """主控根代理模型；未配置时回落起草/审核模型（默认同一模型）。"""
        return self.ROOT_AGENT_MODEL or self.draft_review_llm_model

    VIDEO_UNDERSTAND_MAX_FRAMES: int = 6
    VIDEO_UNDERSTAND_FRAME_INTERVAL: int = 3
    YOLO_API_URL: str = ""
    YOLO_MODEL_PATH: str = ""
    YOLO_FRAME_INTERVAL_SECONDS: int = 3
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 500
    # 本地语义检索模型（vector_search_server 用；未装/未配置时自动降级哈希向量）
    BGE_MODEL_PATH: str = ""
    # A2A 多智能体：起草/审核子代理独立服务（主代理经 Agent Card 发现 + message/send 派活）
    A2A_ENABLED: bool = True
    DRAFTING_AGENT_PORT: int = 8001
    REVIEW_AGENT_PORT: int = 8002
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
