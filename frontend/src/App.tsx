import React from 'react'
import { BrowserRouter, Routes, Route, NavLink, Navigate } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import StockDetail from './pages/StockDetail'
import Screener from './pages/Screener'
import Watchlist from './pages/Watchlist'
import StockList from './pages/StockList'
import SearchBar from './components/SearchBar'

const NavItem: React.FC<{ to: string; label: string; icon: string }> = ({ to, label, icon }) => (
  <NavLink
    to={to}
    className={({ isActive }) =>
      `flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
        isActive ? 'bg-accent/10 text-accent' : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
      }`
    }
  >
    <span>{icon}</span>
    <span>{label}</span>
  </NavLink>
)

const App: React.FC = () => {
  return (
    <BrowserRouter>
      <div className="flex h-screen overflow-hidden bg-bg-primary">
        {/* 侧边导航 */}
        <aside className="w-52 shrink-0 flex flex-col bg-bg-secondary border-r border-border">
          <div className="p-4 border-b border-border">
            <div className="flex items-center gap-2">
              <span className="text-accent text-xl">📈</span>
              <div>
                <div className="font-bold text-text-primary text-sm">理杏仁 Local</div>
                <div className="text-xs text-text-muted">个人金融数据平台</div>
              </div>
            </div>
          </div>
          <nav className="p-3 space-y-1 flex-1">
            <NavItem to="/dashboard" label="仪表盘" icon="🏠" />
            <NavItem to="/stocks" label="股票列表" icon="📋" />
            <NavItem to="/screener" label="筛选器" icon="🔍" />
            <NavItem to="/watchlist" label="自选股" icon="⭐" />
          </nav>
          <div className="p-3 border-t border-border">
            <div className="text-xs text-text-muted text-center">
              数据来源: akshare
            </div>
          </div>
        </aside>

        {/* 主内容区 */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* 顶部搜索栏 */}
          <header className="h-14 flex items-center px-6 border-b border-border bg-bg-secondary shrink-0">
            <SearchBar />
          </header>

          {/* 页面内容 */}
          <main className="flex-1 overflow-y-auto">
            <Routes>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/stocks" element={<StockList />} />
              <Route path="/stock/:code" element={<StockDetail />} />
              <Route path="/screener" element={<Screener />} />
              <Route path="/watchlist" element={<Watchlist />} />
            </Routes>
          </main>
        </div>
      </div>
    </BrowserRouter>
  )
}

export default App
