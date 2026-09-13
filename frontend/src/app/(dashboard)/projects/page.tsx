"use client"

import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useRouter } from "next/navigation"
import { api } from "@/lib/api-client"
import type { Project } from "@/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Plus, BookOpen, Film, Sparkles } from "lucide-react"
import { SkeletonCard } from "@/components/ui/skeleton"
import { OnboardingWizard } from "@/components/onboarding/onboarding-wizard"

export default function ProjectsPage() {
  const [showCreate, setShowCreate] = useState(false)
  const [showOnboarding, setShowOnboarding] = useState(false)
  const queryClient = useQueryClient()
  const router = useRouter()

  const { data, isLoading, error } = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.getProjects(),
  })

  const createMutation = useMutation({
    mutationFn: (data: { title: string; description?: string; genre?: string; target_words?: number }) =>
      api.createProject(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] })
      setShowCreate(false)
    },
  })

  const projects = data?.projects || []

  // 首次访问且无项目时显示引导
  const shouldShowOnboarding = !isLoading && !error && projects.length === 0 && !showOnboarding
  if (shouldShowOnboarding && !showCreate) {
    // 延迟一帧显示，避免闪烁
    setTimeout(() => setShowOnboarding(true), 100)
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">我的项目</h1>
          <p className="text-muted-foreground">管理你的小说和漫剧项目</p>
        </div>
        <Button onClick={() => setShowCreate(!showCreate)}>
          <Plus className="mr-2 h-4 w-4" />
          新建项目
        </Button>
      </div>

      {/* Create Form */}
      {showCreate && (
        <Card>
          <CardHeader>
            <CardTitle>新建项目</CardTitle>
            <CardDescription>创建一个新的创作项目</CardDescription>
          </CardHeader>
          <CardContent>
            <CreateProjectForm
              onSubmit={(data) => createMutation.mutate(data)}
              onCancel={() => setShowCreate(false)}
              isLoading={createMutation.isPending}
              error={createMutation.error?.message}
            />
          </CardContent>
        </Card>
      )}

      {/* Project List */}
      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      ) : error ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            无法连接后端，请确认后端服务已启动
          </CardContent>
        </Card>
      ) : projects.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-muted-foreground mb-4">还没有项目，开始创作吧</p>
            <div className="flex gap-2 justify-center">
              <Button onClick={() => setShowOnboarding(true)}>
                <Sparkles className="mr-2 h-4 w-4" />
                新建引导
              </Button>
              <Button variant="outline" onClick={() => setShowCreate(true)}>
                <Plus className="mr-2 h-4 w-4" />
                直接创建
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {projects.map((project) => (
            <ProjectCard key={project.id} project={project} onClick={() => router.push(`/projects/${project.id}`)} />
          ))}
        </div>
      )}

      {/* Onboarding Wizard */}
      {showOnboarding && (
        <OnboardingWizard onComplete={() => setShowOnboarding(false)} />
      )}
    </div>
  )
}

function ProjectCard({ project, onClick }: { project: Project; onClick: () => void }) {
  const genreLabel: Record<string, string> = {
    novel: "小说",
    comic: "漫剧",
  }

  return (
    <Card className="cursor-pointer transition-shadow hover:shadow-md" onClick={onClick}>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <CardTitle className="text-lg line-clamp-1">{project.title}</CardTitle>
          <Badge variant="secondary" className="shrink-0 ml-2">
            {project.genre ? genreLabel[project.genre] || project.genre : "未分类"}
          </Badge>
        </div>
        <CardDescription className="line-clamp-2">
          {project.description || "暂无描述"}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <div className="flex items-center gap-1">
            {project.genre === "comic" ? (
              <Film className="h-3.5 w-3.5" />
            ) : (
              <BookOpen className="h-3.5 w-3.5" />
            )}
            <span>
              {project.current_words?.toLocaleString() || 0} / {project.target_words?.toLocaleString() || 0} 字
            </span>
          </div>
          <Badge
            variant={project.status === "active" ? "success" : "outline"}
            className="text-xs"
          >
            {project.status === "active" ? "进行中" : project.status}
          </Badge>
        </div>
      </CardContent>
    </Card>
  )
}

function CreateProjectForm({
  onSubmit,
  onCancel,
  isLoading,
  error,
}: {
  onSubmit: (data: { title: string; description?: string; genre?: string; target_words?: number }) => void
  onCancel: () => void
  isLoading: boolean
  error?: string
}) {
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const [genre, setGenre] = useState("novel")
  const [targetWords, setTargetWords] = useState("100000")

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSubmit({
      title,
      description: description || undefined,
      genre,
      target_words: parseInt(targetWords) || undefined,
    })
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{error}</div>
      )}
      <div className="space-y-2">
        <Label htmlFor="title">项目标题</Label>
        <Input
          id="title"
          placeholder="输入项目标题"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="description">项目描述</Label>
        <Textarea
          id="description"
          placeholder="简要描述你的项目"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
        />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor="genre">项目类型</Label>
          <select
            id="genre"
            value={genre}
            onChange={(e) => setGenre(e.target.value)}
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          >
            <option value="novel">小说</option>
            <option value="comic">漫剧</option>
          </select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="targetWords">目标字数</Label>
          <Input
            id="targetWords"
            type="number"
            placeholder="100000"
            value={targetWords}
            onChange={(e) => setTargetWords(e.target.value)}
            min={1000}
          />
        </div>
      </div>
      <div className="flex gap-2">
        <Button type="submit" disabled={isLoading}>
          {isLoading ? "创建中..." : "创建项目"}
        </Button>
        <Button type="button" variant="outline" onClick={onCancel}>
          取消
        </Button>
      </div>
    </form>
  )
}
