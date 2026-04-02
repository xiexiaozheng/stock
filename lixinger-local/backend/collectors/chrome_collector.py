"""
Chrome MCP 爬虫模块（补充数据源）

当 akshare 无法满足需求时，使用浏览器自动化爬取补充数据。
当前提供框架实现，具体页面适配需根据目标网站结构调整。
"""
import logging
import time
import random
from typing import Optional, Dict, Any

from utils.logger import get_logger

logger = get_logger(__name__)


class ChromeCollector:
    """
    Chrome MCP 浏览器爬虫封装。

    注意：此模块依赖 Chrome MCP 工具（mcp__chrome__*），
    在没有 Chrome MCP 环境时调用会抛出 ChromeMCPNotAvailableError。
    """

    # 请求间隔（秒）
    MIN_INTERVAL = 2.0
    MAX_INTERVAL = 5.0

    def __init__(self):
        self._last_request_time = 0.0
        self._visited_cache: Dict[str, float] = {}  # url -> last_visited_timestamp

    def _rate_limit(self):
        """控制请求频率，随机延迟 2-5 秒"""
        elapsed = time.time() - self._last_request_time
        interval = random.uniform(self.MIN_INTERVAL, self.MAX_INTERVAL)
        if elapsed < interval:
            time.sleep(interval - elapsed)
        self._last_request_time = time.time()

    def _is_recently_visited(self, cache_key: str, ttl_hours: float = 24.0) -> bool:
        """检查是否在 TTL 内已访问过（避免重复爬取）"""
        if cache_key in self._visited_cache:
            elapsed_h = (time.time() - self._visited_cache[cache_key]) / 3600
            if elapsed_h < ttl_hours:
                return True
        return False

    def _mark_visited(self, cache_key: str):
        self._visited_cache[cache_key] = time.time()

    # ======================== 场景1：东方财富资金流向 ========================

    def collect_eastmoney_capital_flow(self, stock_code: str) -> Optional[Dict]:
        """
        爬取东方财富资金流向数据。

        :param stock_code: 6位股票代码
        :return: {'inflow': float, 'outflow': float, 'net_inflow': float} or None
        """
        cache_key = f"eastmoney_flow_{stock_code}"
        if self._is_recently_visited(cache_key, ttl_hours=4):
            logger.debug(f"{stock_code} 资金流向数据已缓存，跳过")
            return None

        self._rate_limit()
        url = f"https://data.eastmoney.com/zjlx/{stock_code}.html"
        logger.info(f"爬取东方财富资金流向: {url}")

        try:
            # 使用 Chrome MCP 工具（需要 MCP 环境）
            # mcp__chrome__navigate(url)
            # time.sleep(2)
            # text = mcp__chrome__get_visible_text()
            # 解析文本提取资金流向数据 ...
            raise NotImplementedError(
                "Chrome MCP 环境未配置，请确保 mcp__chrome__* 工具可用。\n"
                "参考文档：https://github.com/modelcontextprotocol/servers"
            )
        except NotImplementedError:
            logger.warning(f"Chrome MCP 不可用，跳过 {stock_code} 资金流向爬取")
            return None
        except Exception as e:
            logger.error(f"爬取东方财富资金流向失败 [{stock_code}]: {e}")
            return None

    # ======================== 场景2：公告列表 ========================

    def collect_announcements(self, stock_code: str, page: int = 1) -> list:
        """
        爬取巨潮资讯网公告列表。

        :param stock_code: 6位股票代码
        :param page: 页码
        :return: 公告列表
        """
        cache_key = f"announcements_{stock_code}_{page}"
        if self._is_recently_visited(cache_key, ttl_hours=12):
            return []

        self._rate_limit()
        url = (
            f"http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?"
            f"url=disclosure/list/search&keyWord={stock_code}"
        )
        logger.info(f"爬取巨潮公告列表: {stock_code}")

        try:
            raise NotImplementedError("Chrome MCP 环境未配置")
        except NotImplementedError:
            logger.warning(f"Chrome MCP 不可用，跳过 {stock_code} 公告爬取")
            return []
        except Exception as e:
            logger.error(f"爬取公告失败 [{stock_code}]: {e}")
            return []

    # ======================== 场景3：理杏仁补充数据 ========================

    def collect_lixinger_supplement(
        self,
        stock_code: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        登录理杏仁并爬取特有指标（ROIC、自由现金流收益率等）。

        :param stock_code: 股票代码
        :param username: 理杏仁账号（可选）
        :param password: 理杏仁密码（可选）
        :return: 补充指标字典
        """
        if not username or not password:
            logger.warning("未提供理杏仁账号，跳过补充数据爬取")
            return None

        cache_key = f"lixinger_{stock_code}"
        if self._is_recently_visited(cache_key, ttl_hours=24):
            return None

        self._rate_limit()
        logger.info(f"尝试从理杏仁爬取 {stock_code} 补充数据...")

        try:
            raise NotImplementedError("Chrome MCP 环境未配置")
        except NotImplementedError:
            logger.warning("Chrome MCP 不可用，跳过理杏仁补充数据爬取")
            return None
        except Exception as e:
            logger.error(f"理杏仁数据爬取失败 [{stock_code}]: {e}")
            return None
