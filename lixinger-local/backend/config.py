"""配置管理模块"""
import os
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent

# 数据库配置
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/data/lixinger.db")

# 应用配置
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
APP_DEBUG = os.getenv("APP_DEBUG", "false").lower() == "true"

# CORS 配置
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")

# 数据采集配置
AKSHARE_REQUEST_INTERVAL = float(os.getenv("AKSHARE_REQUEST_INTERVAL", "0.8"))  # 秒
AKSHARE_MAX_RETRIES = int(os.getenv("AKSHARE_MAX_RETRIES", "3"))
CHROME_MCP_INTERVAL = float(os.getenv("CHROME_MCP_INTERVAL", "3.0"))  # 秒

# 调度配置
SCHEDULE_INCREMENTAL_TIME = os.getenv("SCHEDULE_INCREMENTAL_TIME", "15:35")  # 每个交易日收盘后
SCHEDULE_FULL_REFRESH_DAY = os.getenv("SCHEDULE_FULL_REFRESH_DAY", "sunday")  # 每周日

# 日志配置
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", str(BASE_DIR / "data" / "app.log"))

# 数据采集历史范围
HISTORY_YEARS_QUOTES = int(os.getenv("HISTORY_YEARS_QUOTES", "3"))     # 行情历史年数
HISTORY_YEARS_FINANCIALS = int(os.getenv("HISTORY_YEARS_FINANCIALS", "5"))  # 财务历史年数
HISTORY_YEARS_VALUATIONS = int(os.getenv("HISTORY_YEARS_VALUATIONS", "5"))  # 估值历史年数
