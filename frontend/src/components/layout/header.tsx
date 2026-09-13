"use client"

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { cn } from "@/lib/utils"
import { Circle } from "lucide-react"

export function Header() {
  const { data: pmStatus } = useQuery({
    queryKey: ["pm-status"],
    queryFn: () => api.getPMStatus(),
    refetchInterval: 30000,
    retry: false,
  })

  const statusColor = pmStatus?.kill_switch
    ? "text-red-400"
    : pmStatus?.pause_switch
    ? "text-yellow-400"
    : "text-green-400"

  const statusLabel = pmStatus?.kill_switch
    ? "已停止"
    : pmStatus?.pause_switch
    ? "已暂停"
    : "运行中"

  return (
    <header className="flex h-14 items-center justify-between border-b bg-background px-6">
      <div />
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 text-sm">
          <Circle className={cn("h-3 w-3 fill-current", statusColor)} />
          <span className="text-muted-foreground">PM Agent: {statusLabel}</span>
        </div>
      </div>
    </header>
  )
}
