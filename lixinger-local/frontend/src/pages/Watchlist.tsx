import React, { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useWatchlistStore } from '@/hooks/useWatchlist'
import StockTable from '@/components/StockTable'
import SearchBar from '@/components/SearchBar'

const Watchlist: React.FC = () => {
  const { items, loading, fetch, remove } = useWatchlistStore()
  const navigate = useNavigate()

  useEffect(() => {
    fetch()
  }, [fetch])

  const exportCsv = () => {
    if (!items.length) return
    const headers = ['stock_code', 'stock_name', 'pe_ttm', 'pb', 'dividend_yield', 'close', 'change_pct', 'added_at', 'notes']
    const rows = items.map(r => headers.map(h => ((r as unknown) as Record<string, unknown>)[h] ?? '').join(','))
    const csv = [headers.join(','), ...rows].join('\n')
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `watchlist_${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">自选股</h1>
          <p className="text-text-secondary text-sm mt-1">已添加 {items.length} 只股票</p>
        </div>
        <div className="flex items-center gap-3">
          <SearchBar />
          {items.length > 0 && (
            <button className="btn-secondary text-sm" onClick={exportCsv}>导出 CSV</button>
          )}
        </div>
      </div>

      <div className="card">
        {items.length === 0 ? (
          <div className="text-center text-text-muted py-16">
            <div className="text-4xl mb-4">⭐</div>
            <p className="text-lg mb-2">自选股列表为空</p>
            <p className="text-sm">在股票详情页点击"添加自选"，或通过上方搜索框找到股票</p>
          </div>
        ) : (
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold">自选股列表</h2>
              <span className="text-xs text-text-muted">点击行跳转到详情页</span>
            </div>
            <StockTable
              data={items}
              showChange
              loading={loading}
              columns={['stock_code', 'stock_name', 'close', 'change_pct', 'pe_ttm', 'pb', 'dividend_yield', 'total_market_value']}
              onRowClick={code => navigate(`/stock/${code}`)}
            />
            {/* 删除操作 */}
            <div className="mt-4 border-t border-border pt-4">
              <p className="text-xs text-text-muted mb-2">删除自选股:</p>
              <div className="flex flex-wrap gap-2">
                {items.map(item => (
                  <button
                    key={item.stock_code}
                    className="flex items-center gap-1 text-xs px-2 py-1 bg-bg-hover rounded hover:bg-rise/20 hover:text-rise transition-colors"
                    onClick={() => remove(item.stock_code)}
                  >
                    <span className="font-mono">{item.stock_code}</span>
                    <span className="text-text-muted">{item.stock_name}</span>
                    <span>✕</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default Watchlist
