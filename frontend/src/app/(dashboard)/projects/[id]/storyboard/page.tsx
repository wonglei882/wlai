"use client"

import { use, useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  Film, RefreshCw, Loader2, Eye, RotateCcw, CheckCircle2,
  ChevronDown, ChevronUp, AlertCircle, Zap, Play, X,
} from "lucide-react"
import { cn } from "@/lib/utils"
import Link from "next/link"
import { ArrowLeft } from "lucide-react"

const STATUS_LABELS: Record<string, string> = {
  pending_script: "待脚本",
  pending_image: "待出图",
  pending_review_image: "待审核",
  pending_video: "待视频",
  pending_voice: "待配音",
  pending_composite: "待合成",
  completed: "已完成",
}

const STATUS_COLORS: Record<string, string> = {
  pending_script: "bg-gray-100 text-gray-700 border-gray-300",
  pending_image: "bg-blue-50 text-blue-700 border-blue-300",
  pending_review_image: "bg-yellow-50 text-yellow-700 border-yellow-300",
  pending_video: "bg-purple-50 text-purple-700 border-purple-300",
  pending_voice: "bg-indigo-50 text-indigo-700 border-indigo-300",
  pending_composite: "bg-orange-50 text-orange-700 border-orange-300",
  completed: "bg-green-50 text-green-700 border-green-300",
}

// 状态机下一步映射
const NEXT_STATUS: Record<string, string> = {
  pending_script: "pending_image",
  pending_image: "pending_review_image",
  pending_review_image: "pending_video",
  pending_video: "pending_voice",
  pending_voice: "pending_composite",
  pending_composite: "completed",
}

const NEXT_LABELS: Record<string, string> = {
  pending_script: "进入出图",
  pending_image: "提交审核",
  pending_review_image: "审核通过",
  pending_video: "开始视频",
  pending_voice: "开始配音",
  pending_composite: "开始合成",
}

function ConsistencyScore({ score }: { score: number | null }) {
  if (score == null) return null
  const color =
    score >= 0.9 ? "text-green-600 bg-green-50 border-green-300"
    : score >= 0.7 ? "text-yellow-600 bg-yellow-50 border-yellow-300"
    : "text-red-600 bg-red-50 border-red-300"
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium", color)}>
      <Eye className="h-3 w-3" />
      {(score * 100).toFixed(0)}%
    </span>
  )
}

function RetryBadge({ count }: { count: number }) {
  if (!count) return null
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-orange-100 text-orange-700 border border-orange-300 px-2 py-0.5 text-xs font-medium">
      <RotateCcw className="h-3 w-3" />
      重试 x{count}
    </span>
  )
}

