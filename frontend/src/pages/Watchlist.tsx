import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useWatchlistStore } from '@/hooks/useWatchlist'
import { collectApi } from '@/services/api'
import StockTable from '@/components/StockTable'
import SearchBar from '@/components/SearchBar'
import type { CollectStatus } from '@/types'

const Watchlist: React.FC = () => {
  const { items, loading, fetch, remove } = useWatchlistStore()
  const navigate = useNavigate()
  const [collectStatus, setCollectStatus] = useState<CollectStatus | null>(null)
  const [collectingScope, setCollectingScope] = useState<'incremental' | 'full_refresh' | null>(null)
  const [collectMessage, setCollectMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const refreshCollectStatus = async () => {
    try {
      const { data } = await collectApi.getStatus()
      setCollectStatus(data)
      return data
    } catch {
      return null
    }
  }

  const getCollectLabel = (scope: 'incremental' | 'full_refresh') =>
    collectingScope === scope || (collectStatus?.is_running && collectStatus?.last_run_type === scope)
      ? scope === 'incremental' ? '自选新增更新中...' : '自选全量更新中...'
      : scope === 'incremental' ? '自选新增更新' : '自选全量更新'

  useEffect(() => {
    fetch()
  }, [fetch])

  useEffect(() => {
    refreshCollectStatus().catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!collectStatus?.is_running) {
      if (collectMessage?.type === 'success' && collectStatus?.last_run) {
        fetch().catch(() => undefined)
      }
      return
    }

    const timer = window.setInterval(() => {
      refreshCollectStatus().catch(() => undefined)
    }, 3000)
    return () => window.clearInterval(timer)
  }, [collectStatus?.is_running, collectStatus?.last_run, collectMessage?.type, fetch])

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

  const handleTriggerCollect = async (scope: 'incremental' | 'full_refresh') => {
    if (!items.length) return
    setCollectingScope(scope)
    setCollectMessage(null)
    try {
      const { data } = await collectApi.trigger(scope, items.map(item => item.stock_code))
      setCollectMessage({
        type: 'success',
        text: `${scope === 'incremental' ? '自选股新增更新' : '自选股全量更新'}已启动：${data.message}`,
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

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">自选股</h1>
          <p className="text-text-secondary text-sm mt-1">已添加 {items.length} 只股票</p>
        </div>
        <div className="flex items-center gap-3 flex-wrap justify-end">
          <SearchBar />
          <button
            className="btn-secondary text-sm"
            onClick={() => handleTriggerCollect('incremental')}
            disabled={!items.length || collectingScope !== null || collectStatus?.is_running}
            title={items.length ? '更新全部自选股的新增数据' : '请先添加自选股'}
          >
            {getCollectLabel('incremental')}
          </button>
          <button
            className="btn-secondary text-sm"
            onClick={() => handleTriggerCollect('full_refresh')}
            disabled={!items.length || collectingScope !== null || collectStatus?.is_running}
            title={items.length ? '重新全量更新全部自选股' : '请先添加自选股'}
          >
            {getCollectLabel('full_refresh')}
          </button>
          {items.length > 0 && (
            <button className="btn-secondary text-sm" onClick={exportCsv}>导出 CSV</button>
          )}
        </div>
      </div>

      {collectMessage && (
        <div className={`rounded-lg border px-4 py-3 text-sm ${
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
