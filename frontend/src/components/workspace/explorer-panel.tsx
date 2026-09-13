"use client"

import { use, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { useWorkspaceStore } from "@/store/workspace-store"
import { cn } from "@/lib/utils"
import {
  ChevronRight, ChevronDown, Film, Clapperboard, Users,
} from "lucide-react"
import { SkeletonList } from "@/components/ui/skeleton"

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

export function ExplorerPanel({ projectId }: { projectId: string }) {
  const {
    selectedShotId, selectedEpisodeId, selectedCharacterId,
    selectShot, selectEpisode, selectCharacter, addCenterTab,
  } = useWorkspaceStore()

  const [episodesOpen, setEpisodesOpen] = useState(true)
  const [shotsOpen, setShotsOpen] = useState(true)
  const [charsOpen, setCharsOpen] = useState(true)

  // Data fetching
  const { data: epsData, isLoading: epsLoading } = useQuery({
    queryKey: ["episodes", projectId],
    queryFn: () => api.listEpisodes(projectId),
  })
  const { data: shotsData, isLoading: shotsLoading } = useQuery({
    queryKey: ["project-shots", projectId],
    queryFn: () => api.getShotsByProject(projectId),
  })
  const { data: charsData, isLoading: charsLoading } = useQuery({
    queryKey: ["characters", projectId],
    queryFn: () => api.listCharacters(projectId),
  })

  const episodes = epsData?.episodes ?? []
  const shots = (shotsData?.shots ?? []) as Record<string, unknown>[]
  const characters = charsData?.characters ?? []

  return (
    <div className="h-full overflow-auto bg-[#2B2B2B] text-[#A9B7C6] text-xs">
      {/* Episodes Section */}
      <TreeSection
        label="集数"
        icon={<Film className="h-3.5 w-3.5" />}
        open={episodesOpen}
        onToggle={() => setEpisodesOpen(!episodesOpen)}
        count={episodes.length}
      >
        {epsLoading ? (
          <div className="px-4 py-2"><SkeletonList rows={3} /></div>
        ) : episodes.length === 0 ? (
          <div className="px-6 py-1 text-[#6A7579]">暂无集数</div>
        ) : (
          episodes.map((ep) => (
            <div
              key={ep.id}
              className={cn(
                "flex items-center gap-1.5 py-0.5 px-4 cursor-pointer hover:bg-[#4B6EAF]/30",
                selectedEpisodeId === ep.id && "bg-[#4B6EAF]/50"
              )}
              onClick={() => selectEpisode(ep.id)}
            >
              <ChevronRight className="h-3 w-3 text-[#6A7579]" />
              <span className="truncate">
                第 {ep.episode_number} 集{ep.title ? `: ${ep.title}` : ""}
              </span>
              <span className={cn(
                "ml-auto text-[10px]",
                ep.status === "completed" ? "text-green-400" : "text-[#6A7579]"
              )}>
                {ep.status === "draft" ? "草稿" : ep.status === "completed" ? "完成" : ep.status}
              </span>
            </div>
          ))
        )}
      </TreeSection>

      {/* Shots Section */}
      <TreeSection
        label="镜头"
        icon={<Clapperboard className="h-3.5 w-3.5" />}
        open={shotsOpen}
        onToggle={() => setShotsOpen(!shotsOpen)}
        count={shots.length}
      >
        {shotsLoading ? (
          <div className="px-4 py-2"><SkeletonList rows={3} /></div>
        ) : shots.length === 0 ? (
          <div className="px-6 py-1 text-[#6A7579]">暂无镜头</div>
        ) : (
          shots.map((shot) => {
            const shotId = shot.id as string
            const num = shot.shot_number as number
            const status = shot.status as string
            return (
              <div
                key={shotId}
                className={cn(
                  "flex items-center gap-1.5 py-0.5 px-4 cursor-pointer hover:bg-[#4B6EAF]/30",
                  selectedShotId === shotId && "bg-[#4B6EAF]/50"
                )}
                onClick={() => selectShot(shotId)}
                onDoubleClick={() => {
                  addCenterTab({
                    id: `shot-${shotId}`,
                    label: `镜头 #${num}`,
                    type: "shot",
                    shotId,
                  })
                }}
              >
                <span className={cn("h-1.5 w-1.5 rounded-full", STATUS_COLORS[status] || "text-gray-400")}
                  style={{ backgroundColor: "currentColor" }} />
                <span className="truncate">#{num} 镜头</span>
                <span className={cn("ml-auto text-[10px]", STATUS_COLORS[status])}>
                  {STATUS_LABELS[status] || status}
                </span>
              </div>
            )
          })
        )}
      </TreeSection>

      {/* Characters Section */}
      <TreeSection
        label="角色"
        icon={<Users className="h-3.5 w-3.5" />}
        open={charsOpen}
        onToggle={() => setCharsOpen(!charsOpen)}
        count={characters.length}
      >
        {charsLoading ? (
          <div className="px-4 py-2"><SkeletonList rows={3} /></div>
        ) : characters.length === 0 ? (
          <div className="px-6 py-1 text-[#6A7579]">暂无角色</div>
        ) : (
          characters.map((char) => (
            <div
              key={char.id}
              className={cn(
                "flex items-center gap-1.5 py-0.5 px-4 cursor-pointer hover:bg-[#4B6EAF]/30",
                selectedCharacterId === char.id && "bg-[#4B6EAF]/50"
              )}
              onClick={() => selectCharacter(char.id)}
            >
              <div className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-[#4B6EAF]/40 text-[9px] font-bold text-white">
                {char.name?.[0] || "?"}
              </div>
              <span className="truncate">{char.name}</span>
              {char.status === "locked" && (
                <span className="ml-auto text-[10px] text-green-400">锁定</span>
              )}
            </div>
          ))
        )}
      </TreeSection>
    </div>
  )
}

function TreeSection({
  label, icon, open, onToggle, count, children,
}: {
  label: string
  icon: React.ReactNode
  open: boolean
  onToggle: () => void
  count: number
  children: React.ReactNode
}) {
  return (
    <div>
      <div
        className="flex h-6 items-center gap-1 bg-[#3C3F41] px-2 cursor-pointer select-none hover:bg-[#4B6EAF]/30"
        onClick={onToggle}
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        {icon}
        <span className="font-medium">{label}</span>
        <span className="text-[#6A7579]">({count})</span>
      </div>
      {open && <div>{children}</div>}
    </div>
  )
}
