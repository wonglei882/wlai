"use client"

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { cn } from "@/lib/utils"
import { Loader2, ExternalLink, Film, Clapperboard } from "lucide-react"
import Link from "next/link"

const STATUS_COLORS: Record<string, string> = {
  pending_script: "text-gray-400",
  pending_image: "text-blue-400",
  pending_review_image: "text-yellow-400",
  pending_video: "text-purple-400",
  pending_voice: "text-indigo-400",
  pending_composite: "text-orange-400",
  completed: "text-green-400",
}

const STATUS_LABELS: Record<string, string> = {
  pending_script: "待脚本",
  pending_image: "待出图",
  pending_review_image: "待审核",
  pending_video: "待视频",
  pending_voice: "待配音",
  pending_composite: "待合成",
  completed: "已完成",
}

export function StoryboardPreview({
  projectId,
  storyboardId,
  onBackToEditor,
}: {
  projectId: string
  storyboardId: string | null
  onBackToEditor: () => void
}) {
  const { data: shotsData, isLoading } = useQuery({
    queryKey: ["storyboard-shots", storyboardId],
    queryFn: () => api.getShotsByStoryboard(storyboardId!),
    enabled: !!storyboardId,
  })

  const shots = (shotsData?.shots ?? []) as Record<string, unknown>[]

  if (!storyboardId) {
    return (
      <div className="flex h-full items-center justify-center bg-[#2B2B2B] text-[#6A7579] text-sm">
        <div className="text-center">
          <Film className="h-8 w-8 mx-auto mb-2 opacity-30" />
          <p>选择章节并点击「转分镜」</p>
          <p className="text-[10px] mt-1">将自动从小说文本生成分镜表</p>
        </div>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center bg-[#2B2B2B]">
        <Loader2 className="h-5 w-5 animate-spin text-[#6A7579]" />
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col bg-[#2B2B2B]">
      {/* Header */}
      <div className="flex h-8 shrink-0 items-center gap-2 border-b border-[#515151] bg-[#3C3F41] px-3">
        <Clapperboard className="h-3.5 w-3.5 text-green-400" />
        <span className="text-[12px] font-medium text-[#A9B7C6]">分镜预览</span>
        <span className="text-[10px] text-[#6A7579]">{shots.length} 个镜头</span>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={onBackToEditor}
            className="rounded px-2 py-0.5 text-[11px] text-[#6A7579] hover:text-[#A9B7C6] hover:bg-[#4B6EAF]/30"
          >
            返回编辑
          </button>
          <Link href={`/projects/${projectId}/comic/workspace`}>
            <button className="flex items-center gap-1 rounded bg-[#4B6EAF] px-2 py-0.5 text-[11px] text-white hover:bg-[#4B6EAF]/80">
              <ExternalLink className="h-3 w-3" />
              打开漫剧工作台
            </button>
          </Link>
        </div>
      </div>

      {/* Shot Grid */}
      <div className="flex-1 overflow-auto p-3">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {shots.map((shot, idx) => {
            const status = shot.status as string
            return (
              <div
                key={(shot.id as string) || idx}
                className="rounded border border-[#515151] bg-[#3C3F41] p-3 space-y-2"
              >
                {/* Shot header */}
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-medium text-[#A9B7C6]">
                    #{shot.shot_number as number}
                  </span>
                  <span className={cn("text-[10px]", STATUS_COLORS[status] || "text-gray-400")}>
                    {STATUS_LABELS[status] || status}
                  </span>
                </div>

                {/* Scene type */}
                {!!shot.scene_type && (
                  <div className="rounded bg-[#2B2B2B] px-2 py-1 text-[10px] text-[#6A7579]">
                    {String(shot.scene_type)}
                  </div>
                )}

                {/* Visual description */}
                {!!shot.visual_description && (
                  <p className="text-[11px] text-[#A9B7C6] line-clamp-3">
                    {String(shot.visual_description)}
                  </p>
                )}

                {/* Dialogue */}
                {!!shot.dialogue && (
                  <div className="rounded border-l-2 border-[#4B6EAF] bg-[#2B2B2B] px-2 py-1 text-[10px] text-[#A9B7C6] italic">
                    {String(shot.dialogue)}
                  </div>
                )}

                {/* Camera movement */}
                {!!shot.camera_movement && (
                  <div className="text-[10px] text-[#6A7579]">
                    镜头: {String(shot.camera_movement)}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
