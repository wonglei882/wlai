"use client"

import { useState, useEffect } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Settings2, Save } from "lucide-react"
import { cn } from "@/lib/utils"

const LEVELS = [
  { value: "advisor", label: "建议模式", desc: "PM Agent 仅提供建议，所有操作需人工确认" },
  { value: "advisor_plus", label: "增强自主", desc: "低风险操作自动执行，高风险操作需确认" },
  { value: "autonomous", label: "全自动", desc: "所有操作自动执行，仅记录日志" },
]

const AUTO_TYPES = [
  { value: "outline", label: "大纲" },
  { value: "suggest", label: "建议" },
  { value: "foreshadow", label: "伏笔" },
  { value: "character", label: "角色" },
  { value: "world_setting", label: "世界观" },
]

interface AutonomyAdjusterProps {
  projectId: string
  userId: string
}

export function AutonomyAdjuster({ projectId, userId }: AutonomyAdjusterProps) {
  const queryClient = useQueryClient()

  const { data } = useQuery({
    queryKey: ["autonomy", projectId],
    queryFn: () => api.getAutonomyConfig(projectId, userId),
  })

  const [level, setLevel] = useState(data?.level as string || "advisor")
  const [threshold, setThreshold] = useState((data?.confidence_threshold as number) || 0.6)
  const [autoTypes, setAutoTypes] = useState<string[]>(
    (data?.auto_execute_types as string[]) || ["outline", "suggest", "foreshadow", "character", "world_setting"]
  )

  useEffect(() => {
    if (data) {
      setLevel(data.level as string || "advisor")
      setThreshold((data.confidence_threshold as number) || 0.6)
      setAutoTypes((data.auto_execute_types as string[]) || [])
    }
  }, [data])

  const saveMutation = useMutation({
    mutationFn: () => api.setAutonomyConfig(projectId, userId, level, threshold, autoTypes.join(",")),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["autonomy", projectId] }),
  })

  const toggleType = (type: string) => {
    setAutoTypes(prev =>
      prev.includes(type) ? prev.filter(t => t !== type) : [...prev, type]
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <Settings2 className="h-5 w-5 text-primary" />
          PM Agent 自主度
        </CardTitle>
        <CardDescription>控制 PM Agent 的自动修复权限</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Level Selection */}
        <div className="space-y-3">
          <Label>自主度级别</Label>
          <div className="grid grid-cols-3 gap-3">
            {LEVELS.map((l) => (
              <button
                key={l.value}
                onClick={() => setLevel(l.value)}
                className={cn(
                  "rounded-lg border p-3 text-left transition-colors",
                  level === l.value
                    ? "border-primary bg-primary/5"
                    : "hover:bg-accent"
                )}
              >
                <p className="font-medium text-sm">{l.label}</p>
                <p className="text-xs text-muted-foreground mt-1">{l.desc}</p>
              </button>
            ))}
          </div>
        </div>

        {/* Confidence Threshold */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label>置信度阈值</Label>
            <Badge variant="outline">{threshold.toFixed(2)}</Badge>
          </div>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={threshold}
            onChange={(e) => setThreshold(parseFloat(e.target.value))}
            className="w-full h-2 bg-secondary rounded-lg appearance-none cursor-pointer"
          />
          <p className="text-xs text-muted-foreground">
            低于此置信度的修复决策不会自动执行
          </p>
        </div>

        {/* Auto Execute Types */}
        <div className="space-y-2">
          <Label>自动执行类型</Label>
          <div className="flex flex-wrap gap-2">
            {AUTO_TYPES.map((t) => (
              <button
                key={t.value}
                onClick={() => toggleType(t.value)}
                className={cn(
                  "rounded-full px-3 py-1 text-xs font-medium transition-colors border",
                  autoTypes.includes(t.value)
                    ? "bg-primary text-primary-foreground border-primary"
                    : "bg-background text-muted-foreground border-input hover:bg-accent"
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {/* Save Button */}
        <Button
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending}
          className="w-full"
        >
          <Save className="mr-2 h-4 w-4" />
          {saveMutation.isPending ? "保存中..." : "保存配置"}
        </Button>
      </CardContent>
    </Card>
  )
}
