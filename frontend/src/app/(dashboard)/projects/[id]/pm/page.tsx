"use client"

import { use, useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { useAuthStore } from "@/store/auth-store"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Shield, Activity, AlertTriangle, CheckCircle2, XCircle, Loader2,
  Zap, RefreshCw, ThumbsUp, ThumbsDown, ChevronDown, ChevronUp,
} from "lucide-react"
import { cn } from "@/lib/utils"
import Link from "next/link"
import { ArrowLeft } from "lucide-react"
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts"
import { AutonomyAdjuster } from "@/components/pm/autonomy-adjuster"

export default function ProjectPMDashboard({ params }: { params: Promise<{ id: string }> }) {
  const { id: projectId } = use(params)
  const { user } = useAuthStore()
  const userId = user?.id || "system"
  const queryClient = useQueryClient()
  const [expandedLog, setExpandedLog] = useState<string | null>(null)

  // ---- 数据查询 ----
  const { data: dashboard, isLoading: dashLoading } = useQuery({
    queryKey: ["pm-dashboard", projectId],
    queryFn: () => api.getPMDashboard(projectId, userId),
    refetchInterval: 60000,
  })

  const { data: summary } = useQuery({
    queryKey: ["pm-diag-summary", projectId],
    queryFn: () => api.getDiagnosticSummary(projectId),
  })

  const { data: logs } = useQuery({
    queryKey: ["pm-diag-logs", projectId],
    queryFn: () => api.getDiagnosticLogs(projectId, 30),
  })

  const { data: fixReport } = useQuery({
    queryKey: ["pm-fix-report", projectId],
    queryFn: () => api.getFixReport(projectId),
  })

  const { data: suggestions } = useQuery({
    queryKey: ["pm-suggestions", projectId],
    queryFn: () => api.getSuggestions(projectId, userId),
  })

  // ---- 操作 ----
  const inspectMutation = useMutation({
    mutationFn: () => api.inspectProject(projectId, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pm-dashboard", projectId] })
      queryClient.invalidateQueries({ queryKey: ["pm-diag-summary", projectId] })
      queryClient.invalidateQueries({ queryKey: ["pm-diag-logs", projectId] })
    },
  })

  const feedbackMutation = useMutation({
    mutationFn: ({ logId, action, note }: { logId: string; action: string; note?: string }) =>
      api.submitFixFeedback(logId, action, note),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["pm-fix-report", projectId] }),
  })

  const resolveMutation = useMutation({
    mutationFn: (logId: string) => api.resolveDiagnostic(logId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pm-diag-logs", projectId] })
      queryClient.invalidateQueries({ queryKey: ["pm-diag-summary", projectId] })
    },
  })

  const healthScore = (dashboard?.health_score as number) ?? 0
  const healthLevel = dashboard?.health_level as string ?? "未知"
  const issues = (dashboard?.issues as Record<string, unknown>[]) ?? []
  const warnings = (dashboard?.warnings as Record<string, unknown>[]) ?? []
  const trend = (summary?.trend as { date: string; created: number; resolved: number }[]) ?? []
  const unresolvedTotal = (summary?.unresolved_total as number) ?? 0
  const criticalCount = (summary?.critical_count as number) ?? 0

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Link href={`/projects/${projectId}`} className="flex items-center gap-1 hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
          项目详情
        </Link>
        <span>/</span>
        <span className="text-foreground">PM 诊断面板</span>
      </div>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-3">
            <Shield className="h-8 w-8 text-primary" />
            PM Agent 诊断面板
          </h1>
          <p className="text-muted-foreground mt-1">项目健康状态、诊断日志与修复闭环</p>
        </div>
        <Button
          onClick={() => inspectMutation.mutate()}
          disabled={inspectMutation.isPending}
        >
          {inspectMutation.isPending ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="mr-2 h-4 w-4" />
          )}
          一键巡检
        </Button>
      </div>

      {/* Health Score + Stats */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card className="md:col-span-1">
          <CardHeader className="pb-2">
            <CardDescription>综合健康分</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col items-center">
              <div className={cn(
                "text-5xl font-bold",
                healthScore >= 8 ? "text-green-400" : healthScore >= 6 ? "text-yellow-400" : "text-red-400"
              )}>
                {healthScore.toFixed(1)}
              </div>
              <p className="text-sm text-muted-foreground mt-1">{healthLevel}</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>未解决问题</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">{unresolvedTotal}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>严重问题</CardDescription>
          </CardHeader>
          <CardContent>
            <p className={cn("text-3xl font-bold", criticalCount > 0 ? "text-red-400" : "")}>
              {criticalCount}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>本轮发现</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex gap-4">
              <div>
                <p className="text-2xl font-bold text-red-400">{issues.length}</p>
                <p className="text-xs text-muted-foreground">问题</p>
              </div>
              <div>
                <p className="text-2xl font-bold text-yellow-400">{warnings.length}</p>
                <p className="text-xs text-muted-foreground">警告</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Issues & Warnings */}
      {(issues.length > 0 || warnings.length > 0) && (
        <div className="grid gap-4 md:grid-cols-2">
          {issues.length > 0 && (
            <Card className="border-red-200">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-red-600">
                  <XCircle className="h-5 w-5" /> 问题
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {issues.map((issue, i) => (
                  <div key={i} className="rounded-md bg-red-50 dark:bg-red-950/20 p-3 text-sm">
                    <span className="font-medium">{issue.type as string}</span>
                    <p className="text-muted-foreground mt-1">{JSON.stringify(issue.items).slice(0, 100)}...</p>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
          {warnings.length > 0 && (
            <Card className="border-yellow-200">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-yellow-600">
                  <AlertTriangle className="h-5 w-5" /> 警告
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {warnings.map((w, i) => (
                  <div key={i} className="rounded-md bg-yellow-50 dark:bg-yellow-950/20 p-3 text-sm">
                    <span className="font-medium">{w.type as string}</span>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* 7-day Trend Chart */}
      {trend.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="h-5 w-5 text-primary" />
              7 天诊断趋势
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={trend}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="created" stroke="#ef4444" name="新增" strokeWidth={2} />
                <Line type="monotone" dataKey="resolved" stroke="#22c55e" name="已解决" strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {/* Diagnostic Logs Timeline */}
      <Card>
        <CardHeader>
          <CardTitle>诊断日志</CardTitle>
          <CardDescription>最近的诊断记录，按时间倒序</CardDescription>
        </CardHeader>
        <CardContent>
          {dashLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
            </div>
          ) : !logs?.items?.length ? (
            <p className="text-center text-muted-foreground py-8">暂无诊断记录</p>
          ) : (
            <div className="space-y-2">
              {logs.items.map((log) => (
                <div
                  key={log.id}
                  className={cn(
                    "rounded-md border p-3 cursor-pointer transition-colors hover:bg-accent/50",
                    log.severity === "critical" && "border-red-300 bg-red-50/50",
                    log.severity === "warning" && "border-yellow-300 bg-yellow-50/50",
                  )}
                  onClick={() => setExpandedLog(expandedLog === log.id ? null : log.id)}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Badge
                        variant={log.severity === "critical" ? "destructive" : log.severity === "warning" ? "warning" : "secondary"}
                        className="text-xs"
                      >
                        {log.severity}
                      </Badge>
                      <span className="text-xs text-muted-foreground">{log.diag_type}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      {log.resolved ? (
                        <Badge variant="success" className="text-xs">已解决</Badge>
                      ) : (
                        <Badge variant="outline" className="text-xs">未解决</Badge>
                      )}
                      <span className="text-xs text-muted-foreground">
                        {log.created_at ? new Date(log.created_at).toLocaleString("zh-CN") : ""}
                      </span>
                      {expandedLog === log.id ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                    </div>
                  </div>
                  <p className="text-sm mt-2">{log.message}</p>
                  {expandedLog === log.id && (
                    <div className="mt-3 space-y-2 border-t pt-3">
                      {log.suggestion && (
                        <p className="text-sm text-muted-foreground">
                          <span className="font-medium">建议：</span>{log.suggestion}
                        </p>
                      )}
                      {!log.resolved && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={(e) => { e.stopPropagation(); resolveMutation.mutate(log.id) }}
                          disabled={resolveMutation.isPending}
                        >
                          <CheckCircle2 className="mr-1 h-3 w-3" />
                          标记已解决
                        </Button>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Fix Report */}
      {fixReport && fixReport.total > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Zap className="h-5 w-5 text-primary" />
              修复报告
            </CardTitle>
            <CardDescription>最近修复结果，请审核确认</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {fixReport.items.map((item) => (
              <div key={item.id as string} className="rounded-md border p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Badge variant={item.severity === "critical" ? "destructive" : "secondary"}>
                      {item.diag_type as string}
                    </Badge>
                    <Badge variant={item.verified ? "success" : "outline"}>
                      {item.verified ? "已验证" : "待验证"}
                    </Badge>
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {item.created_at ? new Date(item.created_at as string).toLocaleString("zh-CN") : ""}
                  </span>
                </div>
                <p className="text-sm mb-2">{item.message as string}</p>
                <p className="text-sm text-muted-foreground mb-3">
                  <span className="font-medium">决策：</span>{String(item.decision)}
                  {item.fix_result ? ` | 结果：${String(item.fix_result)}` : null}
                </p>
                {item.user_feedback ? (
                  <Badge variant={item.user_feedback === "approved" ? "success" : "destructive"}>
                    {item.user_feedback === "approved" ? "已采纳" : "已驳回"}
                    {item.feedback_note ? `：${String(item.feedback_note)}` : null}
                  </Badge>
                ) : (
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      className="text-green-600 border-green-300 hover:bg-green-50"
                      onClick={() => feedbackMutation.mutate({ logId: item.id as string, action: "approve" })}
                    >
                      <ThumbsUp className="mr-1 h-3 w-3" /> 采纳
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="text-red-600 border-red-300 hover:bg-red-50"
                      onClick={() => feedbackMutation.mutate({ logId: item.id as string, action: "reject" })}
                    >
                      <ThumbsDown className="mr-1 h-3 w-3" /> 驳回
                    </Button>
                  </div>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Suggestions */}
      {suggestions && suggestions.total > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>主动建议</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {suggestions.suggestions.map((s, i) => (
              <div key={i} className="rounded-md border p-3 text-sm">
                <p className="font-medium">{s.title as string || s.type as string}</p>
                <p className="text-muted-foreground">{s.detail as string || s.message as string}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Autonomy Adjuster */}
      <AutonomyAdjuster projectId={projectId} userId={userId} />

      {/* Navigation */}
      <div className="flex gap-4">
        <Link href={`/projects/${projectId}/pm/decisions`}>
          <Button variant="outline">查看决策记录</Button>
        </Link>
      </div>
    </div>
  )
}
