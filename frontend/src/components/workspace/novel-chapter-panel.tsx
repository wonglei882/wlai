"use client"

import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { cn } from "@/lib/utils"
import { toast } from "@/store/toast-store"
import { SkeletonList } from "@/components/ui/skeleton"
import {
  FileText, Plus, ChevronRight, ChevronDown, Trash2,
  Loader2, ArrowRightCircle,
} from "lucide-react"

export function NovelChapterPanel({
  projectId,
  selectedChapterId,
  onSelectChapter,
  onConvertToStoryboard,
}: {
  projectId: string
  selectedChapterId: string | null
  onSelectChapter: (id: string) => void
  onConvertToStoryboard: (chapterId: string) => void
}) {
  const queryClient = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [newTitle, setNewTitle] = useState("")
  const [newNumber, setNewNumber] = useState(1)
  const [expandedChars, setExpandedChars] = useState(true)

  const { data, isLoading } = useQuery({
    queryKey: ["novel-chapters", projectId],
    queryFn: () => api.listChapters(projectId),
  })

  const { data: charsData } = useQuery({
    queryKey: ["characters", projectId],
    queryFn: () => api.listCharacters(projectId),
  })

  const chapters = data?.chapters ?? []
  const characters = charsData?.characters ?? []

  const createMutation = useMutation({
    mutationFn: (data: { project_id: string; chapter_number: number; title: string }) =>
      api.createChapter(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["novel-chapters", projectId] })
      setShowCreate(false)
      setNewTitle("")
      setNewNumber(chapters.length + 1)
      toast.success("章节已创建")
    },
    onError: () => {
      toast.error("创建章节失败")
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (chapterId: string) => api.deleteChapter(chapterId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["novel-chapters", projectId] })
      toast.success("章节已删除")
    },
  })

  const handleCreate = () => {
    if (!newTitle.trim()) return
    createMutation.mutate({
      project_id: projectId,
      chapter_number: newNumber,
      title: newTitle.trim(),
    })
  }

  return (
    <div className="h-full overflow-auto bg-[#2B2B2B] text-[#A9B7C6] text-xs">
      {/* Chapters Section */}
      <div>
        <div className="flex h-6 items-center gap-1 bg-[#3C3F41] px-2 select-none">
          <FileText className="h-3.5 w-3.5" />
          <span className="font-medium flex-1">章节</span>
          <span className="text-[#6A7579]">({chapters.length})</span>
          <button
            onClick={() => setShowCreate(!showCreate)}
            className="ml-1 rounded p-0.5 hover:bg-[#4B6EAF]/40 text-[#6A7579] hover:text-[#A9B7C6]"
            title="新建章节"
          >
            <Plus className="h-3 w-3" />
          </button>
        </div>

        {/* Create form */}
        {showCreate && (
          <div className="border-b border-[#515151] bg-[#3C3F41] p-2 space-y-1.5">
            <div className="flex gap-1.5">
              <input
                type="number"
                value={newNumber}
                onChange={(e) => setNewNumber(parseInt(e.target.value) || 1)}
                className="w-12 rounded bg-[#2B2B2B] border border-[#515151] px-1.5 py-0.5 text-[11px] text-[#A9B7C6]"
                min={1}
              />
              <input
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                placeholder="章节标题"
                className="flex-1 rounded bg-[#2B2B2B] border border-[#515151] px-1.5 py-0.5 text-[11px] text-[#A9B7C6]"
                onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              />
            </div>
            <div className="flex gap-1.5">
              <button
                onClick={handleCreate}
                disabled={createMutation.isPending || !newTitle.trim()}
                className="rounded bg-[#4B6EAF] px-2 py-0.5 text-[11px] text-white hover:bg-[#4B6EAF]/80 disabled:opacity-50"
              >
                {createMutation.isPending ? "创建中..." : "创建"}
              </button>
              <button
                onClick={() => setShowCreate(false)}
                className="rounded px-2 py-0.5 text-[11px] text-[#6A7579] hover:text-[#A9B7C6]"
              >
                取消
              </button>
            </div>
          </div>
        )}

        {/* Chapter list */}
        {isLoading ? (
          <div className="px-3 py-2"><SkeletonList rows={4} /></div>
        ) : chapters.length === 0 ? (
          <div className="px-4 py-3 text-[#6A7579] text-center">
            暂无章节，点击 + 创建
          </div>
        ) : (
          chapters.map((ch) => (
            <div
              key={ch.id}
              className={cn(
                "group flex items-center gap-1.5 py-1 px-3 cursor-pointer hover:bg-[#4B6EAF]/30 border-l-2",
                selectedChapterId === ch.id
                  ? "bg-[#4B6EAF]/50 border-[#4B6EAF]"
                  : "border-transparent"
              )}
              onClick={() => onSelectChapter(ch.id)}
            >
              <ChevronRight className="h-3 w-3 text-[#6A7579] shrink-0" />
              <span className="text-[#6A7579] shrink-0 w-5 text-right">{ch.chapter_number}</span>
              <span className="truncate flex-1">{ch.title}</span>
              <span className="text-[10px] text-[#6A7579] shrink-0">
                {ch.word_count?.toLocaleString() || 0}字
              </span>
              {/* Actions */}
              <div className="hidden group-hover:flex items-center gap-0.5 shrink-0">
                <button
                  onClick={(e) => { e.stopPropagation(); onConvertToStoryboard(ch.id) }}
                  className="rounded p-0.5 hover:bg-[#4B6EAF]/60 text-[#6A7579] hover:text-green-400"
                  title="转换为分镜"
                >
                  <ArrowRightCircle className="h-3 w-3" />
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); deleteMutation.mutate(ch.id) }}
                  className="rounded p-0.5 hover:bg-[#4B6EAF]/60 text-[#6A7579] hover:text-red-400"
                  title="删除"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Characters Section */}
      <div className="mt-1">
        <div
          className="flex h-6 items-center gap-1 bg-[#3C3F41] px-2 cursor-pointer select-none hover:bg-[#4B6EAF]/30"
          onClick={() => setExpandedChars(!expandedChars)}
        >
          {expandedChars ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          <span className="font-medium">角色</span>
          <span className="text-[#6A7579]">({characters.length})</span>
        </div>
        {expandedChars && (
          <div>
            {characters.length === 0 ? (
              <div className="px-4 py-2 text-[#6A7579]">暂无角色</div>
            ) : (
              characters.map((char) => (
                <div
                  key={char.id}
                  className="flex items-center gap-1.5 py-0.5 px-4 hover:bg-[#4B6EAF]/30 cursor-pointer"
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
          </div>
        )}
      </div>
    </div>
  )
}
