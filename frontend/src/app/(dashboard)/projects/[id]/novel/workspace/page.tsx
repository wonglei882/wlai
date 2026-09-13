"use client"

import { use, useState, useCallback, useEffect } from "react"
import { Group, Panel, Separator } from "react-resizable-panels"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { toast } from "@/store/toast-store"
import { NovelChapterPanel } from "@/components/workspace/novel-chapter-panel"
import { ChapterEditor } from "@/components/workspace/chapter-editor"
import { StoryboardPreview } from "@/components/workspace/storyboard-preview"
import { ToolWindow } from "@/components/workspace/tool-window"
import { cn } from "@/lib/utils"
import {
  BookOpen, Clapperboard, FileText,
} from "lucide-react"

type CenterView = "editor" | "storyboard"

export default function NovelWorkspacePage({ params }: { params: Promise<{ id: string }> }) {
  const { id: projectId } = use(params)
  const queryClient = useQueryClient()

  const [selectedChapterId, setSelectedChapterId] = useState<string | null>(null)
  const [centerView, setCenterView] = useState<CenterView>("editor")
  const [storyboardId, setStoryboardId] = useState<string | null>(null)
  const [leftTab, setLeftTab] = useState<"chapters" | "characters">("chapters")

  // 布局持久化：恢复
  useEffect(() => {
    try {
      const raw = localStorage.getItem(`wlai_novel_ws_${projectId}`)
      if (raw) {
        const data = JSON.parse(raw)
        if (data.centerView) setCenterView(data.centerView)
        if (data.leftTab) setLeftTab(data.leftTab)
        if (data.selectedChapterId) setSelectedChapterId(data.selectedChapterId)
      }
    } catch { /* ignore */ }
  }, [projectId])

  // 布局持久化：保存
  useEffect(() => {
    const data = { centerView, leftTab, selectedChapterId }
    localStorage.setItem(`wlai_novel_ws_${projectId}`, JSON.stringify(data))
  }, [projectId, centerView, leftTab, selectedChapterId])

  // 转分镜 mutation
  const convertMutation = useMutation({
    mutationFn: (data: { text: string; project_id: string; title?: string }) =>
      api.generateStoryboard(data),
    onSuccess: (result) => {
      const sbId = result.storyboard_id as string
      setStoryboardId(sbId)
      setCenterView("storyboard")
      queryClient.invalidateQueries({ queryKey: ["project-shots", projectId] })
      toast.success("分镜生成成功")
    },
    onError: () => {
      toast.error("分镜生成失败")
    },
  })

  const handleSelectChapter = useCallback((chapterId: string) => {
    setSelectedChapterId(chapterId)
    setCenterView("editor")
  }, [])

  const handleConvertToStoryboard = useCallback((chapterId: string, content: string) => {
    convertMutation.mutate({
      text: content,
      project_id: projectId,
      title: `章节转换`,
    })
  }, [projectId, convertMutation])

  const handleQuickConvert = useCallback((chapterId: string) => {
    // 先获取章节内容再转换
    api.getChapter(chapterId).then((chapter) => {
      if (chapter.content) {
        handleConvertToStoryboard(chapterId, chapter.content)
      } else {
        toast.warning("章节内容为空")
      }
    }).catch(() => {
      toast.error("获取章节内容失败")
    })
  }, [handleConvertToStoryboard])

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col bg-[#2B2B2B]">
      {/* Main panel area */}
      <Group orientation="horizontal" className="flex-1">
        {/* Left Panel */}
        <Panel defaultSize={20} minSize={12} maxSize={35} id="novel-left">
          <div className="flex h-full flex-col bg-[#2B2B2B]">
            {/* Left tab bar */}
            <div className="flex h-7 shrink-0 items-center border-b border-[#515151] bg-[#3C3F41]">
              <button
                onClick={() => setLeftTab("chapters")}
                className={cn(
                  "h-full flex items-center gap-1 px-3 text-[11px] font-medium border-b-2 transition-colors",
                  leftTab === "chapters"
                    ? "border-[#4B6EAF] text-[#A9B7C6]"
                    : "border-transparent text-[#6A7579] hover:text-[#A9B7C6]"
                )}
              >
                <FileText className="h-3 w-3" />
                章节
              </button>
              <button
                onClick={() => setLeftTab("characters")}
                className={cn(
                  "h-full flex items-center gap-1 px-3 text-[11px] font-medium border-b-2 transition-colors",
                  leftTab === "characters"
                    ? "border-[#4B6EAF] text-[#A9B7C6]"
                    : "border-transparent text-[#6A7579] hover:text-[#A9B7C6]"
                )}
              >
                <BookOpen className="h-3 w-3" />
                角色
              </button>
            </div>
            {/* Left content */}
            <div className="flex-1 overflow-hidden">
              {leftTab === "chapters" ? (
                <NovelChapterPanel
                  projectId={projectId}
                  selectedChapterId={selectedChapterId}
                  onSelectChapter={handleSelectChapter}
                  onConvertToStoryboard={handleQuickConvert}
                />
              ) : (
                <CharacterPanel projectId={projectId} />
              )}
            </div>
          </div>
        </Panel>

        <Separator className="w-1 bg-[#515151] data-[separator=true]:bg-[#4B6EAF]" />

        {/* Center Editor */}
        <Panel defaultSize={55} minSize={30} id="novel-center">
          <div className="flex h-full flex-col bg-[#2B2B2B]">
            {/* Center tab bar */}
            <div className="flex h-7 shrink-0 items-center border-b border-[#515151] bg-[#3C3F41]">
              <button
                onClick={() => setCenterView("editor")}
                className={cn(
                  "h-full flex items-center gap-1 px-3 text-[11px] font-medium border-b-2 transition-colors",
                  centerView === "editor"
                    ? "border-[#4B6EAF] text-[#A9B7C6]"
                    : "border-transparent text-[#6A7579] hover:text-[#A9B7C6]"
                )}
              >
                <FileText className="h-3 w-3" />
                章节编辑
              </button>
              <button
                onClick={() => setCenterView("storyboard")}
                className={cn(
                  "h-full flex items-center gap-1 px-3 text-[11px] font-medium border-b-2 transition-colors",
                  centerView === "storyboard"
                    ? "border-[#4B6EAF] text-[#A9B7C6]"
                    : "border-transparent text-[#6A7579] hover:text-[#A9B7C6]"
                )}
              >
                <Clapperboard className="h-3 w-3" />
                分镜预览
                {storyboardId && (
                  <span className="ml-1 rounded bg-green-600/30 px-1 text-[9px] text-green-400">
                    已生成
                  </span>
                )}
              </button>
            </div>
            {/* Center content */}
            <div className="flex-1 overflow-hidden">
              {centerView === "editor" ? (
                selectedChapterId ? (
                  <ChapterEditor
                    projectId={projectId}
                    chapterId={selectedChapterId}
                    onConvertToStoryboard={handleConvertToStoryboard}
                  />
                ) : (
                  <div className="flex h-full items-center justify-center bg-[#2B2B2B] text-[#6A7579] text-sm">
                    <div className="text-center">
                      <FileText className="h-8 w-8 mx-auto mb-2 opacity-30" />
                      <p>选择左侧章节开始编辑</p>
                      <p className="text-[10px] mt-1">或创建新章节输入小说内容</p>
                    </div>
                  </div>
                )
              ) : (
                <StoryboardPreview
                  projectId={projectId}
                  storyboardId={storyboardId}
                  onBackToEditor={() => setCenterView("editor")}
                />
              )}
            </div>
          </div>
        </Panel>

        {/* Right Panel — Properties */}
        <Panel defaultSize={25} minSize={15} maxSize={40} id="novel-right">
          <ToolWindow title="项目信息">
            <NovelProjectInfo projectId={projectId} />
          </ToolWindow>
        </Panel>
      </Group>

      {/* Status Bar */}
      <NovelStatusBar projectId={projectId} />
    </div>
  )
}

