import React from 'react'
import { useNavigate } from 'react-router-dom'
import type { ScreenerResult, WatchlistItem } from '@/types'

type Row = Partial<ScreenerResult & WatchlistItem> & {
  stock_code: string
  stock_name?: string
}

interface StockTableProps {
  data: Row[]
  columns?: string[]
  loading?: boolean
  onRowClick?: (code: string) => void
  showChange?: boolean
}

const COLUMN_DEFS: Record<string, { label: string; render: (row: Row) => React.ReactNode }> = {
  stock_code: { label: '代码', render: r => <span className="font-mono text-accent">{r.stock_code}</span> },
  stock_name: { label: '名称', render: r => <span>{r.stock_name ?? '-'}</span> },
  exchange: { label: '交易所', render: r => <span className="text-text-secondary">{(r as ScreenerResult).exchange ?? '-'}</span> },
  industry: { label: '行业', render: r => <span className="text-text-secondary text-xs">{r.industry ?? '-'}</span> },
  close: { label: '最新价', render: r => <span className="font-mono">{(r as WatchlistItem).close?.toFixed(2) ?? '-'}</span> },
  change_pct: {
    label: '涨跌幅',
    render: r => {
      const v = (r as WatchlistItem).change_pct
      if (v === undefined || v === null) return <span className="text-text-muted">-</span>
      return <span className={`font-mono ${v >= 0 ? 'text-rise' : 'text-fall'}`}>{v >= 0 ? '+' : ''}{v.toFixed(2)}%</span>
    },
  },
  pe_ttm: { label: 'PE-TTM', render: r => <span className="font-mono">{r.pe_ttm?.toFixed(1) ?? '-'}</span> },
  pb: { label: 'PB', render: r => <span className="font-mono">{r.pb?.toFixed(2) ?? '-'}</span> },
  roe: { label: 'ROE(%)', render: r => <span className="font-mono">{(r as ScreenerResult).roe?.toFixed(1) ?? '-'}</span> },
  gross_margin: { label: '毛利率(%)', render: r => <span className="font-mono">{(r as ScreenerResult).gross_margin?.toFixed(1) ?? '-'}</span> },
  net_margin: { label: '净利率(%)', render: r => <span className="font-mono">{(r as ScreenerResult).net_margin?.toFixed(1) ?? '-'}</span> },
  debt_ratio: { label: '资产负债率(%)', render: r => <span className="font-mono">{(r as ScreenerResult).debt_ratio?.toFixed(1) ?? '-'}</span> },
  dividend_yield: { label: '股息率(%)', render: r => <span className="font-mono">{r.dividend_yield?.toFixed(2) ?? '-'}</span> },
  total_market_value: {
    label: '市值(亿)',
    render: r => {
      const v = r.total_market_value
      return <span className="font-mono">{v ? (v / 1e8).toFixed(0) : '-'}</span>
    },
  },
}

const DEFAULT_SCREENER_COLS = ['stock_code', 'stock_name', 'industry', 'pe_ttm', 'pb', 'roe', 'gross_margin', 'debt_ratio', 'total_market_value']
const DEFAULT_WATCHLIST_COLS = ['stock_code', 'stock_name', 'close', 'change_pct', 'pe_ttm', 'pb', 'dividend_yield']

const StockTable: React.FC<StockTableProps> = ({
  data,
  columns,
  loading = false,
  onRowClick,
  showChange = false,
}) => {
  const navigate = useNavigate()
  const cols = columns ?? (showChange ? DEFAULT_WATCHLIST_COLS : DEFAULT_SCREENER_COLS)

  const handleClick = (code: string) => {
    if (onRowClick) {
      onRowClick(code)
    } else {
      navigate(`/stock/${code}`)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-40 text-text-secondary">
        <div className="animate-spin w-6 h-6 border-2 border-accent border-t-transparent rounded-full mr-2" />
        加载中...
      </div>
    )
  }

  if (!data.length) {
    return <div className="text-center text-text-muted py-12">暂无数据</div>
  }

  return (
    <div className="overflow-x-auto">
      <table className="data-table">
        <thead>
          <tr>
            {cols.map(col => (
              <th key={col}>{COLUMN_DEFS[col]?.label ?? col}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map(row => (
            <tr key={row.stock_code} onClick={() => handleClick(row.stock_code)}>
              {cols.map(col => (
                <td key={col}>{COLUMN_DEFS[col]?.render(row) ?? '-'}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default StockTable
