import React, { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { stocksApi } from '@/services/api'
import type { DashboardData, DailyQuote, Financial, Valuation, Dividend } from '@/types'
import ValuationChart from '@/components/charts/ValuationChart'
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
  const [valuations, setValuations] = useState<Valuation[]>([])
  const [dividends, setDividends] = useState<Dividend[]>([])
  const [tab, setTab] = useState<Tab>('valuation')
  const [loading, setLoading] = useState(true)
  const { add, remove, isInWatchlist } = useWatchlistStore()
  const watched = isInWatchlist(code)

  useEffect(() => {
    if (!code) return
    setLoading(true)
    Promise.all([
      stocksApi.getDashboard(code),
      stocksApi.getValuations(code),
      stocksApi.getFinancials(code, { years: 10 }),
    ]).then(([d, v, f]) => {
      setDashboard(d.data)
      setValuations(v.data)
      setFinancials(f.data)
    }).catch(() => {
      navigate('/stocks')
    }).finally(() => setLoading(false))
  }, [code, navigate])

  useEffect(() => {
    if (tab === 'kline' && !quotes.length) {
      stocksApi.getQuotes(code).then(r => setQuotes(r.data))
    }
    if (tab === 'dividend' && !dividends.length) {
      stocksApi.getDividends(code).then(r => setDividends(r.data))
    }
  }, [tab, code, quotes.length, dividends.length])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin w-8 h-8 border-2 border-accent border-t-transparent rounded-full" />
      </div>
    )
  }

  if (!dashboard) return null
  const { stock, valuation, financial, metrics } = dashboard

  const fmt = (v?: number | null, decimals = 2) =>
    v !== undefined && v !== null ? v.toFixed(decimals) : '-'
  const fmtB = (v?: number | null) =>
    v !== undefined && v !== null ? (v / 1e8).toFixed(0) + '亿' : '-'

  const TABS: Array<{ key: Tab; label: string }> = [
    { key: 'valuation', label: '估值图' },
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
            className={watched ? 'btn-secondary' : 'btn-primary'}
            onClick={() => watched ? remove(code) : add(code)}
          >
            {watched ? '⭐ 已自选' : '+ 添加自选'}
          </button>
          <button className="btn-secondary" onClick={() => navigate(-1)}>← 返回</button>
        </div>
      </div>

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

          {/* 估值图 */}
          {tab === 'valuation' && (
            <div className="space-y-4">
              <div className="card">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-medium">PE-TTM 历史走势</h3>
                  {metrics.pe_percentile !== undefined && (
                    <span className="text-sm text-text-secondary">
                      当前分位: <span className="font-mono text-accent">{metrics.pe_percentile?.toFixed(0)}%</span>
                    </span>
                  )}
                </div>
                <ValuationChart
                  data={valuations}
                  metric="pe_ttm"
                  quantiles={metrics.pe_quantiles}
                />
              </div>
              <div className="card">
                <h3 className="font-medium mb-4">PB 历史走势</h3>
                <ValuationChart data={valuations} metric="pb" />
              </div>
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
            value={fmt(valuation?.pe_ttm, 1)}
            highlight
            percentile={metrics.pe_percentile}
          />
          <MetricCard label="PB" value={fmt(valuation?.pb, 2)} />
          <MetricCard label="股息率" value={fmt(valuation?.dividend_yield, 2)} unit="%" />
          <MetricCard label="市值" value={valuation?.total_market_value ? fmtB(valuation.total_market_value) : '-'} />
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
