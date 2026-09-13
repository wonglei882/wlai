"use client"

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { useWorkspaceStore } from "@/store/workspace-store"
import { cn } from "@/lib/utils"
import {
  Loader2, Eye, RotateCcw, Zap, Play, CheckCircle2, Lock, Unlock,
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

export function PropertiesPanel({ projectId }: { projectId: string }) {
  const { selectedShotId, selectedCharacterId, addLog } = useWorkspaceStore()
  const queryClient = useQueryClient()

  // Shot selected
  if (selectedShotId) {
    return <ShotProperties projectId={projectId} shotId={selectedShotId} />
  }

  // Character selected
  if (selectedCharacterId) {
    return <CharacterProperties projectId={projectId} characterId={selectedCharacterId} />
  }

  // Nothing selected
  return (
    <div className="flex h-full items-center justify-center bg-[#2B2B2B] p-4">
      <p className="text-center text-xs text-[#6A7579]">
        选择一个镜头或角色<br />查看属性
      </p>
    </div>
  )
}

// ---- Shot Properties ----
function ShotProperties({ projectId, shotId }: { projectId: string; shotId: string }) {
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
  })

  const advanceMutation = useMutation({
    mutationFn: (target: string) => api.updateShotStatus(shotId, target),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-shots", projectId] })
      addLog("状态流转", `Shot ${shotId.slice(0, 6)}`, "success")
    },
  })

  if (isLoading) {
    return <div className="flex h-full items-center justify-center bg-[#2B2B2B]"><Loader2 className="h-4 w-4 animate-spin text-[#6A7579]" /></div>
  }

  if (!shot) {
    return <div className="flex h-full items-center justify-center bg-[#2B2B2B] text-xs text-[#6A7579]">镜头未找到</div>
  }

  const status = shot.status as string
  const num = shot.shot_number as number
  const score = shot.last_consistency_score as number | null
  const retryCount = (shot.retry_count as number) || 0
  const compiledPrompt = shot.compiled_prompt as string | null
  const seed = shot.seed as number | null
  const cameraMovement = shot.camera_movement as string | null
  const duration = shot.duration as number | null
  const sceneType = shot.scene_type as string | null

  return (
    <div className="h-full overflow-auto bg-[#2B2B2B] p-2 text-xs">
      <div className="space-y-2">
        {/* Header */}
        <div className="flex items-center justify-between">
          <span className="font-medium text-[#A9B7C6]">#{num} 镜头</span>
          <span className={cn(
            "rounded-full border px-1.5 py-0.5 text-[10px]",
            status === "completed" ? "border-green-500/40 text-green-400" :
            status === "pending_review_image" ? "border-yellow-500/40 text-yellow-400" :
            "border-[#515151] text-[#A9B7C6]"
          )}>
            {STATUS_LABELS[status] || status}
          </span>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 gap-1">
          {score != null && (
            <PropItem label="一致性" value={`${(score * 100).toFixed(0)}%`}
              valueClass={score >= 0.9 ? "text-green-400" : score >= 0.7 ? "text-yellow-400" : "text-red-400"} />
          )}
          {retryCount > 0 && <PropItem label="重试次数" value={`x${retryCount}`} valueClass="text-orange-400" />}
          {sceneType && <PropItem label="景别" value={sceneType} />}
          {duration != null && <PropItem label="时长" value={`${duration}s`} />}
          {seed != null && <PropItem label="Seed" value={String(seed)} />}
          {cameraMovement && <PropItem label="运动" value={cameraMovement} />}
        </div>

        {/* Compiled prompt */}
        <div className="rounded border border-[#515151] bg-[#3C3F41] p-1.5">
          <p className="mb-0.5 text-[10px] text-[#6A7579]">编译提示词</p>
          <p className="line-clamp-4 font-mono text-[10px] text-[#A9B7C6]">
            {compiledPrompt || "未编译"}
          </p>
        </div>

        {/* Quick actions */}
        {status !== "completed" && (
          <div className="space-y-1 border-t border-[#515151] pt-2">
            <button
              onClick={() => compileMutation.mutate()}
              disabled={compileMutation.isPending}
              className="flex w-full items-center justify-center gap-1 rounded bg-[#3C3F41] py-1 text-[10px] text-[#A9B7C6] hover:bg-[#4B6EAF]/40 disabled:opacity-50"
            >
              {compileMutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Zap className="h-3 w-3" />}
              编译提示词
            </button>
            {NEXT_STATUS[status] && (
              <button
                onClick={() => advanceMutation.mutate(NEXT_STATUS[status])}
                disabled={advanceMutation.isPending}
                className="flex w-full items-center justify-center gap-1 rounded bg-[#4B6EAF] py-1 text-[10px] text-white hover:bg-[#5A7DBF] disabled:opacity-50"
              >
                {advanceMutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
                {STATUS_LABELS[NEXT_STATUS[status]] || NEXT_STATUS[status]}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ---- Character Properties ----
function CharacterProperties({ projectId, characterId }: { projectId: string; characterId: string }) {
  const queryClient = useQueryClient()

  const { data: charsData, isLoading } = useQuery({
    queryKey: ["characters", projectId],
    queryFn: () => api.listCharacters(projectId),
  })

  const characters = charsData?.characters ?? []
  const char = characters.find((c) => c.id === characterId)

  const lockMutation = useMutation({
    mutationFn: () => api.lockCharacter(characterId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["characters", projectId] }),
  })

  if (isLoading) {
    return <div className="flex h-full items-center justify-center bg-[#2B2B2B]"><Loader2 className="h-4 w-4 animate-spin text-[#6A7579]" /></div>
  }

  if (!char) {
    return <div className="flex h-full items-center justify-center bg-[#2B2B2B] text-xs text-[#6A7579]">角色未找到</div>
  }

  return (
    <div className="h-full overflow-auto bg-[#2B2B2B] p-2 text-xs">
      <div className="space-y-2">
        {/* Avatar + Name */}
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#4B6EAF] text-sm font-bold text-white">
            {char.name?.[0] || "?"}
          </div>
          <div>
            <p className="font-medium text-[#A9B7C6]">{char.name}</p>
            <p className="text-[10px] text-[#6A7579]">
              {[char.gender, char.age].filter(Boolean).join(" · ") || "未设定"}
            </p>
          </div>
        </div>

        {/* Status */}
        <div className="flex items-center justify-between">
          <span className={cn(
            "rounded-full border px-1.5 py-0.5 text-[10px]",
            char.status === "locked" ? "border-green-500/40 text-green-400" : "border-[#515151] text-[#A9B7C6]"
          )}>
            {char.status === "locked" ? "已锁定" : "未锁定"}
          </span>
          <button
            onClick={() => lockMutation.mutate()}
            disabled={lockMutation.isPending}
            className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-[#A9B7C6] hover:bg-[#4B6EAF]/40 disabled:opacity-50"
          >
            {lockMutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> :
              char.status === "locked" ? <Unlock className="h-3 w-3" /> : <Lock className="h-3 w-3" />}
            {char.status === "locked" ? "解锁" : "锁定"}
          </button>
        </div>

        {/* Details */}
        <div className="space-y-1">
          {char.hair && <PropItem label="发型" value={char.hair} />}
          {char.eyes && <PropItem label="瞳色" value={char.eyes} />}
          {char.outfit && <PropItem label="服装" value={char.outfit} />}
          {char.personality && <PropItem label="性格" value={char.personality} />}
          {char.catchphrase && <PropItem label="口头禅" value={`"${char.catchphrase}"`} />}
        </div>

        {/* Appearance prompt */}
        {char.appearance_prompt && (
          <div className="rounded border border-[#515151] bg-[#3C3F41] p-1.5">
            <p className="mb-0.5 text-[10px] text-[#6A7579]">外貌提示词</p>
            <p className="line-clamp-4 text-[10px] text-[#A9B7C6]">{char.appearance_prompt}</p>
          </div>
        )}
      </div>
    </div>
  )
}

// ---- Shared Prop Item ----
function PropItem({ label, value, valueClass }: { label: string; value: string; valueClass?: string }) {
  return (
    <div className="flex items-center justify-between rounded border border-[#515151] bg-[#3C3F41] px-1.5 py-0.5">
      <span className="text-[10px] text-[#6A7579]">{label}</span>
      <span className={cn("text-[10px] text-[#A9B7C6]", valueClass)}>{value}</span>
    </div>
  )
}
