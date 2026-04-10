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

# =====================================================================
# 并发多源采集配置
# =====================================================================

# 主开关: 是否启用并发多源采集 (保留兼容配置项，当前统一走并发+交叉校验)
CONCURRENT_FETCH_ENABLED = os.getenv("CONCURRENT_FETCH_ENABLED", "true").lower() == "true"

# 并发采集最大线程数
CONCURRENT_MAX_WORKERS = int(os.getenv("CONCURRENT_MAX_WORKERS", "7"))

# 并发采集超时 (秒)
CONCURRENT_FETCH_TIMEOUT = float(os.getenv("CONCURRENT_FETCH_TIMEOUT", "120.0"))

# =====================================================================
# 交叉校验配置
# =====================================================================

# 价格偏差容忍度 (0.5% = 0.005)
CROSS_VALIDATION_PRICE_TOLERANCE = float(os.getenv("CROSS_VALIDATION_PRICE_TOLERANCE", "0.005"))

# 成交量偏差容忍度 (5% = 0.05)
CROSS_VALIDATION_VOLUME_TOLERANCE = float(os.getenv("CROSS_VALIDATION_VOLUME_TOLERANCE", "0.05"))

# 涨跌幅偏差容忍度 (绝对值 1% = 0.01)
CROSS_VALIDATION_PCT_CHG_TOLERANCE = float(os.getenv("CROSS_VALIDATION_PCT_CHG_TOLERANCE", "0.01"))

# =====================================================================
# 数据源独立开关 (true=启用, false=禁用)
# =====================================================================

DATASOURCE_EFINANCE_ENABLED = os.getenv("DATASOURCE_EFINANCE_ENABLED", "true").lower() == "true"
DATASOURCE_AKSHARE_ENABLED = os.getenv("DATASOURCE_AKSHARE_ENABLED", "true").lower() == "true"
DATASOURCE_TUSHARE_ENABLED = os.getenv("DATASOURCE_TUSHARE_ENABLED", "true").lower() == "true"
DATASOURCE_BAOSTOCK_ENABLED = os.getenv("DATASOURCE_BAOSTOCK_ENABLED", "true").lower() == "true"
DATASOURCE_YFINANCE_ENABLED = os.getenv("DATASOURCE_YFINANCE_ENABLED", "true").lower() == "true"
DATASOURCE_LONGBRIDGE_ENABLED = os.getenv("DATASOURCE_LONGBRIDGE_ENABLED", "true").lower() == "true"
DATASOURCE_EASTMONEY_ENABLED = os.getenv("DATASOURCE_EASTMONEY_ENABLED", "true").lower() == "true"

# =====================================================================
# 各数据源独立配置
# =====================================================================

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

# YFinanceFetcher: Yahoo Finance, 免费
YFINANCE_SLEEP_MIN = float(os.getenv("YFINANCE_SLEEP_MIN", "1.5"))  # 秒
YFINANCE_SLEEP_MAX = float(os.getenv("YFINANCE_SLEEP_MAX", "3.0"))  # 秒

# LongbridgeFetcher: 长桥, 需要 Token
LONGBRIDGE_APP_KEY = os.getenv("LONGBRIDGE_APP_KEY", "")
LONGBRIDGE_APP_SECRET = os.getenv("LONGBRIDGE_APP_SECRET", "")
LONGBRIDGE_ACCESS_TOKEN = os.getenv("LONGBRIDGE_ACCESS_TOKEN", "")
LONGBRIDGE_SLEEP_MIN = float(os.getenv("LONGBRIDGE_SLEEP_MIN", "1.0"))  # 秒
LONGBRIDGE_SLEEP_MAX = float(os.getenv("LONGBRIDGE_SLEEP_MAX", "2.0"))  # 秒

# EastmoneyFetcher: 东财直连 API
EASTMONEY_SLEEP_MIN = float(os.getenv("EASTMONEY_SLEEP_MIN", "2.0"))  # 秒
EASTMONEY_SLEEP_MAX = float(os.getenv("EASTMONEY_SLEEP_MAX", "5.0"))  # 秒

# =====================================================================
# 熔断器配置
# =====================================================================

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
