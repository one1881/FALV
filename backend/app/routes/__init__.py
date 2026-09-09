from .auth import router as auth_router
from .contracts import router as contracts_router
from .customers import router as customers_router
from .mcp import router as mcp_router
from .review import router as review_router
from .stats import router as stats_router
from .litigation import router as litigation_router

__all__ = [
    "auth_router",
    "contracts_router",
    "customers_router",
    "mcp_router",
    "review_router",
    "stats_router",
    "litigation_router",
]
