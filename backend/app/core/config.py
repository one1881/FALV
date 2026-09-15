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
    # A2A 等待上限按业务区分：起草目标 5 分钟，审核按下面的「内 < 外」不变量确定。
    # 【结构不变量】模型单次超时 < A2A 等待上限 < 任务总预算：
    #   起草 300 < 340 < 360      审核 300 < 480 < 600
    # 违反时外层看门狗先掐断，内层超时永远等不到（等于死配置）。
    A2A_TIMEOUT_SECONDS: float = 480.0
    A2A_DRAFTING_TIMEOUT_SECONDS: float = 340.0
    # 模型单次请求上限按业务区分：起草 300 秒，审核 300 秒。
    DRAFTING_MODEL_TIMEOUT_SECONDS: float = 300.0
    # 单次起草的端到端预算（秒）：超过即由看门狗截断并如实返回失败。
    # 实测生成 3865 字合同约需 190s、波动可达 300s，故预算放到 360s
    # （「5 分钟」物理上过紧，已与用户确认改为保稳优先）。
    DRAFTING_TOTAL_BUDGET_SECONDS: float = 360.0
    # 单次审核的端到端预算（秒）。审核是穷尽式逐条扫描（issues 不设上限）+ 4 个 skill，
    # 天然比起草重，且 agent_runtime 对审核允许「不合格时重新生成」一次 = 最坏 2 倍耗时。
    # 2026-09-11 实测：1186 字文档 145s、3751 字文档 205s（约 +0.023 s/字）；
    # 端到端（含根代理调度）193s。
    # ⚠️ 此前审核被 DRAFTING_TOTAL_BUDGET_SECONDS(360s) 误掐：3751 字文档若首轮不合格
    # （205×2=410s）必然超预算失败，且报错文案写成「起草」。故拆出独立预算。
    # 用户 2026-09-11 拍板：取 600s —— 宁可超时更早暴露，也不让用户干等 25 分钟。
    # 覆盖范围：3751 字文档重试一轮（205×2 + 调度 ≈ 470s）仍在预算内；
    # 逾 1 万字文档重试会超预算而失败，这是预期行为（按需上调此值即可）。
    REVIEW_TOTAL_BUDGET_SECONDS: float = 600.0
    # 模型单次输出上限：防流式输出失控（httpx read timeout 对流式不触发，
    # 实测曾出现 405s 仍未结束）。10240 ≈ 正常合同输出量的 1.4 倍。
    # 注意：reasoning token 也占额度。10240 实测会截断正常起草（含思考约需 10k+），
    # 放宽到 16384；极端失控由总预算看门狗（360s）兜底，而非靠压低 max_tokens。
    MODEL_MAX_TOKENS: int = 16384
    # 审核模型单次请求上限。必须 < A2A_TIMEOUT_SECONDS(480) < REVIEW_TOTAL_BUDGET_SECONDS(600)，
    # 否则内层超时永远等不到、外层先掐（等于死配置）。
    REVIEW_MODEL_TIMEOUT_SECONDS: float = 300.0
    ROOT_MODEL_TIMEOUT_SECONDS: float = 180.0
    # 不接受 temperature 参数的模型（前缀匹配，逗号分隔）：命中则不传该参数。
    # kimi-k3 实测传 temperature 会返回 400 InvalidParameter，硬传会导致起草直接失败。
    NO_TEMPERATURE_MODELS: str = "kimi"
    # 思考型模型的思考 token 预算（extra_body.thinking_budget），0=不限制。
    # 2026-09-11 实测：qwen3.8-2.4t-a95b 的 enable_thinking 被强制为 True（关不掉），
    # 起草时思考可烧光全部 max_tokens → finish_reason=length、正文 0 字 → 代码回溯
    # 抓到 prompt 当正文（908 字 bug）。加 thinking_budget=4096 后 reasoning 从
    # 10240 压到 ~110，耗时 22.8s→11.9s，正文反而更长（658→826 字）。
    THINKING_BUDGET: int = 4096
    # 接受 thinking_budget 参数的模型（前缀匹配，逗号分隔）：命中才注入该参数。
    THINKING_BUDGET_MODELS: str = "qwen3.8"
    # 快速起草路径（fast_drafting_service）总开关：默认关闭（2026-09-11 回退）。
    # 该路径存在 3 处阻断缺陷（路由判定 None 边界 / 落库少传 user_id / 前端轮询契约不符），
    # 未经修复不要打开；详见《合同起草快路径_诊断报告_20260911.md》。
    FAST_DRAFTING_ENABLED: bool = False
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
