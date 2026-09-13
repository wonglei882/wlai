import { create } from "zustand"
import { api } from "@/lib/api-client"
import type { User } from "@/types"

const TOKEN_KEY = "wlai_token"

interface AuthState {
  user: User | null
  token: string | null
  mustChangePassword: boolean
  isLoading: boolean
  isAuthenticated: boolean
  login: (username: string, password: string) => Promise<boolean>
  register: (username: string, password: string, displayName?: string) => Promise<void>
  changePassword: (oldPassword: string, newPassword: string) => Promise<void>
  logout: () => void
  checkAuth: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: typeof window !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null,
  mustChangePassword: false,
  isLoading: true,
  isAuthenticated: false,

  login: async (username, password) => {
    const res = await api.login(username, password)
    localStorage.setItem(TOKEN_KEY, res.access_token)
    const user = await api.me()
    set({
      user: { ...user, role: user.role || "user" },
      token: res.access_token,
      mustChangePassword: !!res.must_change_password,
      isAuthenticated: true,
    })
    return !!res.must_change_password
  },

  register: async (username, password, displayName) => {
    const res = await api.register(username, password, displayName)
    localStorage.setItem(TOKEN_KEY, res.access_token)
    const user = await api.me()
    set({
      user: { ...user, role: user.role || "user" },
      token: res.access_token,
      mustChangePassword: false,
      isAuthenticated: true,
    })
  },

  changePassword: async (oldPassword, newPassword) => {
    const res = await api.changePassword(oldPassword, newPassword)
    localStorage.setItem(TOKEN_KEY, res.access_token)
    set({ token: res.access_token, mustChangePassword: false })
  },

  logout: () => {
    localStorage.removeItem(TOKEN_KEY)
    set({ user: null, token: null, mustChangePassword: false, isAuthenticated: false })
  },

  checkAuth: async () => {
    try {
      const token = localStorage.getItem(TOKEN_KEY)
      if (!token) {
        set({ isLoading: false, isAuthenticated: false })
        return
      }
      const user = await api.me()
      set({
        user: { ...user, role: user.role || "user" },
        token,
        mustChangePassword: !!user.must_change_password,
        isAuthenticated: true,
        isLoading: false,
      })
    } catch {
      localStorage.removeItem(TOKEN_KEY)
      set({ isLoading: false, isAuthenticated: false })
    }
  },
}))
