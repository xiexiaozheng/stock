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

# 数据采集配置 — 通用
AKSHARE_REQUEST_INTERVAL = float(os.getenv("AKSHARE_REQUEST_INTERVAL", "0.8"))  # 秒
AKSHARE_MAX_RETRIES = int(os.getenv("AKSHARE_MAX_RETRIES", "3"))
CHROME_MCP_INTERVAL = float(os.getenv("CHROME_MCP_INTERVAL", "3.0"))  # 秒

# 数据采集配置 — 多数据源 (参考 daily_stock_analysis)
# EfinanceFetcher: 东方财富 efinance 库, 免费无需 Token
EFINANCE_SLEEP_MIN = float(os.getenv("EFINANCE_SLEEP_MIN", "1.5"))  # 秒
EFINANCE_SLEEP_MAX = float(os.getenv("EFINANCE_SLEEP_MAX", "3.0"))  # 秒
EFINANCE_TIMEOUT = float(os.getenv("EFINANCE_TIMEOUT", "10.0"))     # 秒

# AkshareFetcher: akshare 多爬虫, 需要更长延迟防封禁
AKSHARE_FETCHER_SLEEP_MIN = float(os.getenv("AKSHARE_FETCHER_SLEEP_MIN", "2.0"))  # 秒
AKSHARE_FETCHER_SLEEP_MAX = float(os.getenv("AKSHARE_FETCHER_SLEEP_MAX", "5.0"))  # 秒

# TushareFetcher: Tushare Pro API, 需要 Token (免费额度 80次/分钟)
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")
TUSHARE_QUOTA_PER_MINUTE = int(os.getenv("TUSHARE_QUOTA_PER_MINUTE", "80"))

# BaostockFetcher: 证券宝, 免费无需 Token, 但数据 T+1
BAOSTOCK_SLEEP_MIN = float(os.getenv("BAOSTOCK_SLEEP_MIN", "0.5"))  # 秒
BAOSTOCK_SLEEP_MAX = float(os.getenv("BAOSTOCK_SLEEP_MAX", "1.5"))  # 秒

# 熔断器配置 (参考 daily_stock_analysis CircuitBreaker)
CIRCUIT_BREAKER_FAILURE_THRESHOLD = int(os.getenv("CIRCUIT_BREAKER_FAILURE_THRESHOLD", "3"))
CIRCUIT_BREAKER_COOLDOWN_SECONDS = float(os.getenv("CIRCUIT_BREAKER_COOLDOWN_SECONDS", "300.0"))

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
