"""
FastAPI 应用入口

启动方式：
    cd backend
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""
import sys
import os

# 确保可以导入本目录下的模块
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from config import APP_HOST, APP_PORT, APP_DEBUG, CORS_ORIGINS
from database import init_db
from utils.logger import setup_logging
from api.stocks import router as stocks_router
from api.screener import router as screener_router
from api.watchlist import router as watchlist_router
from api.collector import router as collector_router

# 初始化日志
setup_logging()
logger = logging.getLogger(__name__)

# 创建 FastAPI 应用
app = FastAPI(
    title="LiXinger Local - 个人金融数据平台",
    description="基于 akshare 的个人 A 股数据分析平台",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(stocks_router)
app.include_router(screener_router)
app.include_router(watchlist_router)
app.include_router(collector_router)


@app.on_event("startup")
async def startup_event():
    """应用启动时初始化数据库"""
    logger.info("应用启动，初始化数据库...")
    init_db()

    # 启动定时调度器
    try:
        from collectors.scheduler import setup_scheduler
        setup_scheduler()
    except Exception as e:
        logger.warning(f"调度器启动失败: {e}")

    logger.info("应用启动完成")


@app.get("/api/health")
def health_check():
    """健康检查"""
    return {"status": "ok", "version": "1.0.0"}


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"未处理异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "内部服务器错误，请查看后端日志"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=APP_HOST,
        port=APP_PORT,
        reload=APP_DEBUG,
        log_level="info",
    )
