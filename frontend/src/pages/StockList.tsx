import React, { useEffect, useState } from 'react'
import { stocksApi } from '@/services/api'
import type { StockListResponse } from '@/types'
import StockTable from '@/components/StockTable'

const StockList: React.FC = () => {
  const [data, setData] = useState<StockListResponse>({ total: 0, page: 1, page_size: 50, items: [] })
  const [query, setQuery] = useState('')
  const [exchange, setExchange] = useState('')
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)

  const load = async (q = query, ex = exchange, p = page) => {
    setLoading(true)
    try {
      const { data: res } = await stocksApi.list({ q: q || undefined, exchange: ex || undefined, page: p, page_size: 50 })
      setData(res)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const handleSearch = () => {
    setPage(1)
    load(query, exchange, 1)
  }

  const totalPages = Math.ceil(data.total / data.page_size)

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">A 股股票列表</h1>
        <span className="text-text-secondary text-sm">共 {data.total.toLocaleString()} 只</span>
      </div>

      {/* 搜索条件 */}
      <div className="card flex flex-wrap items-center gap-4">
        <input
          className="input flex-1 min-w-40"
          placeholder="搜索股票代码或名称..."
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSearch()}
        />
        <select className="input w-32" value={exchange} onChange={e => { setExchange(e.target.value); load(query, e.target.value, 1) }}>
          <option value="">全部交易所</option>
          <option value="SH">沪市(SH)</option>
          <option value="SZ">深市(SZ)</option>
          <option value="BJ">北交所(BJ)</option>
        </select>
        <button className="btn-primary" onClick={handleSearch}>搜索</button>
      </div>

      {/* 列表 */}
      <div className="card">
        <StockTable
          data={data.items}
          loading={loading}
          columns={['stock_code', 'stock_name', 'exchange', 'industry']}
        />

        {/* 分页 */}
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-2 mt-4 pt-4 border-t border-border">
            <button
              className="btn-secondary text-sm px-3 py-1"
              disabled={page <= 1}
              onClick={() => { const p = page - 1; setPage(p); load(query, exchange, p) }}
            >
              ← 上一页
            </button>
            <span className="text-sm text-text-secondary font-mono">
              {page} / {totalPages}
            </span>
            <button
              className="btn-secondary text-sm px-3 py-1"
              disabled={page >= totalPages}
              onClick={() => { const p = page + 1; setPage(p); load(query, exchange, p) }}
            >
              下一页 →
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export default StockList
