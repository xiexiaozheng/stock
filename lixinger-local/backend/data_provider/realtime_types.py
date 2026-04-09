"""
统一实时行情类型定义与熔断器

参考 ZhuLinsen/daily_stock_analysis data_provider/realtime_types.py

包含:
- RealtimeSource: 数据源枚举
- UnifiedRealtimeQuote: 统一实时行情 dataclass
- ChipDistribution: 筹码分布 dataclass
- CircuitBreaker: 熔断器 (CLOSED → OPEN → HALF_OPEN → CLOSED)
"""
import time
import threading
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =====================================================================
# 数据源枚举
# =====================================================================

class RealtimeSource(str, Enum):
    """实时行情数据源标识"""
    EFINANCE = "efinance"
    AKSHARE_EM = "akshare_em"       # 东方财富 (via akshare)
    AKSHARE_SINA = "akshare_sina"   # 新浪财经 (via akshare)
    AKSHARE_QQ = "akshare_qq"       # 腾讯财经 (via akshare)
    TUSHARE = "tushare"
    BAOSTOCK = "baostock"
    SINA = "sina"                   # 直连新浪 API
    TENCENT = "tencent"             # 直连腾讯 API
    FALLBACK = "fallback"


# =====================================================================
# 统一实时行情
# =====================================================================

@dataclass
class UnifiedRealtimeQuote:
    """
    统一实时行情 dataclass

    参考 daily_stock_analysis 设计，所有数据源的实时行情统一映射到此结构。
    支持字段补充（从多个数据源合并缺失字段）。
    """
    code: str
    name: str = ""
    source: RealtimeSource = RealtimeSource.FALLBACK

    # ---- 核心价格 ----
    price: Optional[float] = None           # 最新价
    change_pct: Optional[float] = None      # 涨跌幅 (%)
    change_amount: Optional[float] = None   # 涨跌额

    # ---- 成交量 ----
    volume: Optional[int] = None            # 成交量 (手)
    amount: Optional[float] = None          # 成交额 (元)
    volume_ratio: Optional[float] = None    # 量比
    turnover_rate: Optional[float] = None   # 换手率 (%)
    amplitude: Optional[float] = None       # 振幅 (%)

    # ---- 价格档位 ----
    open_price: Optional[float] = None      # 开盘价
    high: Optional[float] = None            # 最高价
    low: Optional[float] = None             # 最低价
    pre_close: Optional[float] = None       # 昨收价

    # ---- 估值 ----
    pe_ratio: Optional[float] = None        # 市盈率 (动态)
    pb_ratio: Optional[float] = None        # 市净率
    total_mv: Optional[float] = None        # 总市值 (元)
    circ_mv: Optional[float] = None         # 流通市值 (元)

    # ---- 扩展 ----
    change_60d: Optional[float] = None      # 60日涨跌幅 (%)
    high_52w: Optional[float] = None        # 52周最高
    low_52w: Optional[float] = None         # 52周最低

    def to_dict(self) -> Dict[str, Any]:
        """转为字典，跳过 None 值"""
        result = {}
        for k, v in self.__dict__.items():
            if v is not None:
                if isinstance(v, RealtimeSource):
                    result[k] = v.value
                else:
                    result[k] = v
        return result

    def has_basic_data(self) -> bool:
        """是否具备基本价格数据"""
        return self.price is not None and self.price > 0

    def has_volume_data(self) -> bool:
        """是否具备量能数据 (量比或换手率)"""
        return (self.volume_ratio is not None) or (self.turnover_rate is not None)

    def has_valuation_data(self) -> bool:
        """是否具备估值数据"""
        return (self.pe_ratio is not None) or (self.pb_ratio is not None)

    def needs_supplement(self) -> bool:
        """是否需要从其他数据源补充字段"""
        return not self.has_volume_data() or not self.has_valuation_data()


def merge_quote_fields(primary: UnifiedRealtimeQuote, secondary: UnifiedRealtimeQuote) -> None:
    """
    将 secondary 的非空字段补充到 primary 中（不覆盖已有数据）。
    参考 daily_stock_analysis 的 _merge_quote_fields 逻辑。
    """
    supplement_fields = [
        "volume_ratio", "turnover_rate", "amplitude",
        "pe_ratio", "pb_ratio", "total_mv", "circ_mv",
        "change_60d", "high_52w", "low_52w",
    ]
    for f in supplement_fields:
        if getattr(primary, f) is None and getattr(secondary, f) is not None:
            setattr(primary, f, getattr(secondary, f))


