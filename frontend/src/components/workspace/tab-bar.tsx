"use client"

import { useWorkspaceStore } from "@/store/workspace-store"
import { cn } from "@/lib/utils"
import { X } from "lucide-react"

export function TabBar() {
  const { centerTabs, activeCenterTab, setActiveCenterTab, closeCenterTab } =
    useWorkspaceStore()

  return (
    <div className="flex h-8 shrink-0 items-end bg-[#2B2B2B] border-b border-[#515151]">
      {centerTabs.map((tab) => {
        const isActive = tab.id === activeCenterTab
        return (
          <div
            key={tab.id}
            className={cn(
              "group relative flex h-7 items-center gap-1.5 border-r border-[#515151] px-3 text-xs cursor-pointer select-none",
              isActive
                ? "bg-[#3C3F41] text-[#A9B7C6] before:absolute before:left-0 before:top-0 before:h-[2px] before:w-full before:bg-[#4B6EAF]"
                : "bg-[#2B2B2B] text-[#6A7579] hover:bg-[#313335]"
            )}
            onClick={() => setActiveCenterTab(tab.id)}
          >
            <span className="truncate max-w-[120px]">{tab.label}</span>
            {centerTabs.length > 1 && (
              <button
                className="ml-1 rounded p-0.5 opacity-0 group-hover:opacity-100 hover:bg-[#4B6EAF] hover:text-white"
                onClick={(e) => {
                  e.stopPropagation()
                  closeCenterTab(tab.id)
                }}
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
        )
      })}
    </div>
  )
}
