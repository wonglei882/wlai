"use client"

import { cn } from "@/lib/utils"
import { X, ChevronDown } from "lucide-react"

interface ToolWindowProps {
  title: string
  children: React.ReactNode
  className?: string
  onClose?: () => void
  actions?: React.ReactNode
}

export function ToolWindow({ title, children, className, onClose, actions }: ToolWindowProps) {
  return (
    <div className={cn("flex h-full flex-col bg-[#2B2B2B]", className)}>
      {/* Title bar */}
      <div className="flex h-8 shrink-0 items-center gap-1 border-b border-[#515151] bg-[#3C3F41] px-2">
        <span className="flex-1 truncate text-xs font-medium text-[#A9B7C6]">{title}</span>
        {actions}
        {onClose && (
          <button
            onClick={onClose}
            className="rounded p-0.5 text-[#A9B7C6] hover:bg-[#4B6EAF] hover:text-white"
          >
            <X className="h-3 w-3" />
          </button>
        )}
      </div>
      {/* Content */}
      <div className="flex-1 overflow-auto">{children}</div>
    </div>
  )
}

/** 面板分割线 handle 样式 */
export function PanelDivider({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "bg-[#515151] transition-colors hover:bg-[#4B6EAF] active:bg-[#4B6EAF]",
        className
      )}
    />
  )
}

/** 折叠按钮 */
export function CollapseButton({
  collapsed,
  onClick,
  position = "right",
}: {
  collapsed: boolean
  onClick: () => void
  position?: "left" | "right" | "bottom" | "top"
}) {
  const rotation = { left: 180, right: 0, bottom: 270, top: 90 }[position]
  return (
    <button
      onClick={onClick}
      className="rounded p-0.5 text-[#A9B7C6] hover:bg-[#4B6EAF] hover:text-white"
    >
      <ChevronDown
        className="h-3 w-3"
        style={{ transform: `rotate(${rotation}deg)` }}
      />
    </button>
  )
}
