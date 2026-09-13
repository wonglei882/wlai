"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { api } from "@/lib/api-client"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { BookOpen, Film, ArrowRight, ArrowLeft, Sparkles, Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"

interface OnboardingWizardProps {
  onComplete: () => void
}

export function OnboardingWizard({ onComplete }: OnboardingWizardProps) {
  const router = useRouter()
  const queryClient = useQueryClient()
  const [step, setStep] = useState(0)
  const [genre, setGenre] = useState<"novel" | "comic">("novel")
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const [targetWords, setTargetWords] = useState("100000")

  const createMutation = useMutation({
    mutationFn: () =>
      api.createProject({
        title,
        description: description || undefined,
        genre,
        target_words: parseInt(targetWords) || undefined,
      }),
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] })
      router.push(`/projects/${project.id}`)
      onComplete()
    },
  })

  const steps = [
    { title: "欢迎使用 WLai", desc: "AI 内容一致性守护平台" },
    { title: "选择创作类型", desc: "选择你要进行的创作形式" },
    { title: "创建项目", desc: "填写项目基本信息" },
  ]

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <Card className="w-full max-w-lg mx-4">
        <CardHeader className="text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
            <Sparkles className="h-6 w-6 text-primary" />
          </div>
          <CardTitle className="text-xl">{steps[step].title}</CardTitle>
          <CardDescription>{steps[step].desc}</CardDescription>
        </CardHeader>
        <CardContent>
          {/* Step indicators */}
          <div className="flex items-center justify-center gap-2 mb-6">
            {steps.map((_, i) => (
              <div
                key={i}
                className={cn(
                  "h-2 w-8 rounded-full transition-colors",
                  i <= step ? "bg-primary" : "bg-muted"
                )}
              />
            ))}
          </div>

          {/* Step 0: Welcome */}
          {step === 0 && (
            <div className="text-center space-y-4">
              <p className="text-sm text-muted-foreground leading-relaxed">
                WLai 帮助你管理 AI 创作过程中的内容一致性——
                角色不变脸、剧情不矛盾、伏笔不遗漏。
              </p>
              <div className="grid grid-cols-2 gap-3 text-left">
                <div className="rounded-lg border p-3">
                  <BookOpen className="h-5 w-5 text-primary mb-2" />
                  <p className="text-sm font-medium">小说工作台</p>
                  <p className="text-xs text-muted-foreground">长篇小说创作与质量守护</p>
                </div>
                <div className="rounded-lg border p-3">
                  <Film className="h-5 w-5 text-primary mb-2" />
                  <p className="text-sm font-medium">漫剧工作台</p>
                  <p className="text-xs text-muted-foreground">AI 漫剧全流程制片管理</p>
                </div>
              </div>
              <Button className="w-full" onClick={() => setStep(1)}>
                开始 <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </div>
          )}

          {/* Step 1: Choose genre */}
          {step === 1 && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <button
                  onClick={() => setGenre("novel")}
                  className={cn(
                    "rounded-lg border p-4 text-left transition-colors",
                    genre === "novel" ? "border-primary bg-primary/5" : "hover:bg-accent"
                  )}
                >
                  <BookOpen className={cn("h-6 w-6 mb-2", genre === "novel" ? "text-primary" : "text-muted-foreground")} />
                  <p className="font-medium">小说</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    章节编辑、角色管理、伏笔追踪、质量诊断
                  </p>
                </button>
                <button
                  onClick={() => setGenre("comic")}
                  className={cn(
                    "rounded-lg border p-4 text-left transition-colors",
                    genre === "comic" ? "border-primary bg-primary/5" : "hover:bg-accent"
                  )}
                >
                  <Film className={cn("h-6 w-6 mb-2", genre === "comic" ? "text-primary" : "text-muted-foreground")} />
                  <p className="font-medium">漫剧</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    设定圣经、分镜生成、镜头管理、审核工作流
                  </p>
                </button>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => setStep(0)}>
                  <ArrowLeft className="mr-2 h-4 w-4" /> 上一步
                </Button>
                <Button className="flex-1" onClick={() => setStep(2)}>
                  下一步 <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </div>
            </div>
          )}

          {/* Step 2: Create project */}
          {step === 2 && (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label>项目标题 *</Label>
                <Input
                  placeholder={genre === "novel" ? "我的小说" : "我的漫剧"}
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  autoFocus
                />
              </div>
              <div className="space-y-2">
                <Label>项目描述</Label>
                <Textarea
                  rows={2}
                  placeholder="简要描述你的项目..."
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label>目标字数</Label>
                <Input
                  type="number"
                  value={targetWords}
                  onChange={(e) => setTargetWords(e.target.value)}
                  min={1000}
                />
              </div>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => setStep(1)}>
                  <ArrowLeft className="mr-2 h-4 w-4" /> 上一步
                </Button>
                <Button
                  className="flex-1"
                  onClick={() => createMutation.mutate()}
                  disabled={createMutation.isPending || !title.trim()}
                >
                  {createMutation.isPending ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Sparkles className="mr-2 h-4 w-4" />
                  )}
                  创建项目
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
