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
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

访问：http://localhost:5173

### 2. Docker 部署

```bash
docker-compose up -d
```

访问：http://localhost:3000

---

## 项目结构

```
.
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

## 通过手机出口为 AkShare 配置代理

如果 CloudCone 节点直接抓取国内站点容易被封，可以把 **手机 Ubuntu 的网络出口** 作为 AkShare 代理出口。当前仓库已经支持通过 `AKSHARE_PROXY_URL` 注入标准 `HTTP(S)_PROXY/ALL_PROXY` 环境变量，适合和你现有的 **V2Ray + TLS + WebSocket + Nginx + Cloudflare** 转发链路一起使用。AkShare 某个源如果在重试中被判定为疑似短时封禁，下一次重试会在“代理 / 直连”之间自动切换；同时系统仍会定期检测代理健康状态，若代理不可用，则保持直连而不会强行切换。

推荐按下面三层理解：

1. **手机 Ubuntu 侧**：启动一个本地 HTTP 代理监听端口（建议 `127.0.0.1:10809`），由手机直接访问国内站点；你现有的手机客户端/Ubuntu 侧程序负责把请求真正从手机网络发出。
2. **CloudCone 侧转发**：现有 Nginx + WebSocket + TLS 配置继续负责把 CloudCone 与手机之间的流量隧道打通；额外再准备一个 CloudCone 本地可访问的 HTTP 转发端口，把它转到手机上的 `10809`。
3. **应用侧**：让 backend 把 AkShare/requests 的出站请求都发到这个本地转发端口。

最小可用示例（Docker 部署）：

```bash
export AKSHARE_PROXY_URL=http://host.docker.internal:10809
docker-compose up -d --build
```

说明：

- `host.docker.internal` 已在 `docker-compose.yml` 中映射到宿主机网关，适合容器访问宿主机上的本地转发服务。
- 如果你的 CloudCone 转发服务监听在其他地址/端口，把 `AKSHARE_PROXY_URL` 改成实际值即可。
- `AKSHARE_PROXY_NO_PROXY` 可选，用来排除不走代理的目标，例如：

```bash
export AKSHARE_PROXY_NO_PROXY=127.0.0.1,localhost,backend
```

### CloudCone ↔ 手机 Ubuntu 落地示例

下面给一套**最容易先跑通**的方案：手机 Ubuntu 提供本地 HTTP 代理，手机再主动连回 CloudCone 暴露一个仅本机可访问的反向端口。  
如果你已经有现成的 V2Ray / Xray / Nginx / Cloudflare 转发链路，也可以把下面示例里的 `11080 -> 10809` 映射替换成你现有链路暴露出来的本地端口，应用侧配置保持不变。

#### 1）手机 Ubuntu：启动 HTTP 代理

可以用 `tinyproxy`，也可以换成你更熟悉的 `3proxy/gost/squid`。下面是 `tinyproxy` 示例：

```bash
sudo apt-get update
sudo apt-get install -y tinyproxy autossh
sudo cp /etc/tinyproxy/tinyproxy.conf /etc/tinyproxy/tinyproxy.conf.bak
sudo tee /etc/tinyproxy/tinyproxy.conf >/dev/null <<'EOF'
User tinyproxy
Group tinyproxy
Port 10809
Listen 127.0.0.1
Timeout 600
DefaultErrorFile "/usr/share/tinyproxy/default.html"
StatFile "/usr/share/tinyproxy/stats.html"
LogFile "/var/log/tinyproxy/tinyproxy.log"
LogLevel Info
PidFile "/run/tinyproxy/tinyproxy.pid"
MaxClients 100
Allow 127.0.0.1
ViaProxyName "phone-akshare-proxy"
EOF
sudo systemctl restart tinyproxy
sudo systemctl enable tinyproxy
curl -x http://127.0.0.1:10809 https://www.baidu.com | head
```

#### 2）手机 Ubuntu：把代理端口反向暴露到 CloudCone

先确保 CloudCone 机器允许 SSH 登录，然后在手机 Ubuntu 上执行：

```bash
autossh -M 0 -f -N \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -R 127.0.0.1:11080:127.0.0.1:10809 \
  <cloudcone_user>@<cloudcone_ip>
