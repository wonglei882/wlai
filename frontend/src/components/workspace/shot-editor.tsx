"use client"

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { useWorkspaceStore } from "@/store/workspace-store"
import { cn } from "@/lib/utils"
import {
  Loader2, Zap, Play, RotateCcw, CheckCircle2, Eye, AlertCircle,
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

export function ShotEditor({ projectId, shotId }: { projectId: string; shotId: string }) {
  const queryClient = useQueryClient()
  const { addLog } = useWorkspaceStore()

  const { data: shotsData, isLoading } = useQuery({
    queryKey: ["project-shots", projectId],
    queryFn: () => api.getShotsByProject(projectId),
  })

  const shots = (shotsData?.shots ?? []) as Record<string, unknown>[]
  const shot = shots.find((s) => s.id === shotId)

  const compileMutation = useMutation({
    mutationFn: () => api.compileShotPrompt(shotId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-shots", projectId] })
      addLog("编译提示词", `Shot ${shotId.slice(0, 6)}`, "success")
    },
    onError: () => {
      addLog("编译提示词", `Shot ${shotId.slice(0, 6)}`, "error")
    },
  })

  const advanceMutation = useMutation({
    mutationFn: (targetStatus: string) => api.updateShotStatus(shotId, targetStatus),
    onSuccess: (_, target) => {
      queryClient.invalidateQueries({ queryKey: ["project-shots", projectId] })
      addLog("状态流转", `Shot ${shotId.slice(0, 6)} → ${STATUS_LABELS[target]}`, "success")
    },
  })

  const retryMutation = useMutation({
    mutationFn: () => api.updateShotStatus(shotId, "pending_image"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-shots", projectId] })
      addLog("手动重试", `Shot ${shotId.slice(0, 6)}`, "success")
    },
  })

  const forcePassMutation = useMutation({
    mutationFn: () => api.updateShotStatus(shotId, "pending_video"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-shots", projectId] })
      addLog("强制通过", `Shot ${shotId.slice(0, 6)}`, "success")
    },
  })

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center bg-[#2B2B2B]">
        <Loader2 className="h-6 w-6 animate-spin text-[#6A7579]" />
      </div>
    )
  }

  if (!shot) {
    return (
      <div className="flex h-full items-center justify-center bg-[#2B2B2B] text-[#6A7579]">
        镜头未找到
      </div>
    )
  }

  const status = shot.status as string
  const num = shot.shot_number as number
  const visualDesc = shot.visual_description as string
  const compiledPrompt = shot.compiled_prompt as string | null
  const correctedPrompt = shot.corrected_prompt as string | null
  const score = shot.last_consistency_score as number | null
  const retryCount = (shot.retry_count as number) || 0
  const seed = shot.seed as number | null
  const cameraMovement = shot.camera_movement as string | null
  const duration = shot.duration as number | null
  const dialogue = shot.dialogue as string | null
  const characterAction = shot.character_action as string | null
  const sceneType = shot.scene_type as string | null

  return (
    <div className="h-full overflow-auto bg-[#2B2B2B] p-4">
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-bold text-[#A9B7C6]">镜头 #{num}</h2>
          <span className={cn(
            "rounded-full border px-2 py-0.5 text-xs",
            status === "completed" ? "border-green-500/40 text-green-400" :
            status === "pending_review_image" ? "border-yellow-500/40 text-yellow-400" :
            "border-[#515151] text-[#A9B7C6]"
          )}>
            {STATUS_LABELS[status] || status}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {score != null && (
            <span className={cn(
              "flex items-center gap-1 rounded-full px-2 py-0.5 text-xs",
              score >= 0.9 ? "bg-green-500/20 text-green-400" :
              score >= 0.7 ? "bg-yellow-500/20 text-yellow-400" :
              "bg-red-500/20 text-red-400"
            )}>
              <Eye className="h-3 w-3" /> {(score * 100).toFixed(0)}%
            </span>
          )}
          {retryCount > 0 && (
            <span className="flex items-center gap-1 rounded-full bg-orange-500/20 px-2 py-0.5 text-xs text-orange-400">
              <RotateCcw className="h-3 w-3" /> 重试 x{retryCount}
            </span>
          )}
        </div>
      </div>

      {/* Main content grid */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Left: Visual preview placeholder */}
        <div className="space-y-3">
          <div className="flex h-48 items-center justify-center rounded border border-[#515151] bg-[#3C3F41]">
            <div className="text-center text-[#6A7579]">
              <Play className="mx-auto mb-1 h-8 w-8 opacity-30" />
              <p className="text-xs">预览区域</p>
            </div>
          </div>

          {/* Visual description */}
          <InfoBlock label="画面描述">
            {visualDesc || "无"}
          </InfoBlock>

          {dialogue && (
            <InfoBlock label="台词">
              &ldquo;{dialogue}&rdquo;
            </InfoBlock>
          )}

          {characterAction && (
            <InfoBlock label="角色动作">
              {characterAction}
            </InfoBlock>
          )}
        </div>

        {/* Right: Prompt & metadata */}
        <div className="space-y-3">
          {/* Compiled prompt */}
          <InfoBlock label="编译提示词">
            {compiledPrompt ? (
              <pre className="whitespace-pre-wrap font-mono text-xs text-[#A9B7C6]">{compiledPrompt}</pre>
            ) : (
              <span className="text-[#6A7579]">未编译</span>
            )}
          </InfoBlock>

          {/* Corrected prompt */}
          {correctedPrompt && (
            <div className="rounded border border-orange-500/30 bg-orange-500/10 p-2">
              <p className="mb-1 flex items-center gap-1 text-xs text-orange-400">
                <AlertCircle className="h-3 w-3" /> 修正注入提示词
              </p>
              <p className="text-xs text-[#A9B7C6]">{correctedPrompt}</p>
            </div>
          )}

          {/* Metadata */}
          <div className="grid grid-cols-2 gap-2">
            {sceneType && <MetaItem label="景别" value={sceneType} />}
            {cameraMovement && <MetaItem label="镜头运动" value={cameraMovement} />}
            {duration != null && <MetaItem label="时长" value={`${duration}s`} />}
            {seed != null && <MetaItem label="Seed" value={String(seed)} />}
          </div>
        </div>
      </div>

      {/* Action bar */}
      {status !== "completed" && (
        <div className="mt-4 flex flex-wrap gap-2 border-t border-[#515151] pt-4">
          <ActionButton
            onClick={() => compileMutation.mutate()}
            disabled={compileMutation.isPending}
            icon={<Zap className="h-3.5 w-3.5" />}
            label="编译提示词"
          />
          {NEXT_STATUS[status] && (
            <ActionButton
              onClick={() => advanceMutation.mutate(NEXT_STATUS[status])}
              disabled={advanceMutation.isPending}
              icon={<Play className="h-3.5 w-3.5" />}
              label={NEXT_LABELS[status]}
              primary
            />
          )}
          {status === "pending_review_image" && (
            <>
              <ActionButton
                onClick={() => retryMutation.mutate()}
                disabled={retryMutation.isPending}
                icon={<RotateCcw className="h-3.5 w-3.5" />}
                label="手动重试"
              />
              <ActionButton
                onClick={() => forcePassMutation.mutate()}
                disabled={forcePassMutation.isPending}
                icon={<CheckCircle2 className="h-3.5 w-3.5" />}
                label="强制通过"
                variant="green"
              />
            </>
          )}
        </div>
      )}
    </div>
  )
}

function InfoBlock({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded border border-[#515151] bg-[#3C3F41] p-2">
      <p className="mb-1 text-[10px] font-medium text-[#6A7579]">{label}</p>
      <div className="text-xs text-[#A9B7C6]">{children}</div>
    </div>
  )
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-[#515151] bg-[#3C3F41] px-2 py-1">
      <p className="text-[9px] text-[#6A7579]">{label}</p>
      <p className="text-xs text-[#A9B7C6]">{value}</p>
    </div>
  )
}

function ActionButton({
  onClick, disabled, icon, label, primary, variant,
}: {
  onClick: () => void
  disabled: boolean
  icon: React.ReactNode
  label: string
  primary?: boolean
  variant?: "green"
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "flex items-center gap-1.5 rounded px-3 py-1.5 text-xs transition-colors disabled:opacity-50",
        primary
          ? "bg-[#4B6EAF] text-white hover:bg-[#5A7DBF]"
          : variant === "green"
          ? "bg-green-600/20 text-green-400 hover:bg-green-600/30"
          : "bg-[#3C3F41] text-[#A9B7C6] hover:bg-[#4B6EAF]/40"
      )}
    >
      {disabled && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
      {!disabled && icon}
      {label}
    </button>
  )
}
