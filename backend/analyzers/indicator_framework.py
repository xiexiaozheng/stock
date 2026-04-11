"""
指标计算基类与策略框架（BaseIndicator）

实现策略模式 (Strategy Pattern) / 插件化的基类接口，用于深度量化研究。

设计目标：
- 所有指标计算器继承 BaseIndicator 基类
- 统一的 compute() 接口：加载数据 → 计算指标 → 返回结果
- 通过 DataReader 接口标准化数据访问
- 支持未来扩展：DCF 模型参数、相对估值通道线、宏观经济指标关联等

使用方式::

    # 注册已有指标
    from analyzers.indicator_framework import IndicatorRegistry
    registry = IndicatorRegistry(db_session)
    result = registry.compute("pe_percentile", ts_code="000001.SZ", years=5)

    # 自定义新指标
    class MyIndicator(BaseIndicator):
        name = "my_indicator"
        description = "我的自定义指标"

        def compute(self, ts_code, **kwargs):
            df = self.reader.read_daily_market(ts_code)
            # ... 计算逻辑 ...
            return {"result": ...}
"""
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type

from sqlalchemy.orm import Session

from analyzers.data_reader import DataReader
from utils.logger import get_logger

logger = get_logger(__name__)


class BaseIndicator(ABC):
    """
    指标计算基类

    所有量化指标计算器必须继承此类，并实现 compute() 方法。
    基类自动提供 DataReader 实例用于数据访问。

    子类需要定义：
        - name (str): 指标唯一标识名
        - description (str): 指标描述
        - compute(ts_code, **kwargs) -> dict: 计算逻辑

    示例::

        class PEPercentileIndicator(BaseIndicator):
            name = "pe_percentile"
            description = "计算历史 PE-TTM 百分位"

            def compute(self, ts_code, **kwargs):
                years = kwargs.get("years", 5)
                df = self.reader.read_daily_market(ts_code, fields=["pe_ttm"])
                # ... 计算 ...
                return {"percentile": 35.5, "current_pe": 12.3}
    """

    # 子类必须定义
    name: str = ""
    description: str = ""

    def __init__(self, db: Session):
        """
        初始化指标计算器。

        :param db: SQLAlchemy Session，用于创建 DataReader
        """
        self.db = db
        self.reader = DataReader(db)

    @abstractmethod
    def compute(self, ts_code: str, **kwargs) -> Dict[str, Any]:
        """
        执行指标计算。

        :param ts_code: 股票代码（带后缀，如 000001.SZ）
        :param kwargs: 指标特有的额外参数
        :return: 计算结果字典
        """
        raise NotImplementedError

    def compute_batch(self, ts_codes: List[str], **kwargs) -> Dict[str, Dict[str, Any]]:
        """
        批量计算多只股票的指标（默认实现：逐只循环调用）。

        子类可以覆写此方法以实现更高效的批量计算。

        :param ts_codes: 股票代码列表
        :param kwargs: 额外参数
        :return: {ts_code: 结果字典}
        """
        results = {}
        for code in ts_codes:
            try:
                results[code] = self.compute(code, **kwargs)
            except Exception as e:
                logger.warning(f"指标 {self.name} 计算失败 [{code}]: {e}")
                results[code] = {"error": str(e)}
        return results

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self.name!r})>"


# =====================================================================
# 指标注册表 IndicatorRegistry
# =====================================================================

class IndicatorRegistry:
    """
    指标注册表

    管理所有可用的指标计算器，提供统一的发现和调用入口。
    新指标只需继承 BaseIndicator 并注册到此注册表即可使用。

    使用示例::

        registry = IndicatorRegistry(db_session)

        # 查看所有可用指标
        print(registry.list_indicators())

        # 计算指标
        result = registry.compute("pe_percentile", ts_code="000001.SZ", years=5)
    """

    # 类级别的指标类注册表
    _indicator_classes: Dict[str, Type[BaseIndicator]] = {}

    def __init__(self, db: Session):
        self.db = db
        self._instances: Dict[str, BaseIndicator] = {}

    @classmethod
    def register(cls, indicator_class: Type[BaseIndicator]) -> Type[BaseIndicator]:
        """
        注册一个指标类（可作为装饰器使用）。

        示例::

            @IndicatorRegistry.register
            class MyIndicator(BaseIndicator):
                name = "my_indicator"
                ...
        """
        if not indicator_class.name:
            raise ValueError(
                f"指标类 {indicator_class.__name__} 缺少 name 属性"
            )
        cls._indicator_classes[indicator_class.name] = indicator_class
        logger.debug(f"注册指标: {indicator_class.name}")
        return indicator_class

    def _get_instance(self, name: str) -> BaseIndicator:
        """获取或创建指标实例（惰性初始化）"""
        if name not in self._instances:
            cls = self._indicator_classes.get(name)
            if cls is None:
                raise ValueError(
                    f"未知指标: {name}，可用指标: {list(self._indicator_classes.keys())}"
                )
            self._instances[name] = cls(self.db)
        return self._instances[name]

    def compute(self, indicator_name: str, ts_code: str, **kwargs) -> Dict[str, Any]:
        """
        调用指定指标的计算方法。

        :param indicator_name: 指标名称
        :param ts_code: 股票代码
        :param kwargs: 指标参数
        :return: 计算结果字典
        """
        indicator = self._get_instance(indicator_name)
        return indicator.compute(ts_code, **kwargs)

    def compute_batch(
        self, indicator_name: str, ts_codes: List[str], **kwargs
    ) -> Dict[str, Dict[str, Any]]:
        """批量计算指标"""
        indicator = self._get_instance(indicator_name)
        return indicator.compute_batch(ts_codes, **kwargs)

    @classmethod
    def list_indicators(cls) -> List[Dict[str, str]]:
        """列出所有已注册的指标"""
        return [
            {"name": name, "description": klass.description}
            for name, klass in cls._indicator_classes.items()
        ]
