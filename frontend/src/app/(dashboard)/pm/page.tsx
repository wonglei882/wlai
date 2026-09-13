"use client"

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { useAuthStore } from "@/store/auth-store"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Shield, Pause, Play, Square, Activity, Coins, Heart, AlertTriangle, RefreshCw } from "lucide-react"
import Link from "next/link"
import { Skeleton, SkeletonCard, SkeletonList } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

export default function PMPage() {
  const queryClient = useQueryClient()
  const { user } = useAuthStore()
  const userId = user?.id || "system"

  const { data: status, isLoading } = useQuery({
    queryKey: ["pm-status"],
    queryFn: () => api.getPMStatus(),
    refetchInterval: 10000,
  })

  const killMutation = useMutation({
    mutationFn: () => api.pmKill(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["pm-status"] }),
  })

  const pauseMutation = useMutation({
    mutationFn: () => api.pmPause(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["pm-status"] }),
  })

  const resumeMutation = useMutation({
    mutationFn: () => api.pmResume(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["pm-status"] }),
  })

  const isRunning = status && !status.kill_switch && !status.pause_switch
  const isPaused = status?.pause_switch
  const isStopped = status?.kill_switch

  // Token 用量
  const { data: tokenSummary } = useQuery({
    queryKey: ["token-summary"],
    queryFn: () => api.getTokenSummary(7),
    refetchInterval: 120000,
  })

  // 所有项目
  const { data: projectsData } = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.getProjects(),
  })

  const projects = projectsData?.projects || []
  const totalTokens = (tokenSummary?.total_tokens as number) ?? 0
  const byFeature = (tokenSummary?.by_feature as Record<string, number>) ?? {}
  const byModel = (tokenSummary?.by_model as Record<string, number>) ?? {}

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div>
          <Skeleton className="h-8 w-48 mb-2" />
          <Skeleton className="h-4 w-64" />
        </div>
        <SkeletonCard />
        <div className="grid gap-4 md:grid-cols-3">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
        <SkeletonCard />
        <SkeletonList rows={4} />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">PM Agent 总控台</h1>
        <p className="text-muted-foreground">监控和管理 PM Agent 运行状态</p>
      </div>

      {/* Status Card */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Shield className="h-6 w-6 text-primary" />
              <div>
                <CardTitle>PM Agent 状态</CardTitle>
                <CardDescription>自主巡检引擎</CardDescription>
              </div>
            </div>
            {!isLoading && (
              <Badge
                variant={isRunning ? "success" : isPaused ? "warning" : "destructive"}
                className="text-sm"
              >
                {isRunning ? "运行中" : isPaused ? "已暂停" : "已停止"}
              </Badge>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex gap-3">
            <Button
              variant="outline"
              size="sm"
              onClick={() => resumeMutation.mutate()}
              disabled={isRunning || resumeMutation.isPending}
            >
              <Play className="mr-1 h-4 w-4" />
              启动/恢复
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => pauseMutation.mutate()}
              disabled={!isRunning || pauseMutation.isPending}
            >
              <Pause className="mr-1 h-4 w-4" />
              暂停
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => killMutation.mutate()}
              disabled={isStopped || killMutation.isPending}
            >
              <Square className="mr-1 h-4 w-4" />
              停止
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Info Cards */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>最近巡检</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm text-muted-foreground">
                {status?.killed_at
                  ? new Date(status.killed_at).toLocaleString("zh-CN")
                  : "暂无数据"}
              </span>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>暂停时间</CardDescription>
          </CardHeader>
          <CardContent>
            <span className="text-sm text-muted-foreground">
              {status?.paused_at
                ? new Date(status.paused_at).toLocaleString("zh-CN")
                : "未暂停"}
            </span>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>停止时间</CardDescription>
          </CardHeader>
          <CardContent>
            <span className="text-sm text-muted-foreground">
              {status?.killed_at
                ? new Date(status.killed_at).toLocaleString("zh-CN")
                : "未停止"}
            </span>
          </CardContent>
        </Card>
      </div>

      {/* Token Usage */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Coins className="h-5 w-5 text-yellow-400" />
            Token 用量（7 天）
          </CardTitle>
          <CardDescription>总消耗: {totalTokens.toLocaleString()} tokens</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2">
            {/* By Feature */}
            <div>
              <p className="text-sm font-medium mb-2">按功能分布</p>
              {Object.keys(byFeature).length > 0 ? (
                <div className="space-y-1">
                  {Object.entries(byFeature).map(([feature, tokens]) => (
                    <div key={feature} className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">{feature}</span>
                      <Badge variant="outline">{(tokens as number).toLocaleString()}</Badge>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">暂无数据</p>
              )}
            </div>
            {/* By Model */}
            <div>
              <p className="text-sm font-medium mb-2">按模型分布</p>
              {Object.keys(byModel).length > 0 ? (
                <div className="space-y-1">
                  {Object.entries(byModel).map(([model, tokens]) => (
                    <div key={model} className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground truncate max-w-[150px]">{model}</span>
                      <Badge variant="outline">{(tokens as number).toLocaleString()}</Badge>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">暂无数据</p>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Project Health Grid */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Heart className="h-5 w-5 text-red-400" />
            项目健康网格
          </CardTitle>
          <CardDescription>每个项目的健康状态概览</CardDescription>
        </CardHeader>
        <CardContent>
          {projects.length === 0 ? (
            <p className="text-center text-muted-foreground py-4">暂无项目</p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {projects.map((project) => (
                <Link key={project.id} href={`/projects/${project.id}/pm`}>
                  <div className={cn(
                    "rounded-lg border p-4 cursor-pointer transition-colors hover:shadow-md",
                  )}>
                    <div className="flex items-center justify-between mb-2">
                      <p className="font-medium text-sm truncate">{project.title}</p>
                      <Badge variant={project.status === "active" ? "success" : "outline"} className="text-xs">
                        {project.status === "active" ? "进行中" : project.status}
                      </Badge>
                    </div>
                    <div className="flex items-center gap-4 text-xs text-muted-foreground">
                      <span>{project.genre === "comic" ? "漫剧" : "小说"}</span>
                      <span>{project.current_words?.toLocaleString() || 0} 字</span>
                      {project.chapter_count ? <span>{project.chapter_count} 章</span> : null}
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* PM Inspection Stats from health */}
      {status?.health && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <RefreshCw className="h-5 w-5 text-primary" />
              巡检统计
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {Object.entries(status.health as Record<string, unknown>).map(([key, value]) => (
                <div key={key} className="text-center">
                  <p className="text-2xl font-bold">{String(value)}</p>
                  <p className="text-xs text-muted-foreground">{key}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
