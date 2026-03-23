from __future__ import annotations

from fastapi import Request


def get_container(request: Request):
    return request.app.state.container
