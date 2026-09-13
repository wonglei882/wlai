import { create } from "zustand"
import { api } from "@/lib/api-client"
import type { User } from "@/types"

interface AuthState {
  user: User | null
  token: string | null
  isLoading: boolean
  isAuthenticated: boolean
  login: (username: string, password: string) => Promise<void>
  register: (username: string, password: string, displayName?: string) => Promise<void>
  logout: () => void
  checkAuth: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: typeof window !== "undefined" ? localStorage.getItem("wlai_token") : null,
  isLoading: true,
  isAuthenticated: false,

  login: async (username, password) => {
    const res = await api.login(username, password)
    localStorage.setItem("wlai_token", res.access_token)
    set({ token: res.access_token })
    // 获取用户信息
    const user = await api.me()
    set({
      user: { ...user, role: "user" },
      isAuthenticated: true,
    })
  },

  register: async (username, password, displayName) => {
    const res = await api.register(username, password, displayName)
    localStorage.setItem("wlai_token", res.access_token)
    set({ token: res.access_token })
    const user = await api.me()
    set({
      user: { ...user, role: "user" },
      isAuthenticated: true,
    })
  },

  logout: () => {
    localStorage.removeItem("wlai_token")
    set({ user: null, token: null, isAuthenticated: false })
  },

  checkAuth: async () => {
    try {
      const token = localStorage.getItem("wlai_token")
      if (!token) {
        set({ isLoading: false, isAuthenticated: false })
        return
      }
      const user = await api.me()
      set({
        user: { ...user, role: "user" },
        token,
        isAuthenticated: true,
        isLoading: false,
      })
    } catch {
      localStorage.removeItem("wlai_token")
      set({ isLoading: false, isAuthenticated: false })
    }
  },
}))