```

这条命令的含义是：

- CloudCone 本机打开 `127.0.0.1:11080`
- 实际请求通过 SSH 反向隧道转发到手机 Ubuntu 的 `127.0.0.1:10809`
- AkShare 只需要把代理地址指向 CloudCone 本地的 `11080`

如果你想常驻运行，可以在手机 Ubuntu 上创建 systemd 服务：

```ini
# /etc/systemd/system/akshare-proxy-tunnel.service
[Unit]
Description=Reverse tunnel for AkShare proxy
After=network-online.target
Wants=network-online.target

[Service]
User=<your_user>
ExecStart=/usr/bin/autossh -M 0 -N \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -R 127.0.0.1:11080:127.0.0.1:10809 \
  <cloudcone_user>@<cloudcone_ip>
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now akshare-proxy-tunnel
```

#### 3）CloudCone：确认本地代理端口已打通

在 CloudCone 上执行：

```bash
curl -x http://127.0.0.1:11080 https://www.baidu.com | head
curl -x http://127.0.0.1:11080 https://quote.eastmoney.com | head
```

如果能返回页面内容，说明 CloudCone → 手机 Ubuntu 的代理链路已经通了。

#### 4）应用侧：让 AkShare 走手机出口

如果后端直接运行在 CloudCone 宿主机上：

```bash
export AKSHARE_PROXY_URL=http://127.0.0.1:11080
export AKSHARE_PROXY_NO_PROXY=127.0.0.1,localhost
cd /path/to/stock
python scripts/check_akshare.py
```

如果后端跑在本仓库的 Docker Compose 里：

```bash
export AKSHARE_PROXY_URL=http://host.docker.internal:11080
export AKSHARE_PROXY_NO_PROXY=127.0.0.1,localhost,backend
docker-compose up -d --build
```

这里使用 `host.docker.internal`，是因为容器访问的是 CloudCone 宿主机上的 `11080`。

#### 5）和你现有 V2Ray / Nginx 配置怎么对应

- 你当前的 **Nginx + TLS + WebSocket + Cloudflare** 入口可以继续保留，不需要改动应用代码
- 关键不是协议本身，而是**最终在 CloudCone 本机上拿到一个可访问的 HTTP 代理端口**
- 只要你的现有链路最终能在 CloudCone 暴露出类似 `127.0.0.1:11080` 的端口，就把：
  - 宿主机部署：`AKSHARE_PROXY_URL=http://127.0.0.1:11080`
  - Docker 部署：`AKSHARE_PROXY_URL=http://host.docker.internal:11080`
- 如果你现有链路暴露的是 SOCKS5 端口，也可以直接写成：

```bash
export AKSHARE_PROXY_URL=socks5h://host.docker.internal:11080
```

其中 `socks5h` 表示域名解析也走远端代理，更适合规避 CloudCone 本地 DNS 暴露。

前端现在也支持：

- 个股详情页：单只股票 **增量扫描 / 全量扫描**
- 自选股页面：自选范围 **增量扫描 / 全量扫描**

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

akshare 接口更新较频繁。本项目通过 `backend/data_provider/source_config.py` 集中管理所有 AKShare 接口配置（签名、参数白名单、字段映射、fallback 顺序等），`backend/utils/api_compat.py` 作为统一调用入口。

1. **首次运行前**，建议执行健康检查：
   ```bash
   python scripts/check_akshare.py
   ```

2. **如果某接口报错**，在 `backend/data_provider/source_config.py` 的 `AKSHARE_API_CONFIGS` 中
   修改对应 `sources` 下的 `api_function`、`signature`、`supported_params` 等字段，
   无需改动业务代码。`api_compat.py` 会自动读取最新配置。

3. **更新 akshare**：
   ```bash
   pip install akshare --upgrade
   ```

4. **官方文档**：https://akshare.akfamily.xyz/

---

## akshare 接口变更日志

| 日期 | 接口 | 变更说明 | 处理方式 |
|---|---|---|---|
| （初始版本） | 所有接口 | 基于 akshare 1.14.x | 参见 source_config.py |
| 2026-04-10 | 接口配置集中化 | 所有接口定义从 api_compat.py 迁移到 source_config.py | AKSHARE_API_CONFIGS 为唯一权威配置 |

> 如遇接口变更，请在此记录，并更新 `backend/data_provider/source_config.py` 中对应的 sources 配置。

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