export default function ShotStoryboardPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: projectId } = use(params)
  const queryClient = useQueryClient()
  const [expandedShot, setExpandedShot] = useState<string | null>(null)
  const [promptDialog, setPromptDialog] = useState<{ shotId: string; prompt: string } | null>(null)
  const [selectedShots, setSelectedShots] = useState<Set<string>>(new Set())

  // Fetch all shots for this project
  const { data: shotsData, isLoading } = useQuery({
    queryKey: ["project-shots", projectId],
    queryFn: () => api.getShotsByProject(projectId),
  })

  // Fetch reviews
  const { data: reviewsData } = useQuery({
    queryKey: ["project-reviews", projectId],
    queryFn: () => api.getReviews(projectId),
  })

  const shots = (shotsData?.shots ?? []) as Record<string, unknown>[]
  const reviews = (reviewsData?.reviews ?? []) as Record<string, unknown>[]

  // Mutations
  const retryMutation = useMutation({
    mutationFn: (shotId: string) => api.updateShotStatus(shotId, "pending_image"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["project-shots", projectId] }),
  })

  const forcePassMutation = useMutation({
    mutationFn: (shotId: string) => api.updateShotStatus(shotId, "pending_video"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["project-shots", projectId] }),
  })

  const reviewPassMutation = useMutation({
    mutationFn: ({ reviewId, notes }: { reviewId: string; notes?: string }) =>
      api.updateReview(reviewId, "approved", notes),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["project-reviews", projectId] }),
  })

  // 编译提示词
  const compileMutation = useMutation({
    mutationFn: (shotId: string) => api.compileShotPrompt(shotId),
    onSuccess: (data, shotId) => {
      queryClient.invalidateQueries({ queryKey: ["project-shots", projectId] })
      const prompt = (data.compiled_prompt as string) || "编译完成，请刷新查看详情"
      setPromptDialog({ shotId, prompt })
    },
  })

  // 状态流转
  const advanceMutation = useMutation({
    mutationFn: ({ shotId, targetStatus }: { shotId: string; targetStatus: string }) =>
      api.updateShotStatus(shotId, targetStatus),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["project-shots", projectId] }),
  })

  // 批量编译
  const batchCompile = () => {
    selectedShots.forEach(shotId => compileMutation.mutate(shotId))
    setSelectedShots(new Set())
  }

  // Stats
  const totalShots = shots.length
  const retryingShots = shots.filter(s => ((s.retry_count as number) || 0) > 0).length
  const lowScoreShots = shots.filter(s => {
    const score = s.last_consistency_score as number | null
    return score != null && score < 0.7
  }).length
  const pendingReviewShots = shots.filter(s => s.status === "pending_review_image").length

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
        <span className="text-foreground">镜头工作台</span>
      </div>

      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold flex items-center gap-3">
          <Film className="h-8 w-8 text-primary" />
          镜头状态可视化
        </h1>
        <p className="text-muted-foreground mt-1">视觉重试状态、一致性评分与审核交互</p>
      </div>

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>总镜头数</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{totalShots}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>待审核</CardDescription>
          </CardHeader>
          <CardContent>
            <p className={cn("text-2xl font-bold", pendingReviewShots > 0 ? "text-yellow-400" : "")}>
              {pendingReviewShots}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>重试中</CardDescription>
          </CardHeader>
          <CardContent>
            <p className={cn("text-2xl font-bold", retryingShots > 0 ? "text-orange-400" : "")}>
              {retryingShots}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>低一致性</CardDescription>
          </CardHeader>
          <CardContent>
            <p className={cn("text-2xl font-bold", lowScoreShots > 0 ? "text-red-400" : "")}>
              {lowScoreShots}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Batch Operations */}
      {selectedShots.size > 0 && (
        <Card className="border-primary/30 bg-primary/5">
          <CardContent className="py-3 flex items-center justify-between">
            <p className="text-sm">已选择 {selectedShots.size} 个镜头</p>
            <div className="flex gap-2">
              <Button size="sm" onClick={batchCompile} disabled={compileMutation.isPending}>
                <Zap className="mr-1 h-3 w-3" /> 批量编译
              </Button>
              <Button size="sm" variant="outline" onClick={() => setSelectedShots(new Set())}>
                取消选择
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Shot Cards */}
      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      ) : shots.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            暂无镜头数据。请先在分镜工作台中生成分镜。
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {shots.map((shot) => {
            const shotId = shot.id as string
            const shotNumber = shot.shot_number as number
            const status = shot.status as string
            const retryCount = (shot.retry_count as number) || 0
            const consistencyScore = shot.last_consistency_score as number | null
            const correctedPrompt = shot.corrected_prompt as string | null
            const visualDesc = shot.visual_description as string
            const isExpanded = expandedShot === shotId
            const isPendingReview = status === "pending_review_image"
            const relatedReview = reviews.find(r => r.target_id === shotId)

            return (
              <Card
                key={shotId}
                className={cn(
                  "cursor-pointer transition-all hover:shadow-md",
                  consistencyScore != null && consistencyScore < 0.7 && "border-red-300",
                  consistencyScore != null && consistencyScore >= 0.9 && "border-green-300",
                  retryCount > 0 && "border-orange-200",
                  selectedShots.has(shotId) && "ring-2 ring-primary",
                )}
                onClick={() => setExpandedShot(isExpanded ? null : shotId)}
              >
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={selectedShots.has(shotId)}
                        onChange={(e) => {
                          e.stopPropagation()
                          const next = new Set(selectedShots)
                          next.has(shotId) ? next.delete(shotId) : next.add(shotId)
                          setSelectedShots(next)
                        }}
                        onClick={(e) => e.stopPropagation()}
                        className="h-4 w-4 rounded border-gray-300"
                      />
                      <CardTitle className="text-sm">
                        镜头 #{shotNumber}
                      </CardTitle>
                    </div>
                    <div className="flex items-center gap-1">
                      <RetryBadge count={retryCount} />
                      <ConsistencyScore score={consistencyScore} />
                    </div>
                  </div>
                  <div className="flex items-center gap-2 mt-1">
                    <span className={cn(
                      "rounded-full border px-2 py-0.5 text-xs font-medium",
                      STATUS_COLORS[status] || "bg-gray-50 text-gray-700 border-gray-300"
                    )}>
                      {STATUS_LABELS[status] || status}
                    </span>
                  </div>
                </CardHeader>
                <CardContent className="pb-3">
                  {/* Visual Description */}
                  {visualDesc && (
                    <p className="text-xs text-muted-foreground line-clamp-2 mb-2">
                      {visualDesc}
                    </p>
                  )}

                  {/* Corrected Prompt Indicator */}
                  {correctedPrompt && (
                    <div className="rounded-md bg-orange-50 dark:bg-orange-950/20 border border-orange-200 p-2 mb-2">
                      <p className="text-xs text-orange-700 dark:text-orange-400 flex items-center gap-1">
                        <AlertCircle className="h-3 w-3 shrink-0" />
                        <span className="font-medium">已注入修正提示词</span>
                      </p>
                      <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                        {correctedPrompt}
                      </p>
                    </div>
                  )}

                  {/* Production Actions */}
                  {status !== "completed" && (
                    <div className="flex gap-2 border-t pt-2 mt-2">
                      <Button
                        size="sm"
                        variant="outline"
                        className="text-xs flex-1"
                        onClick={(e) => { e.stopPropagation(); compileMutation.mutate(shotId) }}
                        disabled={compileMutation.isPending}
                      >
                        <Zap className="mr-1 h-3 w-3" />
                        编译提示词
                      </Button>
                      {NEXT_STATUS[status] && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="text-xs flex-1 text-primary"
                          onClick={(e) => {
                            e.stopPropagation()
                            advanceMutation.mutate({ shotId, targetStatus: NEXT_STATUS[status] })
                          }}
                          disabled={advanceMutation.isPending}
                        >
                          <Play className="mr-1 h-3 w-3" />
                          {NEXT_LABELS[status]}
                        </Button>
                      )}
                    </div>
                  )}

                  {/* C.2: Review Actions for pending_review_image */}
                  {isPendingReview && (
                    <div className="space-y-2 border-t pt-2 mt-2">
                      {/* Auto-retry info */}
                      {retryCount > 0 && (
                        <p className="text-xs text-muted-foreground">
                          已自动重试 {retryCount} 次
                          {consistencyScore != null && `，当前评分 ${(consistencyScore * 100).toFixed(0)}%`}
                        </p>
                      )}

                      {/* Review actions */}
                      <div className="flex gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          className="text-xs flex-1"
                          onClick={(e) => { e.stopPropagation(); retryMutation.mutate(shotId) }}
                          disabled={retryMutation.isPending}
                        >
                          <RotateCcw className="mr-1 h-3 w-3" />
                          手动重试
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          className="text-xs flex-1 text-green-600 border-green-300 hover:bg-green-50"
                          onClick={(e) => { e.stopPropagation(); forcePassMutation.mutate(shotId) }}
                          disabled={forcePassMutation.isPending}
                        >
                          <CheckCircle2 className="mr-1 h-3 w-3" />
                          强制通过
                        </Button>
                      </div>

                      {/* Review checkpoint actions */}
                      {relatedReview && (
                        <div className="border-t pt-2">
                          <p className="text-xs text-muted-foreground mb-1">审核检查点</p>
                          <Button
                            size="sm"
                            variant="outline"
                            className="text-xs w-full"
                            onClick={(e) => {
                              e.stopPropagation()
                              reviewPassMutation.mutate({ reviewId: relatedReview.id as string })
                            }}
                            disabled={reviewPassMutation.isPending}
                          >
                            <CheckCircle2 className="mr-1 h-3 w-3" />
                            审核通过
                          </Button>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Expanded Detail */}
                  {isExpanded && (
                    <div className="border-t pt-2 mt-2 space-y-2">
                      <div className="text-xs">
                        <span className="font-medium">ID:</span>{" "}
                        <span className="text-muted-foreground font-mono">{shotId.slice(0, 8)}</span>
                      </div>
                      {(shot.compiled_prompt as string) && (
                        <div>
                          <p className="text-xs font-medium">编译提示词</p>
                          <p className="text-xs text-muted-foreground line-clamp-3">
                            {shot.compiled_prompt as string}
                          </p>
                        </div>
                      )}
                      {shot.seed != null && (
                        <div className="text-xs">
                          <span className="font-medium">Seed:</span>{" "}
                          <span className="text-muted-foreground">{String(shot.seed)}</span>
                        </div>
                      )}
                      {(shot.camera_movement as string) && (
                        <div className="text-xs">
                          <span className="font-medium">镜头运动:</span>{" "}
                          <span className="text-muted-foreground">{String(shot.camera_movement)}</span>
                        </div>
                      )}
                    </div>
                  )}
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      {/* Navigation */}
      <div className="flex gap-4">
        <Link href={`/projects/${projectId}/pm`}>
          <Button variant="outline">
            <ArrowLeft className="mr-2 h-4 w-4" />
            返回 PM 诊断
          </Button>
        </Link>
      </div>

      {/* Prompt Dialog */}
      {promptDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setPromptDialog(null)}>
          <Card className="w-full max-w-lg mx-4" onClick={(e) => e.stopPropagation()}>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">编译提示词</CardTitle>
                <Button variant="ghost" size="sm" onClick={() => setPromptDialog(null)}>
                  <X className="h-4 w-4" />
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <pre className="rounded-md bg-muted p-4 text-xs whitespace-pre-wrap font-mono max-h-64 overflow-auto">
                {promptDialog.prompt}
              </pre>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
