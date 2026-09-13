"use client"

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { useWorkspaceStore } from "@/store/workspace-store"
import { cn } from "@/lib/utils"
import { AlertCircle, CheckCircle2, Loader2, Eye } from "lucide-react"

export function ReviewConsole({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const { selectShot, setBottomPanelTab, addLog } = useWorkspaceStore()

  const { data: shotsData, isLoading } = useQuery({
    queryKey: ["project-shots", projectId],
    queryFn: () => api.getShotsByProject(projectId),
  })

  const { data: reviewsData } = useQuery({
    queryKey: ["project-reviews", projectId],
    queryFn: () => api.getReviews(projectId),
  })

  const shots = (shotsData?.shots ?? []) as Record<string, unknown>[]
  const reviews = (reviewsData?.reviews ?? []) as Record<string, unknown>[]

  // Shots needing review
  const reviewShots = shots.filter((s) => s.status === "pending_review_image")
  const completedShots = shots.filter((s) => s.status === "completed")

  const forcePassMutation = useMutation({
    mutationFn: (shotId: string) => api.updateShotStatus(shotId, "pending_video"),
    onSuccess: (_, shotId) => {
      queryClient.invalidateQueries({ queryKey: ["project-shots", projectId] })
      addLog("强制通过", `Shot ${shotId.slice(0, 6)}`, "success")
    },
  })

  const retryMutation = useMutation({
    mutationFn: (shotId: string) => api.updateShotStatus(shotId, "pending_image"),
    onSuccess: (_, shotId) => {
      queryClient.invalidateQueries({ queryKey: ["project-shots", projectId] })
      addLog("手动重试", `Shot ${shotId.slice(0, 6)}`, "success")
    },
  })

  if (isLoading) {
    return <div className="flex h-full items-center justify-center bg-[#2B2B2B]"><Loader2 className="h-4 w-4 animate-spin text-[#6A7579]" /></div>
  }

  const allItems = [
    ...reviewShots.map((s) => ({ shot: s, type: "pending" as const })),
    ...completedShots.map((s) => ({ shot: s, type: "completed" as const })),
  ]

  return (
    <div className="h-full overflow-auto bg-[#2B2B2B]">
      {allItems.length === 0 ? (
        <div className="flex h-full items-center justify-center text-xs text-[#6A7579]">
          暂无审核项
        </div>
      ) : (
        <div className="divide-y divide-[#515151]">
          {allItems.map(({ shot, type }) => {
            const shotId = shot.id as string
            const num = shot.shot_number as number
            const score = shot.last_consistency_score as number | null
            const retryCount = (shot.retry_count as number) || 0

            return (
              <div
                key={shotId}
                className="flex items-center gap-2 px-2 py-1 hover:bg-[#4B6EAF]/20 cursor-pointer"
                onClick={() => selectShot(shotId)}
              >
                {type === "pending" ? (
                  <AlertCircle className="h-3 w-3 shrink-0 text-yellow-400" />
                ) : (
                  <CheckCircle2 className="h-3 w-3 shrink-0 text-green-400" />
                )}
                <span className="text-[11px] text-[#A9B7C6]">#{num} 镜头</span>
                {score != null && (
                  <span className={cn(
                    "flex items-center gap-0.5 text-[10px]",
                    score >= 0.9 ? "text-green-400" : score >= 0.7 ? "text-yellow-400" : "text-red-400"
                  )}>
                    <Eye className="h-2.5 w-2.5" /> {(score * 100).toFixed(0)}%
                  </span>
                )}
                {retryCount > 0 && (
                  <span className="text-[10px] text-orange-400">重试 x{retryCount}</span>
                )}
                <span className="ml-auto text-[10px] text-[#6A7579]">
                  {type === "pending" ? "待审核" : "已完成"}
                </span>
                {type === "pending" && (
                  <div className="flex gap-1">
                    <button
                      onClick={(e) => { e.stopPropagation(); retryMutation.mutate(shotId) }}
                      disabled={retryMutation.isPending}
                      className="rounded bg-[#3C3F41] px-1.5 py-0.5 text-[9px] text-[#A9B7C6] hover:bg-[#4B6EAF]/40 disabled:opacity-50"
                    >
                      重试
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); forcePassMutation.mutate(shotId) }}
                      disabled={forcePassMutation.isPending}
                      className="rounded bg-green-600/20 px-1.5 py-0.5 text-[9px] text-green-400 hover:bg-green-600/30 disabled:opacity-50"
                    >
                      通过
                    </button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
