"use client"

import { use, useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import {
  ThumbsUp, ThumbsDown, Loader2, ArrowLeft, CheckCircle2, XCircle,
} from "lucide-react"
import { cn } from "@/lib/utils"
import Link from "next/link"

export default function DecisionsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: projectId } = use(params)
  const queryClient = useQueryClient()
  const [feedbackId, setFeedbackId] = useState<string | null>(null)
  const [feedbackNote, setFeedbackNote] = useState("")

  const { data, isLoading } = useQuery({
    queryKey: ["pm-decisions", projectId],
    queryFn: () => api.getDecisions(projectId, 50),
  })

  const feedbackMutation = useMutation({
    mutationFn: ({ id, feedback, comment }: { id: string; feedback: string; comment?: string }) =>
      api.submitDecisionFeedback(id, feedback, comment),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pm-decisions", projectId] })
      setFeedbackId(null)
      setFeedbackNote("")
    },
  })

  const decisions = data?.decisions || []

  // 统计
  const total = decisions.length
  const autoFixed = decisions.filter(d => d.decision === "auto_fix").length
  const verified = decisions.filter(d => d.verified).length
  const rejected = decisions.filter(d => d.user_feedback === "rejected").length

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Link href={`/projects/${projectId}/pm`} className="flex items-center gap-1 hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
          PM 诊断面板
        </Link>
        <span>/</span>
        <span className="text-foreground">决策记录</span>
      </div>

      <div>
        <h1 className="text-3xl font-bold">决策记录</h1>
        <p className="text-muted-foreground">PM Agent 的诊断决策与修复历史</p>
      </div>

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2"><CardDescription>总决策数</CardDescription></CardHeader>
          <CardContent><p className="text-2xl font-bold">{total}</p></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardDescription>自动修复</CardDescription></CardHeader>
          <CardContent><p className="text-2xl font-bold text-blue-400">{autoFixed}</p></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardDescription>验证通过</CardDescription></CardHeader>
          <CardContent><p className="text-2xl font-bold text-green-400">{verified}</p></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardDescription>用户驳回</CardDescription></CardHeader>
          <CardContent><p className="text-2xl font-bold text-red-400">{rejected}</p></CardContent>
        </Card>
      </div>

      {/* Decision Table */}
      <Card>
        <CardHeader>
          <CardTitle>决策列表</CardTitle>
          <CardDescription>最近 50 条决策记录</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
            </div>
          ) : !decisions.length ? (
            <p className="text-center text-muted-foreground py-8">暂无决策记录</p>
          ) : (
            <div className="space-y-3">
              {decisions.map((d) => (
                <div key={d.id} className="rounded-md border p-4">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge
                        variant={d.severity === "critical" ? "destructive" : d.severity === "warning" ? "warning" : "secondary"}
                      >
                        {d.severity}
                      </Badge>
                      <Badge variant="outline">{d.diag_type}</Badge>
                      <Badge variant={d.decision === "auto_fix" ? "default" : "outline"}>
                        {d.decision === "auto_fix" ? "自动修复" : d.decision === "manual" ? "人工处理" : d.decision}
                      </Badge>
                      {d.verified && <Badge variant="success"><CheckCircle2 className="mr-1 h-3 w-3" />已验证</Badge>}
                      {d.user_feedback === "rejected" && (
                        <Badge variant="destructive"><XCircle className="mr-1 h-3 w-3" />已驳回</Badge>
                      )}
                      {d.user_feedback === "approved" && (
                        <Badge variant="success">已采纳</Badge>
                      )}
                    </div>
                    <span className="text-xs text-muted-foreground shrink-0">
                      {d.created_at ? new Date(d.created_at).toLocaleString("zh-CN") : ""}
                    </span>
                  </div>

                  <p className="text-sm mb-1">{d.original_message}</p>
                  {d.decision_reason && (
                    <p className="text-sm text-muted-foreground">
                      <span className="font-medium">决策理由：</span>{d.decision_reason}
                    </p>
                  )}
                  {d.fix_result && (
                    <p className="text-sm text-muted-foreground">
                      <span className="font-medium">修复结果：</span>
                      <span className={cn(
                        d.fix_result === "success" || d.fix_result === "verified" ? "text-green-600" : "text-red-600"
                      )}>{d.fix_result}</span>
                    </p>
                  )}

                  {/* Feedback */}
                  {!d.user_feedback && (
                    <div className="mt-3 pt-3 border-t">
                      {feedbackId === d.id ? (
                        <div className="space-y-2">
                          <Label>备注（可选）</Label>
                          <Textarea
                            placeholder="说明理由..."
                            value={feedbackNote}
                            onChange={(e) => setFeedbackNote(e.target.value)}
                            rows={2}
                          />
                          <div className="flex gap-2">
                            <Button
                              size="sm"
                              className="bg-green-600 hover:bg-green-700"
                              onClick={() => feedbackMutation.mutate({ id: d.id, feedback: "approved", comment: feedbackNote })}
                              disabled={feedbackMutation.isPending}
                            >
                              <ThumbsUp className="mr-1 h-3 w-3" /> 采纳
                            </Button>
                            <Button
                              size="sm"
                              variant="destructive"
                              onClick={() => feedbackMutation.mutate({ id: d.id, feedback: "rejected", comment: feedbackNote })}
                              disabled={feedbackMutation.isPending}
                            >
                              <ThumbsDown className="mr-1 h-3 w-3" /> 驳回
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => setFeedbackId(null)}>
                              取消
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setFeedbackId(d.id)}
                        >
                          提交反馈
                        </Button>
                      )}
                    </div>
                  )}
                  {d.feedback_note && (
                    <p className="text-xs text-muted-foreground mt-2 italic">
                      备注：{d.feedback_note}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
