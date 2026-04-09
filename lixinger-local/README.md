# 理杏仁 Local — 个人 A 股金融数据平台

> 基于 [akshare](https://akshare.akfamily.xyz/) + FastAPI + React 构建的本地个人金融数据平台，
> 功能对标 [lixinger.com](https://www.lixinger.com/)，完全本地部署，无需付费 API。
> 数据获取与分析逻辑参考 [daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis)。

---

## 功能特性

- **股票列表**：全市场 A 股（沪/深/北），支持搜索
- **行情数据**：日 K 线图（前复权），增量更新
- **财务分析**：利润表、资产负债表、现金流量表，自动计算 ROE/毛利率/负债率等衍生指标
- **估值历史**：PE-TTM / PB / PS-TTM / PCF-TTM / 股息率历史曲线，含历史分位线标注
- **分红记录**：历年派息/送转记录
- **筛选器**：多条件组合选股（AND/OR），支持多时间窗口，内置5个预设模板
- **自选股**：添加/删除/导出 CSV
- **数据采集**：定时增量更新（每个交易日 15:35）+ 每周全量刷新，支持手动触发
- **核心数据表**：三张高性能核心表（StockBasic / DailyMarketValuation / QuarterlyFinance），联合主键 + 联合索引优化查询
- **指标计算框架**：策略模式 (Strategy Pattern) 基类接口，支持插件化扩展量化指标
- **内置指标**：PE 百分位、PB 百分位、股息率百分位

---

## 快速开始

### 1. 本地开发（不使用 Docker）

#### 环境要求
- Python 3.11+
- Node.js 18+

#### 后端启动
```bash
cd lixinger-local

# 安装依赖
pip install -r backend/requirements.txt

# 初始化数据库
python scripts/init_db.py

# （可选）检查 akshare 接口可用性
python scripts/check_akshare.py

# （可选）首次全量采集（时间较长，可先用 --codes 指定几只股票测试）
python scripts/first_collect.py --codes 000001 600519 300750

# 启动后端服务
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

#### 前端启动
```bash
cd lixinger-local/frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

访问：http://localhost:5173

### 2. Docker 部署

```bash
cd lixinger-local
docker-compose up -d
```

访问：http://localhost:3000

---

## 项目结构

```
lixinger-local/
├── backend/
│   ├── main.py                    # FastAPI 入口
│   ├── config.py                  # 配置管理（支持环境变量覆盖）
│   ├── database.py                # 数据库初始化（SQLite + WAL 模式）
│   ├── models/                    # ORM 模型 + Pydantic Schema
│   │   ├── stock.py               # stocks / daily_quotes / watchlist
│   │   ├── financial.py           # financials
│   │   ├── valuation.py           # valuations / dividends
│   │   ├── screener.py            # screeners / industries
│   │   └── core.py                # ★ 核心表: StockBasic / DailyMarketValuation / QuarterlyFinance
│   ├── api/                       # FastAPI 路由
│   │   ├── stocks.py              # 股票列表/详情/行情/财务/估值/仪表盘
│   │   ├── screener.py            # 筛选器运行/预设/保存
│   │   ├── watchlist.py           # 自选股管理
│   │   ├── collector.py           # 数据采集触发/状态
│   │   └── core.py                # ★ 核心表API + 指标计算 API
│   ├── collectors/                # 数据采集
│   │   ├── base.py                # 基类（upsert、限流）
│   │   ├── akshare_collector.py   # akshare 主采集器（旧表）
│   │   ├── core_collector.py      # ★ 核心表采集器（日度量价估值 + 季度财务）
│   │   ├── chrome_collector.py    # Chrome MCP 补充爬虫（框架）
│   │   └── scheduler.py           # 调度器（增量/全量，含核心表）
│   ├── analyzers/
│   │   ├── screener_engine.py     # 筛选引擎（多条件、多时间窗口）
│   │   ├── metrics.py             # 增长率、分位数等指标计算
│   │   ├── data_reader.py         # ★ 数据读取接口（标准化 DataFrame 访问）
│   │   ├── indicator_framework.py # ★ 指标计算基类 + 注册表（策略模式）
│   │   └── builtin_indicators.py  # ★ 内置指标（PE/PB/股息率百分位）
│   ├── utils/
│   │   ├── api_compat.py          # akshare 接口兼容层（主要维护点）
│   │   ├── retry.py               # 指数退避重试装饰器
│   │   ├── rate_limiter.py        # 请求限流器
│   │   └── logger.py              # 统一日志配置
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/                 # 页面组件
│   │   │   ├── Dashboard.tsx      # 仪表盘
│   │   │   ├── StockDetail.tsx    # 股票详情（估值/财务/分红/K线）
│   │   │   ├── Screener.tsx       # 筛选器
│   │   │   ├── Watchlist.tsx      # 自选股
│   │   │   └── StockList.tsx      # 股票列表
│   │   ├── components/
│   │   │   ├── charts/
│   │   │   │   ├── ValuationChart.tsx  # PE/PB 历史走势
│   │   │   │   ├── FinancialChart.tsx  # 财务指标图
│   │   │   │   └── KLineChart.tsx      # K 线图（含成交量）
│   │   │   ├── StockTable.tsx     # 通用股票数据表格
│   │   │   ├── MetricCard.tsx     # 指标卡片（含分位进度条）
│   │   │   └── SearchBar.tsx      # 全局股票搜索框
│   │   ├── services/api.ts        # 后端 API 调用封装（axios）
│   │   ├── hooks/useWatchlist.ts  # 自选股状态管理（zustand）
│   │   └── types/index.ts         # TypeScript 类型定义
│   ├── tailwind.config.js         # 暗色主题配色
│   └── package.json
├── data/
│   └── lixinger.db                # SQLite 数据库
├── scripts/
│   ├── init_db.py                 # 数据库初始化
│   ├── first_collect.py           # 首次全量采集（支持 --core-only 模式）
│   ├── check_akshare.py           # akshare 接口健康检查
│   └── export_csv.py              # 数据导出（含核心表）
├── docker-compose.yml
└── README.md                      # 本文档
```

---

## 数据库表结构

### 旧表（保持向后兼容）

| 表名 | 说明 |
|---|---|
| stocks | 股票基础信息（代码、名称、交易所、行业） |
| daily_quotes | 日K线行情（前复权） |
| financials | 财务报表（利润表+资产负债表+现金流） |
| valuations | 估值历史（PE/PB/PS/市值/股息率） |
| dividends | 分红记录 |
| watchlist | 自选股 |
| screeners | 保存的筛选条件 |
| industries | 行业板块 |
| industry_members | 板块成分股 |

### ★ 核心表（新增，高性能设计）

| 表名 | 主键 | 说明 |
|---|---|---|
| stock_basic | ts_code | 股票基础信息（带后缀代码，如 000001.SZ） |
| daily_market_valuation | ts_code + trade_date | 日度量价与估值（收盘价、换手率、PE/PB/PS/PCF/股息率、总市值） |
| quarterly_finance | ts_code + end_date | 季度财务核心（营收、净利润、扣非、经营现金流、ROE、毛利率、资产负债率） |

---

## akshare 接口兼容性说明

akshare 接口更新较频繁。本项目通过 `backend/utils/api_compat.py` 提供统一的接口映射层：

1. **首次运行前**，建议执行健康检查：
   ```bash
   python scripts/check_akshare.py
   ```

2. **如果某接口报错**，在 `backend/utils/api_compat.py` 的 `AKSHARE_API_MAP` 中
   修改对应的 `primary` 或添加 `fallbacks`，无需改动业务代码。

3. **更新 akshare**：
   ```bash
   pip install akshare --upgrade
   ```

4. **官方文档**：https://akshare.akfamily.xyz/

---

## akshare 接口变更日志

| 日期 | 接口 | 变更说明 | 处理方式 |
|---|---|---|---|
| （初始版本） | 所有接口 | 基于 akshare 1.14.x | 参见 api_compat.py |

> 如遇接口变更，请在此记录，并更新 api_compat.py。

---

## Chrome MCP 补充数据（可选）

`backend/collectors/chrome_collector.py` 提供了浏览器自动化爬取框架，
当前实现为框架占位，需要配置 Chrome MCP 环境后激活：

- 东方财富资金流向
- 巨潮公告列表
- 理杏仁特有指标（需账号）

参考：https://github.com/modelcontextprotocol/servers

---

## 环境变量配置

| 变量 | 默认值 | 说明 |
|---|---|---|
| DATABASE_URL | sqlite:///./data/lixinger.db | 数据库连接串 |
| APP_HOST | 0.0.0.0 | 监听地址 |
| APP_PORT | 8000 | 监听端口 |
| APP_DEBUG | false | 开发模式 |
| CORS_ORIGINS | http://localhost:3000,http://localhost:5173 | 允许的前端源 |
| AKSHARE_REQUEST_INTERVAL | 0.8 | akshare 请求间隔（秒） |
| AKSHARE_MAX_RETRIES | 3 | 最大重试次数 |
| HISTORY_YEARS_QUOTES | 3 | 行情历史年数 |
| HISTORY_YEARS_FINANCIALS | 5 | 财务历史年数 |
| LOG_LEVEL | INFO | 日志级别 |

---

## 后端 API 文档

启动后访问 http://localhost:8000/api/docs 查看 Swagger 文档。

主要端点：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/stocks | 股票列表（搜索/分页） |
| GET | /api/stocks/{code} | 股票基本信息 |
| GET | /api/stocks/{code}/quotes | 日K线行情 |
| GET | /api/stocks/{code}/financials | 财务报表 |
| GET | /api/stocks/{code}/valuations | 估值历史 |
| GET | /api/stocks/{code}/dividends | 分红历史 |
| GET | /api/stocks/{code}/dashboard | 综合仪表盘（聚合） |
| POST | /api/screener/run | 运行筛选器 |
| GET | /api/screener/presets | 预设筛选模板 |
| GET | /api/watchlist | 自选股列表 |
| POST | /api/watchlist | 添加自选股 |
| DELETE | /api/watchlist/{code} | 删除自选股 |
| POST | /api/collect/trigger | 触发数据采集 |
| GET | /api/collect/status | 采集任务状态 |

### ★ 核心表 API（新增）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/core/stocks | 股票基础信息列表 |
| GET | /api/core/stocks/{ts_code} | 单只股票基础信息 |
| GET | /api/core/stocks/{ts_code}/daily | 日度量价与估值数据 |
| GET | /api/core/stocks/{ts_code}/finance | 季度财务核心数据 |
| GET | /api/core/stocks/{ts_code}/dashboard | 核心表综合仪表盘 |
| GET | /api/core/indicators | 列出所有已注册指标 |
| GET | /api/core/stocks/{ts_code}/indicator/{name} | 计算指定指标 |

---

## 开发说明

### 筛选器条件格式

```json
{
  "logic": "AND",
  "conditions": [
    {
      "field": "roe",
      "operator": ">=",
      "value": 15,
      "period": "latest_annual",
      "consecutive_years": 5
    },
    {
      "field": "pe_ttm",
      "operator": "between",
      "value": [5, 25]
    }
  ],
  "sort_by": "roe",
  "sort_order": "desc",
  "limit": 50
}
```

支持的 `operator`：`>`, `<`, `>=`, `<=`, `==`, `!=`, `between`, `in`, `not_in`

支持的 `period`：`latest_annual`, `latest_quarter`, `ttm`, `avg_3y`, `avg_5y`

---

## ★ 指标计算框架（Strategy Pattern）

本项目提供了一套可扩展的指标计算框架，基于策略模式 (Strategy Pattern)，
方便后续添加更复杂的量化指标。

### 架构概览

```
DataReader（数据读取接口）
    ↓
BaseIndicator（指标基类）
    ↓
IndicatorRegistry（注册表，统一发现和调用）
```

### 内置指标

| 指标名 | 说明 |
|---|---|
| pe_percentile | 历史 PE-TTM 百分位 |
| pb_percentile | 历史 PB 百分位 |
| dv_percentile | 历史股息率百分位 |

### 自定义新指标

继承 `BaseIndicator` 并用 `@IndicatorRegistry.register` 装饰即可：

```python
from analyzers.indicator_framework import BaseIndicator, IndicatorRegistry

@IndicatorRegistry.register
class MyCustomIndicator(BaseIndicator):
    name = "my_indicator"
    description = "我的自定义指标"

    def compute(self, ts_code, **kwargs):
        df = self.reader.read_daily_market(ts_code, fields=["pe_ttm", "pb"])
        # ... 计算逻辑 ...
        return {"result": 42}
```

### 调用方式

```python
# Python 代码
from analyzers.indicator_framework import IndicatorRegistry
registry = IndicatorRegistry(db_session)
result = registry.compute("pe_percentile", ts_code="000001.SZ", years=5)

# API 调用
# GET /api/core/stocks/000001.SZ/indicator/pe_percentile?years=5
```

### 未来扩展方向

- DCF 模型参数估计器
- 相对估值通道线计算
- 宏观经济指标关联计算（M1/M2 与估值的相关性）
- 技术面指标（MA 均线系统、MACD、RSI、布林带等）
- 行业横向对比指标

---

## License

MIT
