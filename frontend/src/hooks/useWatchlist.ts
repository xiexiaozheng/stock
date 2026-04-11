import { create } from 'zustand'
import type { WatchlistItem } from '@/types'
import { watchlistApi } from '@/services/api'

interface WatchlistStore {
  items: WatchlistItem[]
  loading: boolean
  fetch: () => Promise<void>
  add: (code: string, notes?: string) => Promise<void>
  remove: (code: string) => Promise<void>
  isInWatchlist: (code: string) => boolean
}

export const useWatchlistStore = create<WatchlistStore>((set, get) => ({
  items: [],
  loading: false,

  fetch: async () => {
    set({ loading: true })
    try {
      const { data } = await watchlistApi.get()
      set({ items: data })
    } finally {
      set({ loading: false })
    }
  },

  add: async (code: string, notes?: string) => {
    await watchlistApi.add({ stock_code: code, notes })
    get().fetch()
  },

  remove: async (code: string) => {
    await watchlistApi.remove(code)
    set({ items: get().items.filter(i => i.stock_code !== code) })
  },

  isInWatchlist: (code: string) => {
    return get().items.some(i => i.stock_code === code)
  },
}))
