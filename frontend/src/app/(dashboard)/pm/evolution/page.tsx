"use client"

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ArrowLeft, BrainCircuit, FlaskConical, ListChecks, RefreshCw, RotateCcw } from "lucide-react"
import Link from "next/link"
import { useState } from "react"
import { Skeleton, SkeletonCard, SkeletonList } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

type EvolutionState = {
  id: string
  project_id: string
  dimension: string
  signals_aggregated: number
  total_decisions: number
  hit_count: number
  fp_count: number
  fix_rate: number
  fp_rate: number
  threshold_key: string | null
  threshold_value: number | null
  threshold_original: number | null
  confidence: number
  status: string
  throttle_until: string | null
  consecutive_clean_rounds: number
  last_evolved_at: string | null
  updated_at: string | null
}

const STATUS_META: Record<string, { label: string; variant: "success" | "warning" | "destructive" | "outline" }> = {
  stable: { label: "稳定", variant: "success" },
  evolving: { label: "进化中", variant: "warning" },
  throttled: { label: "节流中", variant: "outline" },
  disabled: { label: "已禁用", variant: "destructive" },
}

export default function PMEvolutionPage() {
  const queryClient = useQueryClient()
  const [projectId, setProjectId] = useState("")

  const { data: overview, isLoading } = useQuery({
    queryKey: ["pm-evolution", projectId],
    queryFn: () => api.getEvolutionOverview(projectId || undefined),
    refetchInterval: 15000,
  })

  const { data: eventsData } = useQuery({
    queryKey: ["pm-evolution-events"],
    queryFn: () => api.getEvolutionEvents(30),
    refetchInterval: 30000,
  })

  const { data: rulesData } = useQuery({
    queryKey: ["pm-evolution-rules", projectId],
    queryFn: () => api.getEvolutionRules(projectId || undefined),
    refetchInterval: 30000,
  })

  const { data: projectsData } = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.getProjects(),
  })
  const projects = projectsData?.projects || []

  const triggerMutation = useMutation({
    mutationFn: () => api.triggerEvolution(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pm-evolution"] })
      queryClient.invalidateQueries({ queryKey: ["pm-evolution-events"] })
    },
  })

  const resetMutation = useMutation({
    mutationFn: () => api.resetProjectEvolution(projectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pm-evolution"] })
      queryClient.invalidateQueries({ queryKey: ["pm-evolution-events"] })
      queryClient.invalidateQueries({ queryKey: ["pm-evolution-rules"] })
    },
  })

  const states: EvolutionState[] = (overview?.states as EvolutionState[]) || []
  const enabled = Boolean(overview?.enabled)
  const ruleCount = (overview?.rule_count as number) ?? 0
  const eventCount = (overview?.event_count as number) ?? 0
  const events = (eventsData?.items as Record<string, unknown>[]) || []
  const rules = (rulesData?.items as Record<string, unknown>[]) || []

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div>
          <Skeleton className="h-8 w-56 mb-2" />
          <Skeleton className="h-4 w-72" />
        </div>
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonList rows={4} />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <BrainCircuit className="h-7 w-7 text-primary" />
            PM 自进化
          </h1>
          <p className="text-muted-foreground mt-1">信号聚合 → 阈值进化 → 规则生长的三层闭环</p>
        </div>
        <Link href="/pm">
          <Button variant="outline" size="sm">
            <ArrowLeft className="mr-1 h-4 w-4" />
            返回总控台
          </Button>
        </Link>
      </div>

      {/* 状态卡 */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>自进化开关</CardDescription>
          </CardHeader>
          <CardContent>
            <Badge variant={enabled ? "success" : "destructive"}>
              {enabled ? "已启用" : "未启用"}
            </Badge>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>维度状态</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{states.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>排除规则</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{ruleCount}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>进化事件</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{eventCount}</p>
          </CardContent>
        </Card>
      </div>

      {/* 操作区 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FlaskConical className="h-5 w-5 text-primary" />
            操作
          </CardTitle>
          <CardDescription>手动触发一轮进化 / 重置指定项目的进化状态</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          <Button
            size="sm"
            onClick={() => triggerMutation.mutate()}
            disabled={!enabled || triggerMutation.isPending}
          >
            <RefreshCw className="mr-1 h-4 w-4" />
            {triggerMutation.isPending ? "执行中..." : "立即进化一轮"}
          </Button>
          <select
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            className="rounded-md border bg-background px-3 py-1.5 text-sm"
          >
            <option value="">全部项目</option>
            {projects.map((p: { id: string; title: string }) => (
              <option key={p.id} value={p.id}>
                {p.title}
              </option>
            ))}
          </select>
          <Button
            variant="destructive"
            size="sm"
            onClick={() => resetMutation.mutate()}
            disabled={!projectId || resetMutation.isPending}
          >
            <RotateCcw className="mr-1 h-4 w-4" />
            重置选中项目
          </Button>
        </CardContent>
      </Card>

      {/* 维度状态表 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BrainCircuit className="h-5 w-5 text-primary" />
            维度进化状态
          </CardTitle>
          <CardDescription>每 (项目, 维度) 的信号聚合与运行时阈值</CardDescription>
        </CardHeader>
        <CardContent>
          {states.length === 0 ? (
            <p className="text-center text-muted-foreground py-6">
              暂无进化数据 — 巡检运行几轮后，各维度将自动聚合信号
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="py-2 pr-3 font-medium">项目</th>
                    <th className="py-2 pr-3 font-medium">维度</th>
                    <th className="py-2 pr-3 font-medium">状态</th>
                    <th className="py-2 pr-3 font-medium">修复率</th>
                    <th className="py-2 pr-3 font-medium">误报率</th>
                    <th className="py-2 pr-3 font-medium">运行时阈值</th>
                    <th className="py-2 pr-3 font-medium">默认值</th>
                    <th className="py-2 pr-3 font-medium">置信度</th>
                    <th className="py-2 pr-3 font-medium">干净轮数</th>
                  </tr>
                </thead>
                <tbody>
                  {states.map((s) => {
                    const meta = STATUS_META[s.status] || STATUS_META.stable
                    return (
                      <tr key={s.id} className="border-b">
                        <td className="py-2 pr-3 font-mono text-xs text-muted-foreground">
                          {s.project_id.slice(0, 8)}
                        </td>
                        <td className="py-2 pr-3 font-medium">{s.dimension}</td>
                        <td className="py-2 pr-3">
                          <Badge variant={meta.variant} className="text-xs">
                            {meta.label}
                          </Badge>
                          {s.throttle_until ? (
                            <p className="text-xs text-muted-foreground mt-0.5">
                              至 {new Date(s.throttle_until).toLocaleString("zh-CN")}
                            </p>
                          ) : null}
                        </td>
                        <td className="py-2 pr-3">
                          <span className={cn(s.fix_rate < 0.4 && "text-destructive")}>
                            {(s.fix_rate * 100).toFixed(0)}%
                          </span>
                        </td>
                        <td className="py-2 pr-3">
                          <span className={cn(s.fp_rate > 0.5 && "text-destructive")}>
                            {(s.fp_rate * 100).toFixed(0)}%
                          </span>
                        </td>
                        <td className="py-2 pr-3 font-mono">
                          {s.threshold_value ?? "—"}
                          {s.threshold_key ? (
                            <span className="text-xs text-muted-foreground ml-1">
                              ({s.threshold_key})
                            </span>
                          ) : null}
                        </td>
                        <td className="py-2 pr-3 font-mono text-muted-foreground">
                          {s.threshold_original ?? "—"}
                        </td>
                        <td className="py-2 pr-3">
                          <div className="flex items-center gap-1.5">
                            <div className="h-1.5 w-12 rounded-full bg-muted">
                              <div
                                className="h-full rounded-full bg-primary"
                                style={{ width: `${Math.round((s.confidence ?? 0) * 100)}%` }}
                              />
                            </div>
                            <span className="text-xs text-muted-foreground">
                              {(s.confidence * 100).toFixed(0)}%
                            </span>
                          </div>
                        </td>
                        <td className="py-2 pr-3">{s.consecutive_clean_rounds}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* 事件日志 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ListChecks className="h-5 w-5 text-primary" />
            进化事件（最近 30 条）
          </CardTitle>
        </CardHeader>
        <CardContent>
          {events.length === 0 ? (
            <p className="text-center text-muted-foreground py-4">暂无事件</p>
          ) : (
            <div className="space-y-2">
              {events.map((ev) => (
                <div
                  key={String(ev.id)}
                  className="flex items-start gap-3 rounded-md border p-2.5 text-sm"
                >
                  <Badge variant="outline" className="mt-0.5 shrink-0 text-xs">
                    {String(ev.event_type)}
                  </Badge>
                  <div className="min-w-0">
                    <p className="truncate font-mono text-xs text-muted-foreground">
                      {String(ev.detail || "")}
                    </p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {ev.dimension ? String(ev.dimension) : "全局"} ·{" "}
                      {ev.created_at
                        ? new Date(String(ev.created_at)).toLocaleString("zh-CN")
                        : ""}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 排除规则 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BrainCircuit className="h-5 w-5 text-primary" />
            排除规则（用户驳回学习）
          </CardTitle>
          <CardDescription>巡检时自动过滤这些噪声，命中即跳过同类问题</CardDescription>
        </CardHeader>
        <CardContent>
          {rules.length === 0 ? (
            <p className="text-center text-muted-foreground py-4">
              暂无规则 — 在决策记录中驳回误报后自动生成
            </p>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {rules.map((r) => (
                <div key={String(r.id)} className="rounded-md border p-3 text-sm">
                  <div className="flex items-center justify-between">
                    <Badge variant="outline" className="text-xs">
                      {String(r.rule_type)}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      命中 {String(r.hits ?? 0)} 次
                    </span>
                  </div>
                  <p className="mt-2 font-mono text-xs truncate">{String(r.rule_key)}</p>
                  <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                    {String(r.reason || "")}
                  </p>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
