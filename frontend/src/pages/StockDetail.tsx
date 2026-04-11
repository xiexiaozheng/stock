import React, { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { collectApi, stocksApi } from '@/services/api'
import type { CollectStatus, DashboardData, DailyQuote, Financial, Dividend, LatestValuationSnapshot } from '@/types'
import FinancialChart from '@/components/charts/FinancialChart'
import KLineChart from '@/components/charts/KLineChart'
import MetricCard from '@/components/MetricCard'
import { useWatchlistStore } from '@/hooks/useWatchlist'

type Tab = 'valuation' | 'financial' | 'dividend' | 'kline'

const StockDetail: React.FC = () => {
  const { code = '' } = useParams()
  const navigate = useNavigate()
  const [dashboard, setDashboard] = useState<DashboardData | null>(null)
  const [quotes, setQuotes] = useState<DailyQuote[]>([])
  const [financials, setFinancials] = useState<Financial[]>([])
  const [latestValuation, setLatestValuation] = useState<LatestValuationSnapshot | null>(null)
  const [dividends, setDividends] = useState<Dividend[]>([])
  const [tab, setTab] = useState<Tab>('valuation')
  const [loading, setLoading] = useState(true)
  const [collectStatus, setCollectStatus] = useState<CollectStatus | null>(null)
  const [collectingScope, setCollectingScope] = useState<'incremental' | 'full_refresh' | null>(null)
  const [collectMessage, setCollectMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const { add, remove, isInWatchlist } = useWatchlistStore()
  const watched = isInWatchlist(code)

  const loadDashboard = async () => {
    if (!code) return
    setLoading(true)
    try {
      const [d, f, v] = await Promise.all([
        stocksApi.getDashboard(code),
        stocksApi.getFinancials(code, { years: 10 }),
        stocksApi.getLatestValuation(code).catch(() => null),
      ])
      setDashboard(d.data)
      setFinancials(f.data)
      if (v) setLatestValuation(v.data)
    } catch {
      navigate('/stocks')
    } finally {
      setLoading(false)
    }
  }

  const refreshCollectStatus = async () => {
    try {
      const { data } = await collectApi.getStatus()
      setCollectStatus(data)
      return data
    } catch {
      return null
    }
  }

  const getCollectLabel = (scope: 'incremental' | 'full_refresh') => {
    const isRunning = collectingScope === scope
      || (collectStatus?.is_running && collectStatus?.last_run_type === scope)

    if (scope === 'incremental') {
      return isRunning ? '新增更新中...' : '新增更新'
    }

    return isRunning ? '全量更新中...' : '全量更新'
  }

  useEffect(() => {
    loadDashboard().catch(() => undefined)
  }, [code])

  useEffect(() => {
    if (tab === 'kline' && !quotes.length) {
      stocksApi.getQuotes(code).then(r => setQuotes(r.data))
    }
    if (tab === 'dividend' && !dividends.length) {
      stocksApi.getDividends(code).then(r => setDividends(r.data))
    }
  }, [tab, code, quotes.length, dividends.length])

  useEffect(() => {
    refreshCollectStatus().catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!collectStatus?.is_running) {
      if (collectMessage?.type === 'success' && collectStatus?.last_run) {
        loadDashboard().catch(() => undefined)
        if (tab === 'kline') {
          stocksApi.getQuotes(code).then(r => setQuotes(r.data)).catch(() => undefined)
        }
        if (tab === 'dividend') {
          stocksApi.getDividends(code).then(r => setDividends(r.data)).catch(() => undefined)
        }
      }
      return
    }

    const timer = window.setInterval(() => {
      refreshCollectStatus().catch(() => undefined)
    }, 3000)
    return () => window.clearInterval(timer)
  }, [collectStatus?.is_running, collectStatus?.last_run, collectMessage?.type])

  const handleTriggerCollect = async (scope: 'incremental' | 'full_refresh') => {
    if (!code) return
    setCollectingScope(scope)
    setCollectMessage(null)
    try {
      const { data } = await collectApi.trigger(scope, [code])
      setCollectMessage({
        type: 'success',
        text: `${scope === 'incremental' ? '当前股票新增更新' : '当前股票全量更新'}已启动：${data.message}`,
      })
      await refreshCollectStatus()
    } catch (error: unknown) {
      const message = typeof error === 'object'
        && error !== null
        && 'response' in error
        && typeof (error as { response?: { data?: { detail?: string } } }).response?.data?.detail === 'string'
        ? (error as { response?: { data?: { detail?: string } } }).response?.data?.detail
        : '启动扫描失败'
      setCollectMessage({ type: 'error', text: message ?? '启动扫描失败' })
    } finally {
      setCollectingScope(null)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin w-8 h-8 border-2 border-accent border-t-transparent rounded-full" />
      </div>
    )
  }

  if (!dashboard) return null
  const { stock, financial, metrics } = dashboard

  const fmt = (v?: number | null, decimals = 2) =>
    v !== undefined && v !== null ? v.toFixed(decimals) : '-'
  const fmtB = (v?: number | null) =>
    v !== undefined && v !== null ? (v / 1e8).toFixed(0) + '亿' : '-'

  // 优先使用最新快照中的估值数据
  const currentPE = latestValuation?.pe_ttm ?? null
  const currentPB = latestValuation?.pb ?? null
  const currentMV = latestValuation?.total_mv ?? null
  const currentClose = latestValuation?.close ?? null
  const snapshotDate = latestValuation?.trade_date ?? null

  const TABS: Array<{ key: Tab; label: string }> = [
    { key: 'valuation', label: '最新估值' },
    { key: 'financial', label: '财务分析' },
    { key: 'dividend', label: '分红历史' },
    { key: 'kline', label: '行情K线' },
  ]

  return (
    <div className="p-6">
      {/* 顶部信息栏 */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold">{stock.stock_name}</h1>
            <span className="font-mono text-accent text-lg">{stock.stock_code}</span>
            <span className="badge bg-bg-hover text-text-secondary">{stock.exchange}</span>
            {stock.industry && (
              <span className="badge bg-accent/10 text-accent">{stock.industry}</span>
            )}
          </div>
          {stock.listing_date && (
            <p className="text-text-secondary text-sm mt-1">上市日期: {stock.listing_date}</p>
          )}
        </div>
        <div className="flex items-center gap-3">
          <button
            className="btn-secondary"
            onClick={() => handleTriggerCollect('incremental')}
            disabled={collectingScope !== null || collectStatus?.is_running}
            title="仅更新当前股票的新增数据"
          >
            {getCollectLabel('incremental')}
          </button>
          <button
            className="btn-secondary"
            onClick={() => handleTriggerCollect('full_refresh')}
            disabled={collectingScope !== null || collectStatus?.is_running}
            title="重新全量更新当前股票"
          >
            {getCollectLabel('full_refresh')}
          </button>
          <button
            className={watched ? 'btn-secondary' : 'btn-primary'}
            onClick={() => watched ? remove(code) : add(code)}
          >
            {watched ? '⭐ 已自选' : '+ 添加自选'}
          </button>
          <button className="btn-secondary" onClick={() => navigate(-1)}>← 返回</button>
        </div>
      </div>

      {collectMessage && (
        <div className={`mb-6 rounded-lg border px-4 py-3 text-sm ${
          collectMessage.type === 'success'
            ? 'border-accent/30 bg-accent/10 text-accent-light'
            : 'border-rise/30 bg-rise/10 text-rise'
        }`}>
          {collectMessage.text}
          {collectStatus?.is_running && (
            <span className="ml-2 text-text-secondary">当前进度：{collectStatus.progress}</span>
          )}
        </div>
      )}

      <div className="flex gap-6">
        {/* 主内容区 */}
        <div className="flex-1 min-w-0">
          {/* 选项卡 */}
          <div className="flex border-b border-border mb-6">
            {TABS.map(t => (
              <button
                key={t.key}
                className={`tab ${tab === t.key ? 'active' : ''}`}
                onClick={() => setTab(t.key)}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* 最新估值快照 */}
          {tab === 'valuation' && (
            <div className="space-y-4">
              {latestValuation ? (
                <>
                  <div className="card">
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="font-medium">最新估值快照</h3>
                      <span className="text-sm text-text-secondary">
                        数据日期: <span className="font-mono">{snapshotDate}</span>
                        <span className="ml-2 text-xs text-text-muted">(来源: 东方财富实时行情)</span>
                      </span>
                    </div>
                    <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                      <div className="rounded-lg bg-bg-hover p-4 text-center">
                        <div className="text-text-secondary text-sm mb-1">PE-TTM（动态）</div>
                        <div className="text-2xl font-mono font-bold text-accent">
                          {currentPE !== null ? currentPE.toFixed(1) : '-'}
                        </div>
                        {metrics.pe_percentile !== undefined && currentPE !== null && (
                          <div className="text-xs text-text-secondary mt-1">
                            历史分位 {metrics.pe_percentile?.toFixed(0)}%
                          </div>
                        )}
                      </div>
                      <div className="rounded-lg bg-bg-hover p-4 text-center">
                        <div className="text-text-secondary text-sm mb-1">市净率 PB</div>
                        <div className="text-2xl font-mono font-bold">
                          {currentPB !== null ? currentPB.toFixed(2) : '-'}
                        </div>
                      </div>
                      <div className="rounded-lg bg-bg-hover p-4 text-center">
                        <div className="text-text-secondary text-sm mb-1">总市值</div>
                        <div className="text-2xl font-mono font-bold">
                          {currentMV !== null ? fmtB(currentMV) : '-'}
                        </div>
                      </div>
                      <div className="rounded-lg bg-bg-hover p-4 text-center">
                        <div className="text-text-secondary text-sm mb-1">最新价</div>
                        <div className="text-2xl font-mono font-bold">
                          {currentClose !== null ? currentClose.toFixed(2) : '-'}
                        </div>
                      </div>
                      <div className="rounded-lg bg-bg-hover p-4 text-center">
                        <div className="text-text-secondary text-sm mb-1">换手率</div>
                        <div className="text-2xl font-mono font-bold">
                          {latestValuation.turnover_rate !== null && latestValuation.turnover_rate !== undefined
                            ? latestValuation.turnover_rate.toFixed(2) + '%'
                            : '-'}
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="card text-sm text-text-secondary">
                    <p>
                      💡 <strong>说明</strong>: 此处显示为当日实时快照估值，
                      非历史 PE/PB 走势图。历史估值序列依赖的数据接口当前不可用。
                    </p>
                  </div>
                </>
              ) : (
                <div className="card">
                  <div className="text-center text-text-muted py-12">
                    <div className="text-4xl mb-3">📊</div>
                    <div className="font-medium mb-1">暂无估值快照数据</div>
                    <div className="text-sm">
                      请触发数据采集后刷新，或等待系统自动更新（每日增量同步）。
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* 财务分析 */}
          {tab === 'financial' && (
            <div className="space-y-4">
              <div className="card">
                <h3 className="font-medium mb-4">营收 & 利润趋势</h3>
                <FinancialChart data={financials} />
              </div>
              {/* 财务数据表格 */}
              <div className="card overflow-x-auto">
                <h3 className="font-medium mb-4">历年财务数据</h3>
                <table className="data-table text-xs">
                  <thead>
                    <tr>
                      <th>报告期</th>
                      <th>营收(亿)</th>
                      <th>净利润(亿)</th>
                      <th>ROE(%)</th>
                      <th>毛利率(%)</th>
                      <th>净利率(%)</th>
                      <th>负债率(%)</th>
                      <th>经营现金流(亿)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {financials
                      .filter(f => f.report_type === 'annual')
                      .sort((a, b) => b.report_date.localeCompare(a.report_date))
                      .map(f => (
                        <tr key={f.id}>
                          <td className="font-mono">{f.report_date}</td>
                          <td className="font-mono">{f.operating_revenue ? (f.operating_revenue / 1e8).toFixed(1) : '-'}</td>
                          <td className="font-mono">{f.net_profit ? (f.net_profit / 1e8).toFixed(1) : '-'}</td>
                          <td className="font-mono">{f.roe?.toFixed(1) ?? '-'}</td>
                          <td className="font-mono">{f.gross_margin?.toFixed(1) ?? '-'}</td>
                          <td className="font-mono">{f.net_margin?.toFixed(1) ?? '-'}</td>
                          <td className="font-mono">{f.debt_ratio?.toFixed(1) ?? '-'}</td>
                          <td className="font-mono">{f.operating_cash_flow ? (f.operating_cash_flow / 1e8).toFixed(1) : '-'}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* 分红历史 */}
          {tab === 'dividend' && (
            <div className="card overflow-x-auto">
              <h3 className="font-medium mb-4">历年分红记录</h3>
              {dividends.length === 0 ? (
                <div className="text-center text-text-muted py-8">暂无分红数据</div>
              ) : (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>除权除息日</th>
                      <th>每股派息(元)</th>
                      <th>送股(每10股)</th>
                      <th>转增(每10股)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dividends.map(d => (
                      <tr key={d.id}>
                        <td className="font-mono">{d.ex_dividend_date ?? '-'}</td>
                        <td className="font-mono text-accent">{d.cash_dividend?.toFixed(4) ?? '-'}</td>
                        <td className="font-mono">{d.bonus_ratio?.toFixed(2) ?? '-'}</td>
                        <td className="font-mono">{d.capital_increase?.toFixed(2) ?? '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* K线 */}
          {tab === 'kline' && (
            <div className="card">
              <h3 className="font-medium mb-4">日K线行情</h3>
              {quotes.length === 0 ? (
                <div className="text-center text-text-muted py-8">暂无行情数据</div>
              ) : (
                <KLineChart data={quotes} height={420} />
              )}
            </div>
          )}
        </div>

        {/* 右侧指标卡片 */}
        <div className="w-52 shrink-0 space-y-3">
          <MetricCard
            label="PE-TTM"
            value={fmt(currentPE, 1)}
            highlight
            percentile={metrics.pe_percentile}
          />
          <MetricCard label="PB" value={fmt(currentPB, 2)} />
          <MetricCard label="市值" value={currentMV ? fmtB(currentMV) : '-'} />
          <MetricCard label="ROE" value={fmt(financial?.roe, 1)} unit="%" />
          <MetricCard label="毛利率" value={fmt(financial?.gross_margin, 1)} unit="%" />
          <MetricCard label="净利率" value={fmt(financial?.net_margin, 1)} unit="%" />
          <MetricCard label="资产负债率" value={fmt(financial?.debt_ratio, 1)} unit="%" />
          <MetricCard
            label="营收增长(3年复合)"
            value={metrics.revenue_growth_3y !== undefined ? fmt(metrics.revenue_growth_3y, 1) : '-'}
            unit="%"
          />
          <MetricCard
            label="净利增长(3年复合)"
            value={metrics.profit_growth_3y !== undefined ? fmt(metrics.profit_growth_3y, 1) : '-'}
            unit="%"
          />
        </div>
      </div>
    </div>
  )
}

export default StockDetail
