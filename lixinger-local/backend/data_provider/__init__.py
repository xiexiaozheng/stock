"""
多数据源数据采集框架 (Multi-Source Data Provider)

参考 ZhuLinsen/daily_stock_analysis 的 data_provider 架构设计：
- 多个独立 Fetcher 实现（akshare/efinance/baostock/tushare）
- DataFetcherManager 统一编排，自动按优先级 failover
- CircuitBreaker 熔断器保护
- 每个数据源独立的防封禁策略

优先级:
  Priority 0: EfinanceFetcher  (东方财富 efinance 库, 免费无需 Token)
  Priority 1: AkshareFetcher   (akshare 多数据源爬虫)
  Priority 2: TushareFetcher   (Tushare Pro, 可选 Token)
  Priority 3: BaostockFetcher  (证券宝, 免费, T+1 数据)

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
]