# =====================================================================
# 筹码分布
# =====================================================================

@dataclass
class ChipDistribution:
    """
    筹码分布 dataclass

    参考 daily_stock_analysis ChipDistribution 设计。
    """
    code: str
    date: str                       # 交易日期
    source: str = "akshare"

    # 获利比例
    profit_ratio: float = 0.0       # 获利盘比例 (0-1)
    avg_cost: float = 0.0           # 平均成本

    # 90% 筹码集中度
    cost_90_low: float = 0.0
    cost_90_high: float = 0.0
    concentration_90: float = 0.0   # (high - low) / (high + low) × 100

    # 70% 筹码集中度
    cost_70_low: float = 0.0
    cost_70_high: float = 0.0
    concentration_70: float = 0.0

    def get_chip_status(self, current_price: float) -> str:
        """获取筹码状态的中文描述"""
        parts = []
        if self.profit_ratio > 0.9:
            parts.append("获利盘极高(>90%)")
        elif self.profit_ratio > 0.7:
            parts.append("获利盘较高(>70%)")
        elif self.profit_ratio < 0.3:
            parts.append("套牢盘较重(<30%获利)")

        if 0 < self.concentration_90 < 8:
            parts.append("筹码高度集中")
        elif self.concentration_90 > 20:
            parts.append("筹码较为分散")

        if self.avg_cost > 0:
            if current_price > self.avg_cost:
                parts.append("现价高于平均成本")
            else:
                parts.append("现价低于平均成本")

        return "；".join(parts) if parts else "筹码分布正常"


# =====================================================================
# 熔断器 (Circuit Breaker)
# =====================================================================

class CircuitBreakerState(str, Enum):
    """熔断器状态"""
    CLOSED = "closed"         # 正常（放行请求）
    OPEN = "open"             # 熔断（拒绝请求）
    HALF_OPEN = "half_open"   # 半开（尝试恢复）


