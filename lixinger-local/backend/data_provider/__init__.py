"""
多数据源数据采集框架 (Multi-Source Data Provider) — 并发多源 + 交叉校验版

架构设计：
- 多个独立 Fetcher 实现（akshare/efinance/baostock/tushare/yfinance/longbridge/eastmoney）
- DataFetcherManager 统一编排:
  * 并发模式: 同时调用所有数据源，交叉校验后返回最佳数据
  * Failover 模式: 按优先级顺序尝试（向后兼容）
- CrossValidator 多源数据交叉校验
- ErrorClassifier 智能错误分类与自适应限流
- CircuitBreaker 熔断器保护
- 每个数据源独立的防封禁策略

数据源优先级:
  Priority 0: EfinanceFetcher  (东方财富 efinance 库, 免费无需 Token)
  Priority 1: AkshareFetcher   (akshare 多信源并发: 东财+新浪+163)
  Priority 2: TushareFetcher   (Tushare Pro, 可选 Token)
  Priority 3: BaostockFetcher  (证券宝, 免费, T+1 数据)
  Priority 4: YFinanceFetcher  (Yahoo Finance, 免费)
  Priority 5: LongbridgeFetcher(长桥 OpenAPI, 需要 Token)
  Priority 6: EastmoneyFetcher (东财直连 HTTP API, 免费)

用法:
    from data_provider import DataFetcherManager
    manager = DataFetcherManager()
    df, source = manager.get_daily_data('600519')       # 并发模式 (默认)
    df, source = manager.get_daily_data('600519', concurrent=False)  # failover 模式
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
