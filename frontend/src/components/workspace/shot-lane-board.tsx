"use client"

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { useWorkspaceStore } from "@/store/workspace-store"
import { cn } from "@/lib/utils"
import { Zap, Play, Eye, RotateCcw } from "lucide-react"

const STATUS_ORDER = [
  "pending_script",
  "pending_image",
  "pending_review_image",
  "pending_video",
  "pending_voice",
  "pending_composite",
  "completed",
]

const STATUS_LABELS: Record<string, string> = {
  pending_script: "待脚本",
  pending_image: "待出图",
  pending_review_image: "待审核",
  pending_video: "待视频",
  pending_voice: "待配音",
  pending_composite: "待合成",
  completed: "已完成",
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

const LANE_BORDER: Record<string, string> = {
  pending_script: "border-l-gray-500",
  pending_image: "border-l-blue-500",
  pending_review_image: "border-l-yellow-500",
  pending_video: "border-l-purple-500",
  pending_voice: "border-l-indigo-500",
  pending_composite: "border-l-orange-500",
  completed: "border-l-green-500",
}

export function ShotLaneBoard({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const { selectShot, addLog } = useWorkspaceStore()

  const { data: shotsData } = useQuery({
    queryKey: ["project-shots", projectId],
    queryFn: () => api.getShotsByProject(projectId),
  })
  const shots = (shotsData?.shots ?? []) as Record<string, unknown>[]

  const advanceMutation = useMutation({
    mutationFn: ({ shotId, targetStatus }: { shotId: string; targetStatus: string }) =>
      api.updateShotStatus(shotId, targetStatus),
    onSuccess: (_, { shotId }) => {
      queryClient.invalidateQueries({ queryKey: ["project-shots", projectId] })
      addLog("状态流转", `Shot ${shotId.slice(0, 6)}`, "success")
    },
    onError: (_, { shotId }) => {
      addLog("状态流转", `Shot ${shotId.slice(0, 6)}`, "error")
    },
  })

  const compileMutation = useMutation({
    mutationFn: (shotId: string) => api.compileShotPrompt(shotId),
    onSuccess: (_, shotId) => {
      queryClient.invalidateQueries({ queryKey: ["project-shots", projectId] })
      addLog("编译提示词", `Shot ${shotId.slice(0, 6)}`, "success")
    },
  })

  const groups = STATUS_ORDER.map((status) => ({
    status,
    label: STATUS_LABELS[status] || status,
    shots: shots.filter((s) => (s.status as string) === status),
  }))

  return (
    <div className="flex h-full gap-2 overflow-x-auto p-3">
      {groups.map((group) => (
        <div
          key={group.status}
          className={cn(
            "flex min-w-[180px] flex-1 flex-col rounded border border-[#515151] bg-[#313335]",
            LANE_BORDER[group.status] || "border-l-gray-500"
          )}
        >
          <div className="flex items-center justify-between border-b border-[#515151] px-2 py-1.5">
            <span className="text-[11px] font-medium text-[#A9B7C6]">{group.label}</span>
            <span className="rounded-full bg-[#3C3F41] px-1.5 text-[9px] text-[#6A7579]">
              {group.shots.length}
            </span>
          </div>
          <div className="flex flex-1 flex-col gap-1.5 p-1.5">
            {group.shots.map((shot) => {
              const shotId = shot.id as string
              const num = shot.shot_number as number
              const score = shot.last_consistency_score as number | null
              const retryCount = (shot.retry_count as number) || 0
              const visualDesc = shot.visual_description as string
              return (
                <div
                  key={shotId}
                  className="cursor-pointer rounded border border-[#515151] bg-[#2B2B2B] p-1.5 hover:border-[#4B6EAF]"
                  onClick={() => selectShot(shotId)}
                >
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-[10px] font-medium text-[#A9B7C6]">#{num}</span>
                    <span className="flex items-center gap-1">
                      {retryCount > 0 && (
                        <span className="flex items-center gap-0.5 text-[8px] text-orange-400">
                          <RotateCcw className="h-2.5 w-2.5" /> x{retryCount}
                        </span>
                      )}
                      {score != null && (
                        <span
                          className={cn(
                            "flex items-center gap-0.5 text-[8px]",
                            score >= 0.9 ? "text-green-400" : score >= 0.7 ? "text-yellow-400" : "text-red-400"
                          )}
                        >
                          <Eye className="h-2.5 w-2.5" />
                          {(score * 100).toFixed(0)}%
                        </span>
                      )}
                    </span>
                  </div>
                  {visualDesc && (
                    <p className="mb-1 line-clamp-2 text-[9px] text-[#6A7579]">{visualDesc}</p>
                  )}
                  {group.status !== "completed" && (
                    <div className="mt-1 flex gap-1 border-t border-[#515151] pt-1">
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          compileMutation.mutate(shotId)
                        }}
                        className="flex flex-1 items-center justify-center gap-0.5 rounded bg-[#3C3F41] py-0.5 text-[8px] text-[#A9B7C6] hover:bg-[#4B6EAF]/40"
                      >
                        <Zap className="h-2.5 w-2.5" /> 编译
                      </button>
                      {NEXT_STATUS[group.status] && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            advanceMutation.mutate({
                              shotId,
                              targetStatus: NEXT_STATUS[group.status],
                            })
                          }}
                          disabled={advanceMutation.isPending}
                          className="flex flex-1 items-center justify-center gap-0.5 rounded bg-[#4B6EAF]/30 py-0.5 text-[8px] text-[#A9B7C6] hover:bg-[#4B6EAF]/50 disabled:opacity-50"
                        >
                          <Play className="h-2.5 w-2.5" /> {NEXT_LABELS[group.status]}
                        </button>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
            {group.shots.length === 0 && (
              <p className="py-4 text-center text-[9px] text-[#515151]">无</p>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
