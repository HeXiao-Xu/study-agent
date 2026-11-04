"""v1 路由汇总：只做 include，不写业务。"""
from fastapi import APIRouter

from app.api.v1 import (
    admin,
    auth,
    files,
    kp,
    mastery,
    mistakes,
    notes,
    qa,
    questions,
    retrieval,
    stats,
    tasks,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(notes.router)
api_router.include_router(files.router)
api_router.include_router(tasks.router)
api_router.include_router(kp.router)
api_router.include_router(questions.router)
api_router.include_router(mistakes.router)
api_router.include_router(mastery.router)
api_router.include_router(stats.router)
api_router.include_router(retrieval.router)
api_router.include_router(qa.router)
api_router.include_router(admin.router)

__all__ = ["api_router"]