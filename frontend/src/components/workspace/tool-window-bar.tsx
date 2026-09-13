"use client"

import { useWorkspaceStore, type LeftPanelType } from "@/store/workspace-store"
import { cn } from "@/lib/utils"
import { FolderTree, BookOpen } from "lucide-react"

const tools: { id: LeftPanelType; label: string; icon: typeof FolderTree }[] = [
  { id: "explorer", label: "资源管理器", icon: FolderTree },
  { id: "bible", label: "设定圣经", icon: BookOpen },
]

export function ToolWindowBar() {
  const { leftPanel, toggleLeftPanel } = useWorkspaceStore()

  return (
    <div className="flex w-10 shrink-0 flex-col items-center bg-[#3C3F41] border-r border-[#515151] py-1 gap-0.5">
      {tools.map((tool) => {
        const isActive = leftPanel === tool.id
        return (
          <button
            key={tool.id}
            title={tool.label}
            className={cn(
              "flex h-9 w-9 items-center justify-center rounded transition-colors",
              isActive
                ? "bg-[#4B6EAF] text-white"
                : "text-[#A9B7C6] hover:bg-[#4B6EAF]/40"
            )}
            onClick={() => toggleLeftPanel(tool.id)}
          >
            <tool.icon className="h-4 w-4" />
          </button>
        )
      })}
    </div>
  )
}
