import React, { useState, useEffect } from 'react'
import { screenerApi } from '@/services/api'
import type { ScreenerConfig, ScreenerCondition, ScreenerResult, ScreenerPreset } from '@/types'
import StockTable from '@/components/StockTable'

const FIELD_OPTIONS = [
  { value: 'roe', label: 'ROE(%)' },
  { value: 'pe_ttm', label: 'PE-TTM' },
  { value: 'pb', label: 'PB' },
  { value: 'ps_ttm', label: 'PS-TTM' },
  { value: 'gross_margin', label: '毛利率(%)' },
  { value: 'net_margin', label: '净利率(%)' },
  { value: 'debt_ratio', label: '资产负债率(%)' },
  { value: 'dividend_yield', label: '股息率(%)' },
  { value: 'total_market_value', label: '总市值(元)' },
  { value: 'free_cash_flow', label: '自由现金流(元)' },
  { value: 'revenue_growth', label: '营收增长率(%)' },
  { value: 'profit_growth', label: '净利润增长率(%)' },
  { value: 'listing_years', label: '上市年数' },
]

const OPERATOR_OPTIONS = [
  { value: '>=', label: '>=' },
  { value: '<=', label: '<=' },
  { value: '>', label: '>' },
  { value: '<', label: '<' },
  { value: '==', label: '==' },
  { value: 'between', label: 'between' },
]

const PERIOD_OPTIONS = [
  { value: 'latest_annual', label: '最近年报' },
  { value: 'latest_quarter', label: '最近季报' },
  { value: 'avg_3y', label: '3年平均' },
  { value: 'avg_5y', label: '5年平均' },
  { value: 'ttm', label: 'TTM' },
]

const emptyCondition = (): ScreenerCondition => ({
  field: 'roe',
  operator: '>=',
  value: 15,
  period: 'latest_annual',
})

