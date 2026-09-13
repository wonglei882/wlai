"use client"

import { useWorkspaceStore } from "@/store/workspace-store"
import { cn } from "@/lib/utils"
import { Trash2 } from "lucide-react"

export function OutputLog() {
  const { logs, clearLogs } = useWorkspaceStore()

  return (
    <div className="flex h-full flex-col bg-[#2B2B2B]">
      {/* Toolbar */}
      <div className="flex h-6 shrink-0 items-center justify-end border-b border-[#515151] bg-[#3C3F41] px-2">
        <button
          onClick={clearLogs}
          className="rounded p-0.5 text-[#6A7579] hover:text-[#A9B7C6]"
          title="清空日志"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>

      {/* Log entries */}
      <div className="flex-1 overflow-auto font-mono text-[10px]">
        {logs.length === 0 ? (
          <div className="flex h-full items-center justify-center text-[#6A7579]">
            暂无日志
          </div>
        ) : (
          <div className="divide-y divide-[#515151]/50">
            {logs.map((log) => (
              <div key={log.id} className="flex items-center gap-2 px-2 py-0.5 hover:bg-[#3C3F41]">
                <span className="text-[#6A7579]">{log.timestamp}</span>
                <span className={cn(
                  "rounded px-1 text-[9px]",
                  log.result === "success" ? "bg-green-500/20 text-green-400" :
                  log.result === "error" ? "bg-red-500/20 text-red-400" :
                  "bg-blue-500/20 text-blue-400"
                )}>
                  {log.result === "success" ? "OK" : log.result === "error" ? "ERR" : "INFO"}
                </span>
                <span className="text-[#A9B7C6]">{log.action}</span>
                <span className="text-[#6A7579]">{log.target}</span>
                {log.detail && <span className="text-[#6A7579]">— {log.detail}</span>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
