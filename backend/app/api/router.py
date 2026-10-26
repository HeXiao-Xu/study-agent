"""v1 路由汇总：只做 include，不写业务。"""
from fastapi import APIRouter

from app.api.v1 import auth

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)

__all__ = ["api_router"]