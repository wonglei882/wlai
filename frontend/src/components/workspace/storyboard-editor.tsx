"use client"

import { use, useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { useWorkspaceStore } from "@/store/workspace-store"
import { ShotLaneBoard } from "@/components/workspace/shot-lane-board"
import { cn } from "@/lib/utils"
import {
  Loader2, RotateCcw, Eye, Zap, Play, CheckCircle2, AlertCircle,
} from "lucide-react"

const STATUS_LABELS: Record<string, string> = {
  pending_script: "待脚本",
  pending_image: "待出图",
  pending_review_image: "待审核",
  pending_video: "待视频",
  pending_voice: "待配音",
  pending_composite: "待合成",
  completed: "已完成",
}

const STATUS_COLORS: Record<string, string> = {
  pending_script: "border-gray-500/40 bg-gray-500/10",
  pending_image: "border-blue-500/40 bg-blue-500/10",
  pending_review_image: "border-yellow-500/40 bg-yellow-500/10",
  pending_video: "border-purple-500/40 bg-purple-500/10",
  pending_voice: "border-indigo-500/40 bg-indigo-500/10",
  pending_composite: "border-orange-500/40 bg-orange-500/10",
  completed: "border-green-500/40 bg-green-500/10",
}

const STATUS_DOT: Record<string, string> = {
  pending_script: "bg-gray-400",
  pending_image: "bg-blue-400",
  pending_review_image: "bg-yellow-400",
  pending_video: "bg-purple-400",
  pending_voice: "bg-indigo-400",
  pending_composite: "bg-orange-400",
  completed: "bg-green-400",
}

const NEXT_STATUS: Record<string, string> = {
  pending_script: "pending_image",
  pending_image: "pending_review_image",
  pending_review_image: "pending_video",
  pending_video: "pending_voice",
  pending_voice: "pending_composite",
  pending_composite: "completed",
}

const NEXT_LABELS: Record<string, string> = {
  pending_script: "进入出图",
  pending_image: "提交审核",
  pending_review_image: "审核通过",
  pending_video: "开始视频",
  pending_voice: "开始配音",
  pending_composite: "开始合成",
}

export function StoryboardEditor({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const { selectShot, addLog } = useWorkspaceStore()
  const [selectedShots, setSelectedShots] = useState<Set<string>>(new Set())
  const [view, setView] = useState<"grid" | "board">("grid")

  const { data: shotsData, isLoading } = useQuery({
    queryKey: ["project-shots", projectId],
    queryFn: () => api.getShotsByProject(projectId),
  })

  const shots = (shotsData?.shots ?? []) as Record<string, unknown>[]

  // Mutations
  const compileMutation = useMutation({
    mutationFn: (shotId: string) => api.compileShotPrompt(shotId),
    onSuccess: (_, shotId) => {
      queryClient.invalidateQueries({ queryKey: ["project-shots", projectId] })
      addLog("编译提示词", `Shot ${shotId.slice(0, 6)}`, "success")
    },
    onError: (_, shotId) => {
      addLog("编译提示词", `Shot ${shotId.slice(0, 6)}`, "error")
    },
  })

  const advanceMutation = useMutation({
    mutationFn: ({ shotId, targetStatus }: { shotId: string; targetStatus: string }) =>
      api.updateShotStatus(shotId, targetStatus),
    onSuccess: (_, { shotId }) => {
      queryClient.invalidateQueries({ queryKey: ["project-shots", projectId] })
      addLog("状态流转", `Shot ${shotId.slice(0, 6)}`, "success")
    },
  })

  const batchCompile = () => {
    selectedShots.forEach((shotId) => compileMutation.mutate(shotId))
    setSelectedShots(new Set())
  }

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center bg-[#2B2B2B]">
        <Loader2 className="h-6 w-6 animate-spin text-[#6A7579]" />
      </div>
    )
  }

  if (shots.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 bg-[#2B2B2B] text-[#6A7579]">
        <p className="text-sm">暂无镜头数据</p>
        <p className="text-xs">请先在分镜工作台中生成分镜</p>
      </div>
    )
  }

  return (
    <div className="h-full overflow-auto bg-[#2B2B2B]">
      {/* 视图切换 */}
      <div className="sticky top-0 z-10 flex items-center gap-1 border-b border-[#515151] bg-[#3C3F41] px-3 py-1">
        <span className="mr-2 text-xs text-[#A9B7C6]">镜头视图</span>
        <button
          onClick={() => setView("grid")}
          className={cn(
            "rounded px-2 py-0.5 text-[10px] hover:bg-[#515151]",
            view === "grid" ? "bg-[#4B6EAF] text-white" : "text-[#A9B7C6]"
          )}
        >
          卡片
        </button>
        <button
          onClick={() => setView("board")}
          className={cn(
            "rounded px-2 py-0.5 text-[10px] hover:bg-[#515151]",
            view === "board" ? "bg-[#4B6EAF] text-white" : "text-[#A9B7C6]"
          )}
        >
          流水线
        </button>
      </div>

      {/* Batch bar */}
      {selectedShots.size > 0 && (
        <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-[#515151] bg-[#3C3F41] px-3 py-1.5">
          <span className="text-xs text-[#A9B7C6]">已选择 {selectedShots.size} 个镜头</span>
          <button
            onClick={batchCompile}
            disabled={compileMutation.isPending}
            className="flex items-center gap-1 rounded bg-[#4B6EAF] px-2 py-0.5 text-[10px] text-white hover:bg-[#5A7DBF] disabled:opacity-50"
          >
            <Zap className="h-3 w-3" /> 批量编译
          </button>
          <button
            onClick={() => setSelectedShots(new Set())}
            className="rounded px-2 py-0.5 text-[10px] text-[#6A7579] hover:bg-[#515151]"
          >
            取消
          </button>
        </div>
      )}

      {view === "grid" && (
      <div className="grid gap-2 p-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {shots.map((shot) => {
          const shotId = shot.id as string
          const num = shot.shot_number as number
          const status = shot.status as string
          const retryCount = (shot.retry_count as number) || 0
          const score = shot.last_consistency_score as number | null
          const visualDesc = shot.visual_description as string
          const correctedPrompt = shot.corrected_prompt as string | null

          return (
            <div
              key={shotId}
              className={cn(
                "group cursor-pointer rounded border p-2 transition-all hover:shadow-md",
                STATUS_COLORS[status] || "border-[#515151] bg-[#3C3F41]",
                score != null && score < 0.7 && "border-red-500/60",
                selectedShots.has(shotId) && "ring-1 ring-[#4B6EAF]"
              )}
              onClick={() => selectShot(shotId)}
            >
              {/* Header */}
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={selectedShots.has(shotId)}
                    onChange={(e) => {
                      e.stopPropagation()
                      const next = new Set(selectedShots)
                      next.has(shotId) ? next.delete(shotId) : next.add(shotId)
                      setSelectedShots(next)
                    }}
                    onClick={(e) => e.stopPropagation()}
                    className="h-3 w-3 rounded border-[#515151] bg-[#3C3F41]"
                  />
                  <span className={cn("h-2 w-2 rounded-full", STATUS_DOT[status])} style={{ backgroundColor: "currentColor" }} />
                  <span className="text-xs font-medium text-[#A9B7C6]">#{num}</span>
                </div>
                <div className="flex items-center gap-1">
                  {retryCount > 0 && (
                    <span className="flex items-center gap-0.5 rounded-full bg-orange-500/20 px-1.5 py-0.5 text-[9px] text-orange-400">
                      <RotateCcw className="h-2.5 w-2.5" /> x{retryCount}
                    </span>
                  )}
                  {score != null && (
                    <span className={cn(
                      "flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[9px]",
                      score >= 0.9 ? "bg-green-500/20 text-green-400" :
                      score >= 0.7 ? "bg-yellow-500/20 text-yellow-400" :
                      "bg-red-500/20 text-red-400"
                    )}>
                      <Eye className="h-2.5 w-2.5" />
                      {(score * 100).toFixed(0)}%
                    </span>
                  )}
                </div>
              </div>

              {/* Status */}
              <div className="mb-1">
                <span className="rounded-full border border-[#515151] bg-[#2B2B2B] px-1.5 py-0.5 text-[9px] text-[#A9B7C6]">
                  {STATUS_LABELS[status] || status}
                </span>
              </div>

              {/* Description */}
              {visualDesc && (
                <p className="mb-1 line-clamp-2 text-[10px] text-[#6A7579]">{visualDesc}</p>
              )}

              {/* Corrected prompt */}
              {correctedPrompt && (
                <div className="mb-1 rounded border border-orange-500/30 bg-orange-500/10 p-1">
                  <p className="flex items-center gap-0.5 text-[9px] text-orange-400">
                    <AlertCircle className="h-2.5 w-2.5" /> 已注入修正
                  </p>
                </div>
              )}

              {/* Actions */}
              {status !== "completed" && (
                <div className="flex gap-1 border-t border-[#515151] pt-1 mt-1">
                  <button
                    onClick={(e) => { e.stopPropagation(); compileMutation.mutate(shotId) }}
                    disabled={compileMutation.isPending}
                    className="flex flex-1 items-center justify-center gap-0.5 rounded bg-[#3C3F41] py-0.5 text-[9px] text-[#A9B7C6] hover:bg-[#4B6EAF]/40 disabled:opacity-50"
                  >
                    <Zap className="h-2.5 w-2.5" /> 编译
                  </button>
                  {NEXT_STATUS[status] && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        advanceMutation.mutate({ shotId, targetStatus: NEXT_STATUS[status] })
                      }}
                      disabled={advanceMutation.isPending}
                      className="flex flex-1 items-center justify-center gap-0.5 rounded bg-[#4B6EAF]/30 py-0.5 text-[9px] text-[#A9B7C6] hover:bg-[#4B6EAF]/50 disabled:opacity-50"
                    >
                      <Play className="h-2.5 w-2.5" /> {NEXT_LABELS[status]}
                    </button>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
      )}
      {view === "board" && <ShotLaneBoard projectId={projectId} />}
    </div>
  )
}
