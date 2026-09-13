"use client"

import { use, useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import type { ComicEpisode } from "@/types"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import {
  Film, Plus, Loader2, Save, Play, CheckCircle2,
  ChevronRight, LayoutGrid,
} from "lucide-react"
import { cn } from "@/lib/utils"
import Link from "next/link"
import { ArrowLeft } from "lucide-react"

export default function ComicEpisodesPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: projectId } = use(params)
  const queryClient = useQueryClient()
  const [selectedEpisode, setSelectedEpisode] = useState<ComicEpisode | null>(null)
  const [showNewEpisode, setShowNewEpisode] = useState(false)

  // ---- 数据查询 ----
  const { data: epsData, isLoading } = useQuery({
    queryKey: ["episodes", projectId],
    queryFn: () => api.listEpisodes(projectId),
  })

  const { data: charsData } = useQuery({
    queryKey: ["characters", projectId],
    queryFn: () => api.listCharacters(projectId),
  })

  const episodes = epsData?.episodes ?? []
  const characters = charsData?.characters ?? []
  const characterNames = characters.map(c => c.name)

  return (
    <div className="space-y-6">
      {/* IDE Banner */}
      <div className="flex items-center justify-between rounded border border-primary/30 bg-primary/5 px-4 py-2">
        <p className="text-sm">新版 IDE 工作台已上线，体验更佳</p>
        <Link href={`/projects/${projectId}/comic/workspace`}>
          <Button size="sm" variant="outline">立即前往 →</Button>
        </Link>
      </div>

      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Link href={`/projects/${projectId}`} className="flex items-center gap-1 hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
          项目详情
        </Link>
        <span>/</span>
        <span className="text-foreground">分镜工作台</span>
      </div>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-3">
            <Film className="h-8 w-8 text-primary" />
            分镜工作台
          </h1>
          <p className="text-muted-foreground mt-1">集数管理、分镜生成与预览</p>
        </div>
        <div className="flex gap-2">
          <Link href={`/projects/${projectId}/storyboard`}>
            <Button variant="outline">
              <LayoutGrid className="mr-2 h-4 w-4" />
              镜头工作台
            </Button>
          </Link>
          <Button onClick={() => setShowNewEpisode(!showNewEpisode)}>
            <Plus className="mr-2 h-4 w-4" />
            新建集数
          </Button>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
        {/* Left: Episode list */}
        <div className="space-y-3">
          {showNewEpisode && (
            <NewEpisodeForm
              projectId={projectId}
              onClose={() => setShowNewEpisode(false)}
            />
          )}

          {isLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
            </div>
          ) : episodes.length === 0 ? (
            <Card>
              <CardContent className="py-8 text-center text-muted-foreground text-sm">
                暂无集数，请先创建
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-2">
              {episodes.map((ep) => (
                <Card
                  key={ep.id}
                  className={cn(
                    "cursor-pointer transition-colors hover:bg-accent/50",
                    selectedEpisode?.id === ep.id && "border-primary bg-accent/30"
                  )}
                  onClick={() => setSelectedEpisode(ep)}
                >
                  <CardContent className="py-3 px-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="font-medium text-sm">
                          第 {ep.episode_number} 集
                        </p>
                        <p className="text-xs text-muted-foreground line-clamp-1">
                          {ep.title || "无标题"}
                        </p>
                      </div>
                      <div className="flex items-center gap-1">
                        <Badge variant={ep.status === "completed" ? "success" : "outline"} className="text-xs">
                          {ep.status === "draft" ? "草稿" : ep.status === "completed" ? "完成" : ep.status}
                        </Badge>
                        <ChevronRight className="h-4 w-4 text-muted-foreground" />
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>

        {/* Right: Storyboard generation & preview */}
        <div className="space-y-4">
          {selectedEpisode ? (
            <StoryboardPanel
              projectId={projectId}
              episode={selectedEpisode}
              characterNames={characterNames}
            />
          ) : (
            <Card>
              <CardContent className="py-16 text-center text-muted-foreground">
                <Film className="h-12 w-12 mx-auto mb-4 opacity-30" />
                <p>选择左侧集数，开始分镜生成</p>
                <p className="text-xs mt-1">或直接输入文本生成分镜</p>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}

// ============================================================================
// 新建集数表单
// ============================================================================
function NewEpisodeForm({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [episodeNumber, setEpisodeNumber] = useState(1)
  const [title, setTitle] = useState("")
  const [summary, setSummary] = useState("")

  const mutation = useMutation({
    mutationFn: () => api.createEpisode({
      project_id: projectId,
      episode_number: episodeNumber,
      title,
      summary,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["episodes", projectId] })
      onClose()
    },
  })

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm">新建集数</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1">
            <Label className="text-xs">集数</Label>
            <Input type="number" min={1} value={episodeNumber}
              onChange={(e) => setEpisodeNumber(parseInt(e.target.value) || 1)} />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">标题</Label>
            <Input placeholder="集数标题" value={title}
              onChange={(e) => setTitle(e.target.value)} />
          </div>
        </div>
        <div className="space-y-1">
          <Label className="text-xs">摘要</Label>
          <Textarea rows={2} placeholder="本集概要..." value={summary}
            onChange={(e) => setSummary(e.target.value)} />
        </div>
        <div className="flex gap-2">
          <Button size="sm" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
            {mutation.isPending ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Save className="mr-1 h-3 w-3" />}
            创建
          </Button>
          <Button size="sm" variant="outline" onClick={onClose}>取消</Button>
        </div>
      </CardContent>
    </Card>
  )
}

// ============================================================================
// 分镜生成与预览面板
// ============================================================================
function StoryboardPanel({
  projectId, episode, characterNames,
}: {
  projectId: string
  episode: ComicEpisode
  characterNames: string[]
}) {
  const queryClient = useQueryClient()
  const [text, setText] = useState("")
  const [generatedResult, setGeneratedResult] = useState<Record<string, unknown> | null>(null)

  const generateMutation = useMutation({
    mutationFn: () => api.generateStoryboard({
      project_id: projectId,
      episode_id: episode.id,
      text,
      character_names: characterNames,
    }),
    onSuccess: (data) => {
      setGeneratedResult(data)
      queryClient.invalidateQueries({ queryKey: ["episodes", projectId] })
    },
  })

  const confirmMutation = useMutation({
    mutationFn: (storyboardId: string) => api.confirmStoryboard(storyboardId),
    onSuccess: () => setGeneratedResult(null),
  })

  const shots = (generatedResult?.shots as Record<string, unknown>[]) ?? []
  const storyboardId = generatedResult?.storyboard_id as string | undefined

  return (
    <div className="space-y-4">
      {/* Episode info */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">
              第 {episode.episode_number} 集: {episode.title || "无标题"}
            </CardTitle>
            <Badge variant="outline">{episode.status}</Badge>
          </div>
          {episode.summary && (
            <CardDescription>{episode.summary}</CardDescription>
          )}
        </CardHeader>
      </Card>

      {/* Text input for generation */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">分镜生成</CardTitle>
          <CardDescription>输入小说/故事文本，AI 自动拆分镜头并生成分镜表</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Textarea
            rows={6}
            placeholder="粘贴或输入本集的小说/故事文本..."
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          {characterNames.length > 0 && (
            <p className="text-xs text-muted-foreground">
              已知角色: {characterNames.join(", ")}
            </p>
          )}
          <Button
            onClick={() => generateMutation.mutate()}
            disabled={generateMutation.isPending || !text.trim()}
          >
            {generateMutation.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Play className="mr-2 h-4 w-4" />
            )}
            生成分镜
          </Button>
        </CardContent>
      </Card>

      {/* Generated result */}
      {generatedResult && (
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">
                分镜预览 — {String(shots.length)} 个镜头
              </CardTitle>
              <div className="flex gap-2">
                {storyboardId && (
                  <Button
                    size="sm"
                    onClick={() => confirmMutation.mutate(storyboardId)}
                    disabled={confirmMutation.isPending}
                  >
                    {confirmMutation.isPending ? (
                      <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                    ) : (
                      <CheckCircle2 className="mr-1 h-3 w-3" />
                    )}
                    确认分镜
                  </Button>
                )}
                <Button size="sm" variant="outline" onClick={() => setGeneratedResult(null)}>
                  关闭
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {shots.map((shot, i) => (
                <div key={i} className="flex items-start gap-3 rounded-md border p-3">
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary text-xs font-bold">
                    {String(shot.shot_number ?? i + 1)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      {(shot.scene_type as string) && (
                        <Badge variant="outline" className="text-xs">{String(shot.scene_type)}</Badge>
                      )}
                      <Badge variant={String(shot.status) === "pending_script" ? "secondary" : "outline"} className="text-xs">
                        {String(shot.status)}
                      </Badge>
                    </div>
                    <p className="text-sm line-clamp-2">{String(shot.visual_description || "")}</p>
                    {(shot.dialogue as string) && (
                      <p className="text-xs text-muted-foreground mt-1">
                        台词: {String(shot.dialogue)}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
            {storyboardId && (
              <div className="mt-4 flex gap-2">
                <Link href={`/projects/${projectId}/storyboard`}>
                  <Button variant="outline" size="sm">
                    <LayoutGrid className="mr-2 h-3 w-3" />
                    在镜头工作台中查看
                  </Button>
                </Link>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
