"use client"

import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  Line,
  LineChart,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Bar,
  BarChart,
  Cell,
} from "recharts"
import { api } from "@/lib/api-client"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { SkeletonCard } from "@/components/ui/skeleton"
import { Coins, TrendingUp, Wallet, Activity, Database } from "lucide-react"
import { cn } from "@/lib/utils"

const DAY_OPTIONS = [7, 14, 30]

const FEATURE_COLORS = [
  "#6366f1",
  "#8b5cf6",
  "#ec4899",
  "#f59e0b",
  "#10b981",
  "#3b82f6",
  "#ef4444",
  "#14b8a6",
]

interface TokenSummary {
  total_tokens: number
  prompt_tokens: number
  completion_tokens: number
  cost_usd: number
  by_feature: Record<string, number>
  by_action: Record<string, number>
  record_count: number
  days: number
}

interface TrendPoint {
  date: string
  total_tokens: number
  cost_usd: number
  count: number
}

function fmt(n: number): string {
  return (n ?? 0).toLocaleString()
}

export default function TokenUsagePage() {
  const [days, setDays] = useState(7)

  const { data: summaryData, isLoading: loadingSummary } = useQuery({
    queryKey: ["token-usage-summary", days],
    queryFn: () =>
      api.getTokenSummary(days) as Promise<{ success: boolean; summary: TokenSummary }>,
  })

  const { data: trendData, isLoading: loadingTrend } = useQuery({
    queryKey: ["token-usage-trend", days],
    queryFn: () => api.getTokenTrend(days) as Promise<{ success: boolean; trend: TrendPoint[] }>,
  })

  const summary = summaryData?.summary
  const trend = trendData?.trend ?? []

  const featureData = useMemo(() => {
    if (!summary?.by_feature) return []
    return Object.entries(summary.by_feature)
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value)
  }, [summary])

  const actionData = useMemo(() => {
    if (!summary?.by_action) return []
    return Object.entries(summary.by_action)
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value)
  }, [summary])

  if (loadingSummary) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-48 mb-2 rounded bg-muted animate-pulse" />
        <div className="grid gap-4 md:grid-cols-4">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
        <SkeletonCard />
        <SkeletonCard />
      </div>
    )
  }

  const stats = [
    { label: "总消耗 (tokens)", value: fmt(summary?.total_tokens ?? 0), icon: Coins, color: "text-yellow-400" },
    { label: "Prompt tokens", value: fmt(summary?.prompt_tokens ?? 0), icon: TrendingUp, color: "text-blue-400" },
    { label: "Completion tokens", value: fmt(summary?.completion_tokens ?? 0), icon: Activity, color: "text-purple-400" },
    { label: "成本 (USD)", value: `$${(summary?.cost_usd ?? 0).toFixed(4)}`, icon: Wallet, color: "text-green-400" },
  ]

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Token 用量统计</h1>
          <p className="text-muted-foreground">PM Agent 各功能 Token 消耗与成本分析</p>
        </div>
        <div className="flex items-center gap-1 rounded-lg border p-1">
          {DAY_OPTIONS.map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={cn(
                "rounded-md px-3 py-1 text-sm font-medium transition-colors",
                days === d
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-accent"
              )}
            >
              {d} 天
            </button>
          ))}
        </div>
      </div>

      {/* 汇总卡片 */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {stats.map((s) => (
          <Card key={s.label}>
            <CardHeader className="pb-2">
              <CardDescription className="flex items-center gap-1.5">
                <s.icon className={cn("h-4 w-4", s.color)} />
                {s.label}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold">{s.value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* 趋势图 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingUp className="h-5 w-5 text-primary" />
            Token 消耗趋势
          </CardTitle>
          <CardDescription>按天汇总，{loadingTrend ? "加载中..." : `${days} 天`}</CardDescription>
        </CardHeader>
        <CardContent>
          {trend.length === 0 ? (
            <p className="text-center text-muted-foreground py-10">暂无数据</p>
          ) : (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={trend} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="date" fontSize={12} tickFormatter={(v: string) => v.slice(5)} />
                  <YAxis fontSize={12} />
                  <Tooltip
                    formatter={(value: unknown) => [fmt(Number(value ?? 0)), "tokens"]}
                    contentStyle={{
                      background: "var(--popover)",
                      border: "1px solid var(--border)",
                      borderRadius: 8,
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey="total_tokens"
                    name="Token 消耗"
                    stroke="var(--primary)"
                    strokeWidth={2}
                    dot={{ r: 3 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        {/* 按功能分布 */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Database className="h-5 w-5 text-indigo-400" />
              按功能分布
            </CardTitle>
            <CardDescription>各功能模块 Token 消耗占比</CardDescription>
          </CardHeader>
          <CardContent>
            {featureData.length === 0 ? (
              <p className="text-center text-muted-foreground py-10">暂无数据</p>
            ) : (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={featureData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                    <XAxis dataKey="name" fontSize={12} interval={0} angle={-15} textAnchor="end" height={50} />
                    <YAxis fontSize={12} />
                    <Tooltip
                      formatter={(value: unknown) => [fmt(Number(value ?? 0)), "tokens"]}
                      contentStyle={{
                        background: "var(--popover)",
                        border: "1px solid var(--border)",
                        borderRadius: 8,
                      }}
                    />
                    <Bar dataKey="value" name="tokens" radius={[4, 4, 0, 0]}>
                      {featureData.map((_, i) => (
                        <Cell key={i} fill={FEATURE_COLORS[i % FEATURE_COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </CardContent>
        </Card>

        {/* 按操作分布 */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="h-5 w-5 text-emerald-400" />
              按操作分布
            </CardTitle>
            <CardDescription>各操作类型的 Token 消耗明细</CardDescription>
          </CardHeader>
          <CardContent>
            {actionData.length === 0 ? (
              <p className="text-center text-muted-foreground py-10">暂无数据</p>
            ) : (
              <div className="space-y-2">
                {actionData.map((a) => {
                  const ratio = summary?.total_tokens ? a.value / summary.total_tokens : 0
                  return (
                    <div key={a.name} className="flex items-center gap-3">
                      <span className="w-32 truncate text-sm text-muted-foreground">{a.name}</span>
                      <div className="h-2 flex-1 rounded-full bg-muted overflow-hidden">
                        <div
                          className="h-full rounded-full bg-primary"
                          style={{ width: `${Math.min(ratio * 100, 100)}%` }}
                        />
                      </div>
                      <Badge variant="outline" className="shrink-0">
                        {fmt(a.value)}
                      </Badge>
                    </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