class CircuitBreaker:
    """
    熔断器模式实现

    参考 daily_stock_analysis 的 CircuitBreaker：
    - CLOSED (正常): 请求正常通过。连续失败 failure_threshold 次后切换到 OPEN。
    - OPEN (熔断): 拒绝请求，等待 cooldown_seconds 秒。冷却结束后切换到 HALF_OPEN。
    - HALF_OPEN (半开): 允许 half_open_max_calls 次探测请求。
      成功则回到 CLOSED，失败则回到 OPEN。

    线程安全：所有状态操作通过 Lock 保护。
    每个数据源独立跟踪状态。
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 300.0,
        half_open_max_calls: int = 1,
    ):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.half_open_max_calls = half_open_max_calls
        self._states: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _get_state(self, source: str) -> Dict[str, Any]:
        """获取或初始化数据源状态"""
        if source not in self._states:
            self._states[source] = {
                "state": CircuitBreakerState.CLOSED,
                "failure_count": 0,
                "last_failure_time": 0.0,
                "half_open_calls": 0,
                "last_error": None,
            }
        return self._states[source]

    def is_available(self, source: str) -> bool:
        """
        检查数据源是否可用。

        - CLOSED: 可用
        - OPEN: 检查冷却是否结束，结束则切 HALF_OPEN 并返回可用
        - HALF_OPEN: 允许有限次请求
        """
        with self._lock:
            s = self._get_state(source)
            state = s["state"]

            if state == CircuitBreakerState.CLOSED:
                return True

            if state == CircuitBreakerState.OPEN:
                elapsed = time.time() - s["last_failure_time"]
                if elapsed >= self.cooldown_seconds:
                    # 冷却结束，进入 HALF_OPEN
                    s["state"] = CircuitBreakerState.HALF_OPEN
                    s["half_open_calls"] = 0
                    logger.info(
                        f"CircuitBreaker [{source}]: OPEN → HALF_OPEN "
                        f"(冷却 {elapsed:.0f}s 已过)"
                    )
                    return True
                else:
                    remaining = self.cooldown_seconds - elapsed
                    logger.debug(
                        f"CircuitBreaker [{source}]: OPEN, "
                        f"剩余冷却 {remaining:.0f}s"
                    )
                    return False

            if state == CircuitBreakerState.HALF_OPEN:
                return s["half_open_calls"] < self.half_open_max_calls

            return False

    def record_success(self, source: str) -> None:
        """记录成功请求"""
        with self._lock:
            s = self._get_state(source)
            if s["state"] == CircuitBreakerState.HALF_OPEN:
                logger.info(f"CircuitBreaker [{source}]: HALF_OPEN → CLOSED (探测成功)")
            s["state"] = CircuitBreakerState.CLOSED
            s["failure_count"] = 0
            s["last_error"] = None

    def record_failure(self, source: str, error: Optional[str] = None) -> None:
        """记录失败请求"""
        with self._lock:
            s = self._get_state(source)
            s["failure_count"] += 1
            s["last_failure_time"] = time.time()
            s["last_error"] = error

            if s["state"] == CircuitBreakerState.HALF_OPEN:
                s["state"] = CircuitBreakerState.OPEN
                logger.warning(
                    f"CircuitBreaker [{source}]: HALF_OPEN → OPEN "
                    f"(探测失败: {error})"
                )
            elif s["failure_count"] >= self.failure_threshold:
                s["state"] = CircuitBreakerState.OPEN
                logger.warning(
                    f"CircuitBreaker [{source}]: CLOSED → OPEN "
                    f"(连续失败 {s['failure_count']} 次, "
                    f"冷却 {self.cooldown_seconds}s)"
                )

    def record_inconclusive(self, source: str) -> None:
        """记录不确定的请求结果 (用于 HALF_OPEN 计数)"""
        with self._lock:
            s = self._get_state(source)
            if s["state"] == CircuitBreakerState.HALF_OPEN:
                s["half_open_calls"] += 1

    def get_status(self, source: str) -> Dict[str, Any]:
        """获取数据源的熔断器状态（调试用）"""
        with self._lock:
            s = self._get_state(source)
            return {
                "source": source,
                "state": s["state"].value,
                "failure_count": s["failure_count"],
                "last_error": s["last_error"],
            }

    def get_all_status(self) -> List[Dict[str, Any]]:
        """获取所有数据源的熔断器状态"""
        with self._lock:
            return [self.get_status(src) for src in self._states]

    def reset(self, source: Optional[str] = None) -> None:
        """重置熔断器状态"""
        with self._lock:
            if source:
                if source in self._states:
                    del self._states[source]
            else:
                self._states.clear()


# =====================================================================
# 全局熔断器实例
# =====================================================================

# 实时行情熔断器: 3次失败，5分钟冷却
_realtime_circuit_breaker = CircuitBreaker(
    failure_threshold=3,
    cooldown_seconds=300.0,
    half_open_max_calls=1,
)

# 筹码分布熔断器: 2次失败，10分钟冷却（更保守）
_chip_circuit_breaker = CircuitBreaker(
    failure_threshold=2,
    cooldown_seconds=600.0,
    half_open_max_calls=1,
)

# 日K线熔断器: 3次失败，5分钟冷却
_daily_circuit_breaker = CircuitBreaker(
    failure_threshold=3,
    cooldown_seconds=300.0,
    half_open_max_calls=1,
)


def get_realtime_circuit_breaker() -> CircuitBreaker:
    return _realtime_circuit_breaker


def get_chip_circuit_breaker() -> CircuitBreaker:
    return _chip_circuit_breaker


def get_daily_circuit_breaker() -> CircuitBreaker:
    return _daily_circuit_breaker


# =====================================================================
# 工具函数
# =====================================================================

def safe_float(value: Any) -> Optional[float]:
    """安全浮点数转换"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            v = float(value)
            import math
            return None if math.isnan(v) or math.isinf(v) else v
        except (TypeError, ValueError):
            return None
    s = str(value).strip().replace(",", "").replace("%", "")
    if not s or s in ("-", "--", "nan", "None", "N/A"):
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def safe_int(value: Any) -> Optional[int]:
    """安全整数转换"""
    f = safe_float(value)
    return int(f) if f is not None else None
