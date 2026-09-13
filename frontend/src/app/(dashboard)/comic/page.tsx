"use client"

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Film, Palette, LayoutGrid, CheckSquare, Shield, Plus, Monitor } from "lucide-react"
import Link from "next/link"
import { SkeletonCard } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

export default function ComicPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.getProjects(),
  })

  const comicProjects = (data?.projects || []).filter(p => p.genre === "comic")

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">漫剧工作台</h1>
          <p className="text-muted-foreground">选择项目开始制片流程</p>
        </div>
        <Link href="/projects">
          <Button>
            <Plus className="mr-2 h-4 w-4" />
            新建漫剧项目
          </Button>
        </Link>
      </div>

      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      ) : comicProjects.length === 0 ? (
        <Card>
          <CardContent className="py-16 text-center">
            <Film className="h-12 w-12 mx-auto mb-4 text-muted-foreground/30" />
            <p className="text-muted-foreground mb-4">还没有漫剧项目</p>
            <Link href="/projects">
              <Button>
                <Plus className="mr-2 h-4 w-4" />
                创建第一个漫剧项目
              </Button>
            </Link>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {comicProjects.map((project) => (
            <Card key={project.id} className="hover:shadow-md transition-shadow">
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between">
                  <div>
                    <CardTitle className="text-lg line-clamp-1">{project.title}</CardTitle>
                    <CardDescription className="line-clamp-2 mt-1">
                      {project.description || "暂无描述"}
                    </CardDescription>
                  </div>
                  <Badge variant={project.status === "active" ? "success" : "outline"} className="text-xs shrink-0">
                    {project.status === "active" ? "进行中" : project.status}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent>
                <div className="text-sm text-muted-foreground mb-3">
                  {project.current_words?.toLocaleString() || 0} 字
                  {project.chapter_count ? ` · ${project.chapter_count} 章` : ""}
                </div>
                <Link href={`/projects/${project.id}/comic/workspace`}>
                  <Button size="sm" className="w-full mb-2">
                    <Monitor className="mr-1 h-3 w-3" />
                    打开 IDE 工作台
                  </Button>
                </Link>
                <div className="grid grid-cols-2 gap-2">
                  <Link href={`/projects/${project.id}/comic/bible`}>
                    <Button variant="outline" size="sm" className="w-full text-xs">
                      <Palette className="mr-1 h-3 w-3" />
                      设定圣经
                    </Button>
                  </Link>
                  <Link href={`/projects/${project.id}/comic/episodes`}>
                    <Button variant="outline" size="sm" className="w-full text-xs">
                      <LayoutGrid className="mr-1 h-3 w-3" />
                      分镜工作台
                    </Button>
                  </Link>
                  <Link href={`/projects/${project.id}/storyboard`}>
                    <Button variant="outline" size="sm" className="w-full text-xs">
                      <Film className="mr-1 h-3 w-3" />
                      镜头工作台
                    </Button>
                  </Link>
                  <Link href={`/projects/${project.id}/pm`}>
                    <Button variant="outline" size="sm" className="w-full text-xs">
                      <Shield className="mr-1 h-3 w-3" />
                      PM 诊断
                    </Button>
                  </Link>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
