from .admin import router as admin_router
from .public import router as public_router
from .system import router as system_router

__all__ = ["admin_router", "public_router", "system_router"]
