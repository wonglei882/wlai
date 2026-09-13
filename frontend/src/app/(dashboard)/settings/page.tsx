"use client"

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { toast } from "@/store/toast-store"
import {
  Settings as SettingsIcon, Loader2, CheckCircle2, XCircle,
  Save, ExternalLink, Key, Server, Bot,
} from "lucide-react"
import Link from "next/link"
import { useState, useEffect } from "react"

// ---- localStorage 配置管理 ----
interface AppSettings {
  aiProvider: string
  aiBaseUrl: string
  aiModel: string
  multimodalBackend: string
  pmScanInterval: number
  pmMaxFixAttempts: number
  pmMaxIssuesPerRound: number
}

const DEFAULT_SETTINGS: AppSettings = {
  aiProvider: "openai",
  aiBaseUrl: "https://api.openai.com/v1",
  aiModel: "gpt-4",
  multimodalBackend: "none",
  pmScanInterval: 30,
  pmMaxFixAttempts: 3,
  pmMaxIssuesPerRound: 100,
}

function loadSettings(): AppSettings {
  if (typeof window === "undefined") return DEFAULT_SETTINGS
  try {
    const raw = localStorage.getItem("wlai_settings")
    if (raw) return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) }
  } catch { /* ignore */ }
  return DEFAULT_SETTINGS
}

function saveSettings(s: AppSettings) {
  localStorage.setItem("wlai_settings", JSON.stringify(s))
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    setSettings(loadSettings())
  }, [])

  const { data: healthData, isLoading } = useQuery({
    queryKey: ["health-ready"],
    queryFn: () => api.healthReady(),
  })

  const components = healthData?.components ?? {}

  const update = (partial: Partial<AppSettings>) => {
    setSettings((prev) => ({ ...prev, ...partial }))
    setSaved(false)
  }

  const handleSave = () => {
    saveSettings(settings)
    setSaved(true)
    toast.success("设置已保存")
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">系统设置</h1>
          <p className="text-muted-foreground">配置 AI 提供商、多模态后端与 PM Agent 参数</p>
        </div>
        <Button onClick={handleSave}>
          {saved ? <CheckCircle2 className="mr-2 h-4 w-4" /> : <Save className="mr-2 h-4 w-4" />}
          {saved ? "已保存" : "保存设置"}
        </Button>
      </div>

      {/* System Status */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <SettingsIcon className="h-5 w-5 text-primary" />
            <CardTitle className="text-lg">系统状态</CardTitle>
          </div>
          <CardDescription>后端服务各组件运行状态</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex justify-center py-4">
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
            </div>
          ) : (
            <div className="space-y-2">
              {Object.entries(components).map(([name, info]) => {
                const status = (info as Record<string, unknown>)?.status as string
                const detail = (info as Record<string, unknown>)?.detail as string
                const isOk = status === "ok" || status === "healthy"
                return (
                  <div key={name} className="flex items-center justify-between rounded-md border p-3">
                    <div className="flex items-center gap-2">
                      {isOk ? (
                        <CheckCircle2 className="h-4 w-4 text-green-400" />
                      ) : (
                        <XCircle className="h-4 w-4 text-red-400" />
                      )}
                      <span className="text-sm font-medium">{name}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      {detail && <span className="text-xs text-muted-foreground">{detail}</span>}
                      <Badge variant={isOk ? "success" : "destructive"} className="text-xs">
                        {status || "unknown"}
                      </Badge>
                    </div>
                  </div>
                )
              })}
              {Object.keys(components).length === 0 && (
                <p className="text-sm text-muted-foreground text-center py-4">
                  无法获取组件状态，请检查后端连接
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* AI Provider */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <Key className="h-5 w-5 text-primary" />
            <CardTitle className="text-lg">AI 提供商配置</CardTitle>
          </div>
          <CardDescription>配置 AI 模型连接参数</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label>提供商</Label>
              <select
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={settings.aiProvider}
                onChange={(e) => update({ aiProvider: e.target.value })}
              >
                <option value="openai">OpenAI</option>
                <option value="gemini">Google Gemini</option>
                <option value="claude">Anthropic Claude</option>
              </select>
            </div>
            <div className="space-y-2">
              <Label>模型名称</Label>
              <Input
                value={settings.aiModel}
                onChange={(e) => update({ aiModel: e.target.value })}
                placeholder="gpt-4"
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label>API Base URL</Label>
            <Input
              value={settings.aiBaseUrl}
              onChange={(e) => update({ aiBaseUrl: e.target.value })}
              placeholder="https://api.openai.com/v1"
            />
            <p className="text-xs text-muted-foreground">
              API Key 请在后端 .env 文件中设置 OPENAI_API_KEY。修改后需重启后端。
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Multimodal */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <Server className="h-5 w-5 text-primary" />
            <CardTitle className="text-lg">多模态后端</CardTitle>
          </div>
          <CardDescription>视觉一致性检测的模型配置</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 gap-3">
            {[
              { value: "none", label: "无", desc: "不启用多模态检测" },
              { value: "cloud", label: "云端", desc: "使用云端多模态 API" },
              { value: "local", label: "本地", desc: "使用本地模型（需 GPU）" },
            ].map((opt) => (
              <button
                key={opt.value}
                onClick={() => update({ multimodalBackend: opt.value })}
                className={`rounded-lg border p-3 text-left transition-colors ${
                  settings.multimodalBackend === opt.value
                    ? "border-primary bg-primary/10"
                    : "border-border hover:border-primary/50"
                }`}
              >
                <p className="font-medium text-sm">{opt.label}</p>
                <p className="text-xs text-muted-foreground mt-1">{opt.desc}</p>
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* PM Agent */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <Bot className="h-5 w-5 text-primary" />
            <CardTitle className="text-lg">PM Agent 参数</CardTitle>
          </div>
          <CardDescription>自主巡检默认参数（每个项目可在诊断面板中单独覆盖）</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-3">
            <div className="space-y-2">
              <Label>巡检间隔（分钟）</Label>
              <Input
                type="number"
                min={5}
                value={settings.pmScanInterval}
                onChange={(e) => update({ pmScanInterval: parseInt(e.target.value) || 30 })}
              />
            </div>
            <div className="space-y-2">
              <Label>最大自动修复次数</Label>
              <Input
                type="number"
                min={1}
                max={10}
                value={settings.pmMaxFixAttempts}
                onChange={(e) => update({ pmMaxFixAttempts: parseInt(e.target.value) || 3 })}
              />
            </div>
            <div className="space-y-2">
              <Label>单轮问题上限</Label>
              <Input
                type="number"
                min={10}
                max={500}
                value={settings.pmMaxIssuesPerRound}
                onChange={(e) => update({ pmMaxIssuesPerRound: parseInt(e.target.value) || 100 })}
              />
            </div>
          </div>
          <Link href="/pm">
            <Button variant="outline" size="sm">
              <ExternalLink className="mr-2 h-3 w-3" />
              前往 PM Agent 总控台
            </Button>
          </Link>
        </CardContent>
      </Card>
    </div>
  )
}
