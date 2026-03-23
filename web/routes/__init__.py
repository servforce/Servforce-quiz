from .admin import register_admin_routes
from .public import register_public_routes
from .shared import register_shared_routes

__all__ = [
    "register_admin_routes",
    "register_public_routes",
    "register_shared_routes",
]
