"use client"

import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import {
  ShieldAlert, ShieldCheck, Loader2, AlertTriangle, CheckCircle2, XCircle, ThumbsUp, ThumbsDown,
} from "lucide-react"
import { cn } from "@/lib/utils"
import type { AuditIssue, PMDecisionDetail } from "@/types"

interface AuditPanelProps {
  decisionId: string
  /** 列表页面的 audit 摘要（可快速预渲染 score/红线徽章） */
  summary?: PMDecisionDetail["audit"]
  /** 是否已提交过反馈（已采纳/已驳回则隐藏反馈按钮） */
  alreadyFeedback?: boolean
}

const SCORE_VARIANT: Record<string, "success" | "secondary" | "warning" | "destructive"> = {
  A: "success",
  B: "secondary",
  C: "warning",
  D: "destructive",
}

/** 监督层审核面板 — 展示 VerifySupervisor 的 AuditReport + 用户采纳/驳回确认 */
export function AuditPanel({ decisionId, summary, alreadyFeedback }: AuditPanelProps) {
  const queryClient = useQueryClient()
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const [feedbackNote, setFeedbackNote] = useState("")

  const { data: detail, isLoading } = useQuery({
    queryKey: ["pm-decision-detail", decisionId],
    queryFn: () => api.getDecisionDetail(decisionId),
    // 展开即加载完整详情（含 audit_report 的完整 issues），摘要仅作回退展示
  })

  const feedbackMutation = useMutation({
    mutationFn: ({ feedback, comment }: { feedback: string; comment?: string }) =>
      api.submitDecisionFeedback(decisionId, feedback, comment),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pm-decisions"] })
      queryClient.invalidateQueries({ queryKey: ["pm-decision-detail", decisionId] })
      setFeedbackOpen(false)
      setFeedbackNote("")
    },
  })

  // 数据源：优先完整详情里的 audit_report，回退为列表摘要
  const audit = detail?.audit_report ?? null
  const hasAudit = Boolean(audit)
  const score = audit?.score ?? summary?.score ?? null
  const issues: AuditIssue[] = audit?.issues ?? []

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        加载监督层审核报告...
      </div>
    )
  }

  // 无任何审核数据：显示占位说明（历史记录或未启用监督层审核）
  if (!hasAudit && !summary) {
    return (
      <div className="flex items-center gap-2 py-2 text-sm text-muted-foreground">
        <ShieldCheck className="h-4 w-4" />
        该决策暂无监督层审核记录（历史数据或未触发审核）
      </div>
    )
  }

  return (
    <div className="rounded-md border border-border/60 bg-muted/30 p-3 space-y-3">
      {/* 审核头部：score + 红线 + 通过状态 */}
      <div className="flex items-center gap-2 flex-wrap">
        {score && (
          <Badge variant={SCORE_VARIANT[score] ?? "outline"} className="text-xs">
            审核评分 {score}
          </Badge>
        )}
        {(summary?.has_red_line || issues.some(i => i.red_line_id)) && (
          <Badge variant="destructive">
            <ShieldAlert className="mr-1 h-3 w-3" />
            命中红线
          </Badge>
        )}
        {(audit?.passed ?? summary?.passed) ? (
          <Badge variant="success">
            <CheckCircle2 className="mr-1 h-3 w-3" />
            审核通过
          </Badge>
        ) : hasAudit ? (
          <Badge variant="warning">
            <AlertTriangle className="mr-1 h-3 w-3" />
            审核未通过
          </Badge>
        ) : null}
      </div>

      {/* 总评 */}
      {(audit?.summary || summary?.summary) && (
        <p className="text-sm text-muted-foreground">{audit?.summary ?? summary?.summary}</p>
      )}

      {/* 审核问题列表 */}
      {issues.length > 0 && (
        <div className="space-y-2">
          {issues.map((issue, idx) => (
            <div key={idx} className="rounded border bg-background p-2 text-sm space-y-1">
              <div className="flex items-center gap-2 flex-wrap">
                <Badge
                  variant={issue.severity === "critical" ? "destructive" : issue.severity === "warning" ? "warning" : "secondary"}
                  className="text-xs"
                >
                  {issue.severity === "critical" ? "严重" : issue.severity === "warning" ? "警告" : "提示"}
                </Badge>
                <span className="font-medium text-xs text-muted-foreground">{issue.check_item}</span>
                {issue.red_line_id && (
                  <Badge variant="destructive" className="text-xs">{issue.red_line_id}</Badge>
                )}
              </div>
              <p className="text-xs">{issue.problem}</p>
              {issue.suggestion && (
                <p className={cn("text-xs", "text-muted-foreground")}>建议：{issue.suggestion}</p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* 用户确认（采纳/驳回）—— 人机协作闭环 */}
      {!alreadyFeedback && !feedbackMutation.isPending && (
        <div className="pt-1 border-t">
          {feedbackOpen ? (
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
                  onClick={() => feedbackMutation.mutate({ feedback: "approved", comment: feedbackNote })}
                >
                  <ThumbsUp className="mr-1 h-3 w-3" /> 采纳
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => feedbackMutation.mutate({ feedback: "rejected", comment: feedbackNote })}
                >
                  <ThumbsDown className="mr-1 h-3 w-3" /> 驳回
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setFeedbackOpen(false)}>
                  取消
                </Button>
              </div>
            </div>
          ) : (
            <Button size="sm" variant="outline" onClick={() => setFeedbackOpen(true)}>
              提交人工确认
            </Button>
          )}
        </div>
      )}
      {alreadyFeedback && (
        <p className="text-xs text-muted-foreground">
          <XCircle className="mr-1 h-3 w-3 inline" />
          已提交人工确认（采纳/驳回）
        </p>
      )}
    </div>
  )
}