const Screener: React.FC = () => {
  const [presets, setPresets] = useState<ScreenerPreset[]>([])
  const [conditions, setConditions] = useState<ScreenerCondition[]>([emptyCondition()])
  const [logic, setLogic] = useState<'AND' | 'OR'>('AND')
  const [sortBy, setSortBy] = useState('roe')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [results, setResults] = useState<ScreenerResult[]>([])
  const [total, setTotal] = useState(0)
  const [running, setRunning] = useState(false)
  const [saveAs, setSaveAs] = useState('')

  useEffect(() => {
    screenerApi.getPresets().then(r => setPresets(r.data))
  }, [])

  const loadPreset = (preset: ScreenerPreset) => {
    setConditions(preset.conditions.conditions)
    setLogic(preset.conditions.logic)
  }

  const addCondition = () => setConditions(prev => [...prev, emptyCondition()])
  const removeCondition = (i: number) => setConditions(prev => prev.filter((_, idx) => idx !== i))

  const updateCondition = (i: number, patch: Partial<ScreenerCondition>) => {
    setConditions(prev => prev.map((c, idx) => idx === i ? { ...c, ...patch } : c))
  }

  const handleRun = async () => {
    setRunning(true)
    try {
      const config: ScreenerConfig = { logic, conditions, sort_by: sortBy, sort_order: sortOrder, limit: 200 }
      const { data } = await screenerApi.run(config, saveAs || undefined)
      setResults(data.results)
      setTotal(data.total)
    } catch (err) {
      alert('筛选失败，请检查条件配置')
    } finally {
      setRunning(false)
    }
  }

  const exportCsv = () => {
    if (!results.length) return
    const headers = Object.keys(results[0])
    const rows = results.map(r => headers.map(h => ((r as unknown) as Record<string, unknown>)[h] ?? '').join(','))
    const csv = [headers.join(','), ...rows].join('\n')
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `screener_results_${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
  }

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">股票筛选器</h1>

      {/* 预设模板 */}
      <div className="card">
        <h2 className="font-semibold mb-3">预设模板</h2>
        <div className="flex flex-wrap gap-2">
          {presets.map(p => (
            <button
              key={p.id}
              className="btn-secondary text-sm"
              onClick={() => loadPreset(p)}
              title={p.description}
            >
              {p.name}
            </button>
          ))}
        </div>
      </div>

      {/* 条件构建器 */}
      <div className="card space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">筛选条件</h2>
          <div className="flex items-center gap-3">
            <span className="text-sm text-text-secondary">逻辑:</span>
            {(['AND', 'OR'] as const).map(l => (
              <button
                key={l}
                className={`px-3 py-1 rounded text-sm ${logic === l ? 'bg-accent text-bg-primary' : 'bg-bg-hover text-text-secondary'}`}
                onClick={() => setLogic(l)}
              >
                {l}
              </button>
            ))}
          </div>
        </div>

        {conditions.map((cond, i) => (
          <div key={i} className="flex items-center gap-3 bg-bg-secondary rounded-lg p-3">
            <select
              className="input text-sm flex-1"
              value={cond.field}
              onChange={e => updateCondition(i, { field: e.target.value })}
            >
              {FIELD_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <select
              className="input text-sm w-24"
              value={cond.operator}
              onChange={e => updateCondition(i, { operator: e.target.value as ScreenerCondition['operator'] })}
            >
              {OPERATOR_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            {cond.operator === 'between' ? (
              <div className="flex gap-1">
                <input
                  className="input text-sm w-20 font-mono"
                  type="number"
                  value={Array.isArray(cond.value) ? (cond.value as number[])[0] : ''}
                  onChange={e => {
                    const arr = Array.isArray(cond.value) ? [...cond.value as number[]] : [0, 0]
                    arr[0] = Number(e.target.value)
                    updateCondition(i, { value: arr })
                  }}
                />
                <span className="text-text-secondary self-center">~</span>
                <input
                  className="input text-sm w-20 font-mono"
                  type="number"
                  value={Array.isArray(cond.value) ? (cond.value as number[])[1] : ''}
                  onChange={e => {
                    const arr = Array.isArray(cond.value) ? [...cond.value as number[]] : [0, 0]
                    arr[1] = Number(e.target.value)
                    updateCondition(i, { value: arr })
                  }}
                />
              </div>
            ) : (
              <input
                className="input text-sm w-28 font-mono"
                type="number"
                value={typeof cond.value === 'number' ? cond.value : ''}
                onChange={e => updateCondition(i, { value: Number(e.target.value) })}
              />
            )}
            <select
              className="input text-sm w-28"
              value={cond.period ?? 'latest_annual'}
              onChange={e => updateCondition(i, { period: e.target.value as ScreenerCondition['period'] })}
            >
              {PERIOD_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <input
              className="input text-sm w-16 font-mono"
              type="number"
              min={1}
              max={10}
              placeholder="连续年"
              title="连续满足条件的年数（可选）"
              value={cond.consecutive_years ?? ''}
              onChange={e => updateCondition(i, { consecutive_years: e.target.value ? Number(e.target.value) : undefined })}
            />
            <button
              className="text-text-muted hover:text-rise transition-colors p-1"
              onClick={() => removeCondition(i)}
              disabled={conditions.length === 1}
            >
              ✕
            </button>
          </div>
        ))}

        <button className="btn-secondary text-sm" onClick={addCondition}>+ 添加条件</button>
      </div>

      {/* 排序和执行 */}
      <div className="card">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="text-sm text-text-secondary">排序:</span>
            <select className="input text-sm" value={sortBy} onChange={e => setSortBy(e.target.value)}>
              {FIELD_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <select className="input text-sm" value={sortOrder} onChange={e => setSortOrder(e.target.value as 'asc' | 'desc')}>
              <option value="desc">降序</option>
              <option value="asc">升序</option>
            </select>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm text-text-secondary">保存为:</span>
            <input
              className="input text-sm w-40"
              placeholder="筛选器名称（可选）"
              value={saveAs}
              onChange={e => setSaveAs(e.target.value)}
            />
          </div>
          <div className="ml-auto flex gap-3">
            {results.length > 0 && (
              <button className="btn-secondary text-sm" onClick={exportCsv}>导出 CSV</button>
            )}
            <button className="btn-primary" onClick={handleRun} disabled={running}>
              {running ? (
                <span className="flex items-center gap-2">
                  <div className="w-4 h-4 border-2 border-bg-primary border-t-transparent rounded-full animate-spin" />
                  筛选中...
                </span>
              ) : '开始筛选'}
            </button>
          </div>
        </div>
      </div>

      {/* 结果 */}
      {results.length > 0 && (
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold">筛选结果</h2>
            <span className="text-sm text-text-secondary">共 <span className="text-accent font-mono">{total}</span> 只</span>
          </div>
          <StockTable data={results} />
        </div>
      )}
    </div>
  )
}

export default Screener
