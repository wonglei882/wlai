"use client"

import { useState, useEffect, useCallback } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { toast } from "@/store/toast-store"
import { Loader2, Save, ArrowRightCircle } from "lucide-react"

export function ChapterEditor({
  projectId,
  chapterId,
  onConvertToStoryboard,
}: {
  projectId: string
  chapterId: string
  onConvertToStoryboard: (chapterId: string, content: string) => void
}) {
  const queryClient = useQueryClient()
  const { data: chapter, isLoading } = useQuery({
    queryKey: ["novel-chapter", chapterId],
    queryFn: () => api.getChapter(chapterId),
  })

  const [content, setContent] = useState("")
  const [title, setTitle] = useState("")
  const [dirty, setDirty] = useState(false)

  // 加载章节内容
  useEffect(() => {
    if (chapter) {
      setContent(chapter.content || "")
      setTitle(chapter.title || "")
      setDirty(false)
    }
  }, [chapter])

  const updateMutation = useMutation({
    mutationFn: (data: { title?: string; content?: string }) =>
      api.updateChapter(chapterId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["novel-chapter", chapterId] })
      queryClient.invalidateQueries({ queryKey: ["novel-chapters", projectId] })
      setDirty(false)
      toast.success("章节已保存")
    },
    onError: () => {
      toast.error("保存失败")
    },
  })

  const handleSave = useCallback(() => {
    updateMutation.mutate({ title, content })
  }, [title, content, updateMutation])

  const handleConvert = () => {
    if (!content.trim()) {
      toast.warning("章节内容为空，无法转换")
      return
    }
    onConvertToStoryboard(chapterId, content)
  }

  // Ctrl+S 保存
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault()
        handleSave()
      }
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [handleSave])

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center bg-[#2B2B2B]">
        <Loader2 className="h-5 w-5 animate-spin text-[#6A7579]" />
      </div>
    )
  }

  const wordCount = content.length

  return (
    <div className="flex h-full flex-col bg-[#2B2B2B]">
      {/* Toolbar */}
      <div className="flex h-8 shrink-0 items-center gap-2 border-b border-[#515151] bg-[#3C3F41] px-3">
        <input
          value={title}
          onChange={(e) => { setTitle(e.target.value); setDirty(true) }}
          className="flex-1 bg-transparent text-[13px] font-medium text-[#A9B7C6] outline-none"
          placeholder="章节标题"
        />
        <span className="text-[10px] text-[#6A7579] shrink-0">
          {wordCount.toLocaleString()} 字
        </span>
        {dirty && (
          <span className="text-[10px] text-yellow-400 shrink-0">未保存</span>
        )}
        <button
          onClick={handleSave}
          disabled={updateMutation.isPending || !dirty}
          className="flex items-center gap-1 rounded bg-[#4B6EAF] px-2 py-0.5 text-[11px] text-white hover:bg-[#4B6EAF]/80 disabled:opacity-50"
        >
          {updateMutation.isPending ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Save className="h-3 w-3" />
          )}
          保存
        </button>
        <button
          onClick={handleConvert}
          className="flex items-center gap-1 rounded bg-green-600/80 px-2 py-0.5 text-[11px] text-white hover:bg-green-600"
          title="将本章内容转换为漫剧分镜"
        >
          <ArrowRightCircle className="h-3 w-3" />
          转分镜
        </button>
      </div>

      {/* Editor */}
      <textarea
        value={content}
        onChange={(e) => { setContent(e.target.value); setDirty(true) }}
        className="flex-1 resize-none bg-[#2B2B2B] p-4 text-[13px] leading-relaxed text-[#A9B7C6] outline-none placeholder:text-[#6A7579]"
        placeholder="在此输入章节内容...&#10;&#10;支持直接粘贴小说文本。&#10;编辑完成后点击「转分镜」按钮，将自动生成分镜表。"
        spellCheck={false}
      />
    </div>
  )
}
