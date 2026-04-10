"""
多数据源数据采集框架 (Multi-Source Data Provider) — 并发多源 + 交叉校验版

架构设计：
- 多个独立 Fetcher 实现（akshare/efinance/baostock/tushare/yfinance/longbridge/eastmoney）
- DataFetcherManager 统一并发编排:
  * 同时调用所有可用数据源
  * 汇总结果与失败原因
  * 交叉校验后返回最佳数据
- CrossValidator 多源数据交叉校验
- ErrorClassifier 智能错误分类与自适应限流
- CircuitBreaker 熔断器保护
- 每个数据源独立的防封禁策略

用法:
    from data_provider import DataFetcherManager
    manager = DataFetcherManager()
    df, source = manager.get_daily_data('600519')
    quote = manager.get_realtime_quote('600519')
    manager.close()
"""
import os
import logging

logger = logging.getLogger(__name__)

# 环境变量驱动的数据源配置
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")

__all__ = [
    "DataFetcherManager",
    "BaseFetcher",
    "DataFetchError",
    "RateLimitError",
    "DataSourceUnavailableError",
    "FetcherStartupStatus",
]
