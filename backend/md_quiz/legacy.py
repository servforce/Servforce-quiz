from __future__ import annotations

from typing import Callable

from a2wsgi import WSGIMiddleware


class LazyWSGIBridge:
    def __init__(self, factory: Callable[[], object]):
        self.factory = factory
        self._app = None

    async def __call__(self, scope, receive, send):
        if self._app is None:
            self._app = WSGIMiddleware(self.factory())
        await self._app(scope, receive, send)


def build_legacy_bridge() -> LazyWSGIBridge:
    from web.app_factory import create_app

    return LazyWSGIBridge(create_app)
