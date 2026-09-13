"use client"

import { useToastStore } from "@/store/toast-store"
import { X, CheckCircle2, AlertCircle, Info, AlertTriangle } from "lucide-react"
import { cn } from "@/lib/utils"

const icons = {
  success: CheckCircle2,
  error: AlertCircle,
  info: Info,
  warning: AlertTriangle,
}

const colors = {
  success: "border-green-500/40 bg-green-500/10 text-green-400",
  error: "border-red-500/40 bg-red-500/10 text-red-400",
  info: "border-blue-500/40 bg-blue-500/10 text-blue-400",
  warning: "border-yellow-500/40 bg-yellow-500/10 text-yellow-400",
}

export function Toaster() {
  const { toasts, removeToast } = useToastStore()

  if (toasts.length === 0) return null

  return (
    <div className="fixed right-4 top-4 z-[100] flex flex-col gap-2 pointer-events-none">
      {toasts.map((t) => {
        const Icon = icons[t.type]
        return (
          <div
            key={t.id}
            className={cn(
              "flex items-center gap-2 rounded border px-3 py-2 text-sm shadow-lg pointer-events-auto animate-in slide-in-from-right",
              colors[t.type]
            )}
          >
            <Icon className="h-4 w-4 shrink-0" />
            <span className="flex-1 text-[#A9B7C6]">{t.message}</span>
            <button
              onClick={() => removeToast(t.id)}
              className="rounded p-0.5 text-[#6A7579] hover:text-[#A9B7C6]"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        )
      })}
    </div>
  )
}
