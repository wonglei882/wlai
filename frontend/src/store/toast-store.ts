import { create } from "zustand"

export interface Toast {
  id: string
  type: "success" | "error" | "info" | "warning"
  message: string
}

interface ToastState {
  toasts: Toast[]
  addToast: (type: Toast["type"], message: string) => void
  removeToast: (id: string) => void
}

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],

  addToast: (type, message) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
    set((s) => ({ toasts: [...s.toasts.slice(-4), { id, type, message }] }))
    // Auto remove after 5s
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }))
    }, 5000)
  },

  removeToast: (id) =>
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))

/** Convenience helpers */
export const toast = {
  success: (msg: string) => useToastStore.getState().addToast("success", msg),
  error: (msg: string) => useToastStore.getState().addToast("error", msg),
  info: (msg: string) => useToastStore.getState().addToast("info", msg),
  warning: (msg: string) => useToastStore.getState().addToast("warning", msg),
}
