"use client"

import { use } from "react"
import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { BookOpen, Film, ArrowLeft, Monitor } from "lucide-react"
import { SkeletonCard } from "@/components/ui/skeleton"
import Link from "next/link"

export default function ProjectDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)

  const { data: project, isLoading } = useQuery({
    queryKey: ["project", id],
    queryFn: () => api.getProject(id),
  })

  if (isLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    )
  }

  if (!project) {
    return (
      <div className="py-12 text-center text-muted-foreground">
        项目不存在或已被删除
      </div>
    )
  }

  const isComic = project.genre === "comic"

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Link href="/projects" className="flex items-center gap-1 hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
          项目列表
        </Link>
        <span>/</span>
        <span className="text-foreground">{project.title}</span>
      </div>

      {/* Project Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-bold">{project.title}</h1>
            <Badge variant="secondary">
              {isComic ? "漫剧" : "小说"}
            </Badge>
          </div>
          <p className="mt-1 text-muted-foreground">{project.description || "暂无描述"}</p>
        </div>
      </div>

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>当前字数</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{project.current_words?.toLocaleString() || 0}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>目标字数</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{project.target_words?.toLocaleString() || 0}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>章节数</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{project.chapter_count || 0}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>状态</CardDescription>
          </CardHeader>
          <CardContent>
            <Badge variant={project.status === "active" ? "success" : "outline"}>
              {project.status === "active" ? "进行中" : project.status}
            </Badge>
          </CardContent>
        </Card>
      </div>

      {/* Quick Actions */}
      <div className="grid gap-4 md:grid-cols-2">
        {isComic ? (
          <>
            {/* IDE Workspace - primary entry */}
            <Link href={`/projects/${id}/comic/workspace`}>
              <Card className="cursor-pointer border-primary/30 hover:border-primary hover:shadow-md transition-all">
                <CardHeader>
                  <div className="flex items-center gap-3">
                    <Monitor className="h-5 w-5 text-primary" />
                    <CardTitle className="text-lg">IDE 工作台</CardTitle>
                    <Badge variant="outline" className="text-xs ml-auto">推荐</Badge>
                  </div>
                  <CardDescription>JetBrains 风格全功能工作台：资源浏览器、分镜网格、镜头编辑、审核控制台</CardDescription>
                </CardHeader>
              </Card>
            </Link>
            <Card className="cursor-pointer hover:shadow-md transition-shadow opacity-70">
              <Link href={`/projects/${id}/comic/bible`}>
                <CardHeader>
                  <div className="flex items-center gap-3">
                    <Film className="h-5 w-5 text-primary" />
                    <CardTitle className="text-lg">设定圣经</CardTitle>
                    <span className="text-xs text-muted-foreground ml-auto">经典视图</span>
                  </div>
                  <CardDescription>管理角色卡、世界观、画风设定</CardDescription>
                </CardHeader>
              </Link>
            </Card>
          </>
        ) : (
          <>
            {/* 剧本工作台 - 主入口 */}
            <Link href={`/projects/${id}/novel/workspace`}>
              <Card className="cursor-pointer border-primary/30 hover:border-primary hover:shadow-md transition-all">
                <CardHeader>
                  <div className="flex items-center gap-3">
                    <Monitor className="h-5 w-5 text-primary" />
                    <CardTitle className="text-lg">剧本工作台</CardTitle>
                    <Badge variant="outline" className="text-xs ml-auto">推荐</Badge>
                  </div>
                  <CardDescription>导入小说 → PM 分析 → 生成剧本：导入小说内容，PM 自动分析生成结构化剧本</CardDescription>
                </CardHeader>
              </Card>
            </Link>
            <Card className="cursor-pointer hover:shadow-md transition-shadow">
              <CardHeader>
                <div className="flex items-center gap-3">
                  <BookOpen className="h-5 w-5 text-primary" />
                  <CardTitle className="text-lg">PM Agent 诊断</CardTitle>
                </div>
                <CardDescription>角色一致性、伏笔追踪、大纲漂移检测</CardDescription>
              </CardHeader>
            </Card>
          </>
        )}
      </div>

      {/* PM Panel Link */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">PM Agent 诊断</CardTitle>
          <CardDescription>查看项目健康状态、诊断日志和决策记录</CardDescription>
        </CardHeader>
        <CardContent>
          <Link href={`/projects/${id}/pm`}>
            <Button variant="outline">
              打开诊断面板
            </Button>
          </Link>
        </CardContent>
      </Card>
    </div>
  )
}
