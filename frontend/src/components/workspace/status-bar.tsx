"use client"

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { cn } from "@/lib/utils"

export function StatusBar({ projectId }: { projectId: string }) {
  const { data: shotsData } = useQuery({
    queryKey: ["project-shots", projectId],
    queryFn: () => api.getShotsByProject(projectId),
  })

  const { data: projectData } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
  })

  const shots = (shotsData?.shots ?? []) as Record<string, unknown>[]
  const total = shots.length
  const pending = shots.filter((s) => s.status === "pending_review_image").length
  const lowScore = shots.filter((s) => {
    const score = s.last_consistency_score as number | null
    return score != null && score < 0.7
  }).length
  const completed = shots.filter((s) => s.status === "completed").length

  return (
    <div className="flex h-5 shrink-0 items-center gap-4 border-t border-[#515151] bg-[#3C3F41] px-3 text-[10px] text-[#6A7579]">
      <span>
        镜头 <span className="text-[#A9B7C6]">{total}</span>
      </span>
      <span className="text-[#515151]">|</span>
      <span>
        待审核 <span className={cn(pending > 0 && "text-yellow-400")}>{pending}</span>
      </span>
      <span className="text-[#515151]">|</span>
      <span>
        低一致性 <span className={cn(lowScore > 0 && "text-red-400")}>{lowScore}</span>
      </span>
      <span className="text-[#515151]">|</span>
      <span>
        已完成 <span className={cn(completed > 0 && "text-green-400")}>{completed}</span>
      </span>
      <span className="ml-auto">
        {projectData?.title && <span className="text-[#A9B7C6]">{projectData.title}</span>}
      </span>
    </div>
  )
}
