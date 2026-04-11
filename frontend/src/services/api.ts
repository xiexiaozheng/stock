import axios from 'axios'
import type {
  Stock, StockListResponse, DailyQuote, Financial, Valuation,
  Dividend, WatchlistItem, DashboardData, ScreenerConfig,
  ScreenerResult, ScreenerPreset, CollectStatus, LatestValuationSnapshot,
} from '@/types'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// ======================== 股票 ========================

export const stocksApi = {
  list: (params?: {
    q?: string
    exchange?: string
    industry?: string
    page?: number
    page_size?: number
  }) => api.get<StockListResponse>('/stocks', { params }),

  get: (code: string) => api.get<Stock>(`/stocks/${code}`),

  getQuotes: (code: string, params?: {
    start_date?: string
    end_date?: string
    period?: string
  }) => api.get<DailyQuote[]>(`/stocks/${code}/quotes`, { params }),

  getFinancials: (code: string, params?: {
    report_type?: string
    years?: number
  }) => api.get<Financial[]>(`/stocks/${code}/financials`, { params }),

  getValuations: (code: string, params?: {
    start_date?: string
    end_date?: string
  }) => api.get<Valuation[]>(`/stocks/${code}/valuations`, { params }),

  getDividends: (code: string) => api.get<Dividend[]>(`/stocks/${code}/dividends`),

  getDashboard: (code: string) => api.get<DashboardData>(`/stocks/${code}/dashboard`),

  getLatestValuation: (code: string) =>
    api.get<LatestValuationSnapshot>(`/stocks/${code}/latest-valuation`),

  getXueqiu: (code: string) => api.get(`/stocks/${code}/xueqiu`),
}

// ======================== 筛选器 ========================

export const screenerApi = {
  run: (conditions: ScreenerConfig, saveAs?: string) =>
    api.post<{ total: number; results: ScreenerResult[] }>('/screener/run', {
      conditions,
      save_as: saveAs,
    }),

  getPresets: () => api.get<ScreenerPreset[]>('/screener/presets'),

  getSaved: () => api.get('/screener/saved'),

  deleteSaved: (id: number) => api.delete(`/screener/saved/${id}`),
}

// ======================== 自选股 ========================

export const watchlistApi = {
  get: () => api.get<WatchlistItem[]>('/watchlist'),

  add: (data: { stock_code: string; notes?: string; sort_order?: number }) =>
    api.post<WatchlistItem>('/watchlist', data),

  remove: (code: string) => api.delete(`/watchlist/${code}`),

  updateSort: (code: string, sort_order: number) =>
    api.put(`/watchlist/${code}/sort`, null, { params: { sort_order } }),
}

// ======================== 数据采集 ========================

export const collectApi = {
  trigger: (scope: 'incremental' | 'full_refresh', stock_codes?: string[]) =>
    api.post('/collect/trigger', { scope, stock_codes }),

  getStatus: () => api.get<CollectStatus>('/collect/status'),
}

// ======================== 健康检查 ========================

export const healthApi = {
  check: () => api.get('/health'),
}
