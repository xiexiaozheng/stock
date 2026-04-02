import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useWatchlistStore } from '@/hooks/useWatchlist'
import { collectApi } from '@/services/api'
import type { CollectStatus } from '@/types'
import StockTable from '@/components/StockTable'

const Dashboard: React.FC = () => {
  const { items, loading, fetch } = useWatchlistStore()
  const [collectStatus, setCollectStatus] = useState<CollectStatus | null>(null)
  const [triggering, setTriggering] = useState(false)

  useEffect(() => {
    fetch()
  }, [fetch])

  useEffect(() => {
    const load = async () => {
      const { data } = await collectApi.getStatus()
      setCollectStatus(data)
    }
    load()
    const interval = setInterval(load, 5000)
    return () => clearInterval(interval)
  }, [])

  const handleTriggerCollect = async (scope: 'incremental' | 'full_refresh') => {
    setTriggering(true)
    try {
      await collectApi.trigger(scope)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? '触发失败'
      alert(msg)
    } finally {
      setTriggering(false)
    }
  }

  return (
    <div className="p-6 space-y-6">
      {/* 页面标题 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">仪表盘</h1>
          <p className="text-text-secondary text-sm mt-1">自选股概览 & 市场动态</p>
        </div>
        <div className="flex items-center gap-3">
          {/* 采集状态 */}
          {collectStatus && (
            <div className={`flex items-center gap-2 text-xs px-3 py-1.5 rounded-full border ${
              collectStatus.is_running
                ? 'border-accent text-accent'
                : collectStatus.last_error
                ? 'border-rise text-rise'
                : 'border-border text-text-secondary'
            }`}>
              {collectStatus.is_running && (
                <div className="w-2 h-2 bg-accent rounded-full animate-pulse" />
              )}
              {collectStatus.is_running
                ? `采集中: ${collectStatus.progress}`
                : collectStatus.last_run
                ? `上次更新: ${collectStatus.last_run.slice(0, 16).replace('T', ' ')}`
                : '尚未采集'}
            </div>
          )}
          <button
            className="btn-secondary text-sm"
            onClick={() => handleTriggerCollect('incremental')}
            disabled={triggering || collectStatus?.is_running}
          >
            增量更新
          </button>
          <button
            className="btn-primary text-sm"
            onClick={() => handleTriggerCollect('full_refresh')}
            disabled={triggering || collectStatus?.is_running}
          >
            全量刷新
          </button>
        </div>
      </div>

      {/* 快捷导航 */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { label: '股票列表', href: '/stocks', icon: '📋', desc: '全市场 A 股' },
          { label: '筛选器', href: '/screener', icon: '🔍', desc: '条件选股' },
          { label: '自选股', href: '/watchlist', icon: '⭐', desc: `${items.length} 只` },
          { label: '数据采集', href: '#', icon: '⚡', desc: '手动触发', onClick: () => handleTriggerCollect('incremental') },
        ].map(item => (
          item.href !== '#' ? (
            <Link key={item.label} to={item.href} className="card hover:border-accent/50 transition-colors group">
              <div className="text-2xl mb-2">{item.icon}</div>
              <div className="font-medium text-text-primary group-hover:text-accent transition-colors">{item.label}</div>
              <div className="text-xs text-text-secondary mt-1">{item.desc}</div>
            </Link>
          ) : (
            <button key={item.label} className="card hover:border-accent/50 transition-colors text-left" onClick={item.onClick}>
              <div className="text-2xl mb-2">{item.icon}</div>
              <div className="font-medium text-text-primary">{item.label}</div>
              <div className="text-xs text-text-secondary mt-1">{item.desc}</div>
            </button>
          )
        ))}
      </div>

      {/* 自选股列表 */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-text-primary">自选股</h2>
          <Link to="/watchlist" className="text-sm text-accent hover:text-accent-light transition-colors">
            管理 →
          </Link>
        </div>
        {items.length === 0 ? (
          <div className="text-center text-text-muted py-8">
            暂无自选股，<Link to="/stocks" className="text-accent">去添加</Link>
          </div>
        ) : (
          <StockTable data={items} showChange loading={loading} />
        )}
      </div>
    </div>
  )
}

export default Dashboard