// ---- Character Panel (compact) ----
function CharacterPanel({ projectId }: { projectId: string }) {
  const { data: charsData } = require("@tanstack/react-query").useQuery({
    queryKey: ["characters", projectId],
    queryFn: () => api.listCharacters(projectId),
  })
  const characters = charsData?.characters ?? []

  return (
    <div className="h-full overflow-auto bg-[#2B2B2B] text-[#A9B7C6] text-xs">
      {characters.length === 0 ? (
        <div className="px-4 py-6 text-center text-[#6A7579]">
          <BookOpen className="h-6 w-6 mx-auto mb-2 opacity-30" />
          <p>暂无角色</p>
          <p className="text-[10px] mt-1">在漫剧工作台中创建角色卡</p>
        </div>
      ) : (
        characters.map((char: Record<string, unknown>) => (
          <div
            key={char.id as string}
            className="flex items-center gap-2 py-1.5 px-3 hover:bg-[#4B6EAF]/30 cursor-pointer"
          >
            <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[#4B6EAF]/40 text-[10px] font-bold text-white">
              {String(char.name || "?")[0]}
            </div>
            <div className="flex-1 min-w-0">
              <p className="truncate text-[12px] font-medium">{String(char.name)}</p>
              {!!char.personality && (
                <p className="truncate text-[10px] text-[#6A7579]">{String(char.personality)}</p>
              )}
            </div>
            {char.status === "locked" && (
              <span className="text-[10px] text-green-400">锁定</span>
            )}
          </div>
        ))
      )}
    </div>
  )
}

// ---- Project Info Panel ----
function NovelProjectInfo({ projectId }: { projectId: string }) {
  const { data: project } = require("@tanstack/react-query").useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
  })

  const { data: chaptersData } = require("@tanstack/react-query").useQuery({
    queryKey: ["novel-chapters", projectId],
    queryFn: () => api.listChapters(projectId),
  })

  const chapters = chaptersData?.chapters ?? []
  const totalWords = chapters.reduce((sum: number, ch: Record<string, unknown>) => sum + (ch.word_count as number || 0), 0)

  return (
    <div className="h-full overflow-auto bg-[#2B2B2B] text-[#A9B7C6] text-xs p-3 space-y-3">
      <div>
        <p className="text-[10px] text-[#6A7579] uppercase tracking-wide">项目</p>
        <p className="text-[13px] font-medium mt-0.5">{project?.title || "加载中..."}</p>
        {project?.description && (
          <p className="text-[11px] text-[#6A7579] mt-1">{project.description}</p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="rounded bg-[#3C3F41] p-2">
          <p className="text-[10px] text-[#6A7579]">章节数</p>
          <p className="text-[16px] font-bold">{chapters.length}</p>
        </div>
        <div className="rounded bg-[#3C3F41] p-2">
          <p className="text-[10px] text-[#6A7579]">总字数</p>
          <p className="text-[16px] font-bold">{totalWords.toLocaleString()}</p>
        </div>
      </div>

      <div>
        <p className="text-[10px] text-[#6A7579] uppercase tracking-wide mb-1">工作流</p>
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-[11px]">
            <span className="flex h-4 w-4 items-center justify-center rounded-full bg-[#4B6EAF] text-[9px] text-white">1</span>
            <span>编写章节内容</span>
          </div>
          <div className="flex items-center gap-2 text-[11px]">
            <span className="flex h-4 w-4 items-center justify-center rounded-full bg-[#4B6EAF] text-[9px] text-white">2</span>
            <span>点击「转分镜」</span>
          </div>
          <div className="flex items-center gap-2 text-[11px]">
            <span className="flex h-4 w-4 items-center justify-center rounded-full bg-[#4B6EAF] text-[9px] text-white">3</span>
            <span>预览分镜结果</span>
          </div>
          <div className="flex items-center gap-2 text-[11px]">
            <span className="flex h-4 w-4 items-center justify-center rounded-full bg-[#4B6EAF] text-[9px] text-white">4</span>
            <span>推送到漫剧工作台</span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ---- Status Bar ----
function NovelStatusBar({ projectId }: { projectId: string }) {
  const { data: chaptersData } = require("@tanstack/react-query").useQuery({
    queryKey: ["novel-chapters", projectId],
    queryFn: () => api.listChapters(projectId),
  })

  const chapters = chaptersData?.chapters ?? []
  const totalWords = chapters.reduce((sum: number, ch: Record<string, unknown>) => sum + (ch.word_count as number || 0), 0)

  return (
    <div className="flex h-5 shrink-0 items-center gap-4 border-t border-[#515151] bg-[#3C3F41] px-3 text-[10px] text-[#6A7579]">
      <span>
        章节 <span className="text-[#A9B7C6]">{chapters.length}</span>
      </span>
      <span className="text-[#515151]">|</span>
      <span>
        总字数 <span className="text-[#A9B7C6]">{totalWords.toLocaleString()}</span>
      </span>
      <span className="text-[#515151]">|</span>
      <span>小说转剧本工作台</span>
      <span className="ml-auto text-[#A9B7C6]">WLai</span>
    </div>
  )
}
