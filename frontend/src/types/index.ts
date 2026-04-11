// TypeScript 类型定义

export interface Stock {
  id: number
  stock_code: string
  stock_name: string
  exchange: string
  listing_date?: string
  industry?: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface StockListResponse {
  total: number
  page: number
  page_size: number
  items: Stock[]
}

export interface DailyQuote {
  stock_code: string
  trade_date: string
  open?: number
  high?: number
  low?: number
  close?: number
  volume?: number
  amount?: number
  turnover_rate?: number
  amplitude?: number
}

export interface Financial {
  id: number
  stock_code: string
  report_type: string
  report_date: string
  total_revenue?: number
  operating_revenue?: number
  operating_cost?: number
  gross_profit?: number
  net_profit?: number
  net_profit_deducted?: number
  total_assets?: number
  total_liabilities?: number
  total_equity?: number
  goodwill?: number
  operating_cash_flow?: number
  investing_cash_flow?: number
  financing_cash_flow?: number
  free_cash_flow?: number
  roe?: number
  roa?: number
  gross_margin?: number
  net_margin?: number
  debt_ratio?: number
}

export interface Valuation {
  id: number
  stock_code: string
  trade_date: string
  pe_ttm?: number
  pb?: number
  ps_ttm?: number
  total_market_value?: number
  circulating_market_value?: number
  dividend_yield?: number
}

export interface Dividend {
  id: number
  stock_code: string
  ex_dividend_date?: string
  bonus_ratio?: number
  cash_dividend?: number
  capital_increase?: number
}

export interface WatchlistItem {
  id: number
  stock_code: string
  stock_name?: string
  added_at: string
  notes?: string
  sort_order: number
  // 附加行情字段
  pe_ttm?: number
  pb?: number
  dividend_yield?: number
  close?: number
  change_pct?: number
}

export interface DashboardData {
  stock: Stock
  valuation?: Valuation
  financial?: Financial
  metrics: {
    pe_percentile?: number
    pe_quantiles?: Record<string, number>
    revenue_growth_3y?: number
    profit_growth_3y?: number
  }
}

export interface ScreenerCondition {
  field: string
  operator: '>' | '<' | '>=' | '<=' | '==' | '!=' | 'between' | 'in' | 'not_in'
  value: number | number[] | string[]
  period?: 'latest_annual' | 'latest_quarter' | 'ttm' | 'avg_3y' | 'avg_5y'
  consecutive_years?: number
}

export interface ScreenerConfig {
  logic: 'AND' | 'OR'
  conditions: ScreenerCondition[]
  sort_by?: string
  sort_order?: 'asc' | 'desc'
  limit?: number
}

export interface ScreenerResult {
  stock_code: string
  stock_name: string
  exchange: string
  industry?: string
  pe_ttm?: number
  pb?: number
  roe?: number
  gross_margin?: number
  net_margin?: number
  debt_ratio?: number
  total_market_value?: number
  dividend_yield?: number
  revenue?: number
  net_profit?: number
}

export interface ScreenerPreset {
  id: string
  name: string
  description: string
  conditions: ScreenerConfig
}

export interface CollectStatus {
  is_running: boolean
  last_run?: string
  last_run_type?: string
  last_error?: string
  progress: string
  started_at?: string
}

export interface LatestValuationSnapshot {
  ts_code: string
  trade_date: string
  close?: number | null
  turnover_rate?: number | null
  pe_ttm?: number | null
  pb?: number | null
  total_mv?: number | null
  source: string
}
