import React, { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { stocksApi } from '@/services/api'
import type { Stock } from '@/types'

const SearchBar: React.FC = () => {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Stock[]>([])
  const [loading, setLoading] = useState(false)
  const [show, setShow] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()

  useEffect(() => {
    if (!query.trim()) {
      setResults([])
      return
    }
    const timer = setTimeout(async () => {
      setLoading(true)
      try {
        const { data } = await stocksApi.list({ q: query, page_size: 8 })
        setResults(data.items)
        setShow(true)
      } finally {
        setLoading(false)
      }
    }, 300)
    return () => clearTimeout(timer)
  }, [query])

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setShow(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const handleSelect = (code: string) => {
    setQuery('')
    setShow(false)
    navigate(`/stock/${code}`)
  }

  return (
    <div ref={ref} className="relative">
      <input
        className="input w-64"
        placeholder="搜索股票代码或名称..."
        value={query}
        onChange={e => setQuery(e.target.value)}
        onFocus={() => results.length && setShow(true)}
      />
      {show && results.length > 0 && (
        <div className="absolute top-full left-0 mt-1 w-72 bg-bg-card border border-border rounded-lg shadow-xl z-50 overflow-hidden">
          {results.map(s => (
            <button
              key={s.stock_code}
              className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-bg-hover text-left transition-colors"
              onClick={() => handleSelect(s.stock_code)}
            >
              <span className="font-mono text-accent text-sm w-16 shrink-0">{s.stock_code}</span>
              <span className="text-sm text-text-primary">{s.stock_name}</span>
              <span className="ml-auto text-xs text-text-muted">{s.exchange}</span>
            </button>
          ))}
        </div>
      )}
      {loading && (
        <div className="absolute right-3 top-1/2 -translate-y-1/2">
          <div className="w-4 h-4 border-2 border-accent border-t-transparent rounded-full animate-spin" />
        </div>
      )}
    </div>
  )
}

export default SearchBar
