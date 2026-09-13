"use client"

import { use, useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import type { CharacterCard, NegativePromptLibrary } from "@/types"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import {
  BookOpen, Users, Palette, Ban, Loader2, Plus, Save, Lock, Unlock,
  ChevronDown, ChevronUp, X,
} from "lucide-react"
import { cn } from "@/lib/utils"
import Link from "next/link"
import { ArrowLeft } from "lucide-react"

export default function ComicBiblePage({ params }: { params: Promise<{ id: string }> }) {
  const { id: projectId } = use(params)
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<"world" | "characters" | "style" | "negative">("world")

  // ---- 数据查询 ----
  const { data: charsData, isLoading: charsLoading } = useQuery({
    queryKey: ["characters", projectId],
    queryFn: () => api.listCharacters(projectId),
  })

  const { data: styleData } = useQuery({
    queryKey: ["style", projectId],
    queryFn: () => api.getStyle(projectId),
  })

  const { data: negData } = useQuery({
    queryKey: ["negative-prompts", projectId],
    queryFn: () => api.getNegativePrompts(projectId),
  })

  const characters = charsData?.characters ?? []
  const negativeLibs = negData?.libraries ?? []

  const tabs = [
    { key: "world" as const, label: "世界观", icon: BookOpen },
    { key: "characters" as const, label: "角色卡", icon: Users, count: characters.length },
    { key: "style" as const, label: "画风", icon: Palette },
    { key: "negative" as const, label: "负面词库", icon: Ban },
  ]

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
        <span className="text-foreground">设定圣经</span>
      </div>

      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold flex items-center gap-3">
          <BookOpen className="h-8 w-8 text-primary" />
          设定圣经
        </h1>
        <p className="text-muted-foreground mt-1">角色卡、世界观、画风设定与负面词库管理</p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={cn(
              "flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px",
              activeTab === tab.key
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            <tab.icon className="h-4 w-4" />
            {tab.label}
            {tab.count != null && tab.count > 0 && (
              <Badge variant="secondary" className="text-xs h-5 min-w-[20px] justify-center">
                {tab.count}
              </Badge>
            )}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === "world" && <WorldSettings projectId={projectId} />}
      {activeTab === "characters" && (
        <CharacterPanel
          projectId={projectId}
          characters={characters}
          isLoading={charsLoading}
        />
      )}
      {activeTab === "style" && <ArtStylePanel projectId={projectId} existingStyle={styleData} />}
      {activeTab === "negative" && <NegativePanel projectId={projectId} libraries={negativeLibs} />}
    </div>
  )
}

// ============================================================================
// 世界观设定
// ============================================================================
function WorldSettings({ projectId }: { projectId: string }) {
  const [form, setForm] = useState({
    world_name: "", summary: "", time_period: "", tone: "",
  })
  const [saved, setSaved] = useState(false)

  const createMutation = useMutation({
    mutationFn: () => api.createBible({ project_id: projectId, ...form }),
    onSuccess: () => { setSaved(true); setTimeout(() => setSaved(false), 2000) },
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">世界观设定</CardTitle>
        <CardDescription>定义故事发生的世界背景</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <Label>世界名称</Label>
            <Input placeholder="如：九州大陆" value={form.world_name}
              onChange={(e) => setForm({ ...form, world_name: e.target.value })} />
          </div>
          <div className="space-y-2">
            <Label>时代背景</Label>
            <Input placeholder="如：架空古代" value={form.time_period}
              onChange={(e) => setForm({ ...form, time_period: e.target.value })} />
          </div>
        </div>
        <div className="space-y-2">
          <Label>基调</Label>
          <Input placeholder="如：热血、暗黑、治愈" value={form.tone}
            onChange={(e) => setForm({ ...form, tone: e.target.value })} />
        </div>
        <div className="space-y-2">
          <Label>世界概述</Label>
          <Textarea placeholder="描述这个世界的核心设定..." rows={4} value={form.summary}
            onChange={(e) => setForm({ ...form, summary: e.target.value })} />
        </div>
        <Button onClick={() => createMutation.mutate()} disabled={createMutation.isPending || !form.world_name}>
          {createMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
          {saved ? "已保存" : "保存设定"}
        </Button>
      </CardContent>
    </Card>
  )
}

// ============================================================================
// 角色卡面板
// ============================================================================
function CharacterPanel({
  projectId, characters, isLoading,
}: {
  projectId: string
  characters: CharacterCard[]
  isLoading: boolean
}) {
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [editingChar, setEditingChar] = useState<CharacterCard | null>(null)

  const lockMutation = useMutation({
    mutationFn: (charId: string) => api.lockCharacter(charId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["characters", projectId] }),
  })

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          共 {characters.length} 个角色{characters.filter(c => c.status === "locked").length > 0 && (
            <span className="ml-2">（{characters.filter(c => c.status === "locked").length} 个已锁定）</span>
          )}
        </p>
        <Button size="sm" onClick={() => { setEditingChar(null); setShowForm(!showForm) }}>
          <Plus className="mr-1 h-4 w-4" />
          新建角色
        </Button>
      </div>

      {/* 新建/编辑表单 */}
      {showForm && (
        <CharacterForm
          projectId={projectId}
          character={editingChar}
          onClose={() => { setShowForm(false); setEditingChar(null) }}
        />
      )}

      {/* 角色卡网格 */}
      {characters.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            还没有角色卡，点击上方按钮创建第一个角色
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {characters.map((char) => (
            <Card key={char.id} className={cn(
              "transition-shadow hover:shadow-md",
              char.status === "locked" && "border-green-200 bg-green-50/30"
            )}>
              <CardHeader className="pb-2">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/10 text-primary font-bold text-lg">
                      {char.name?.[0] || "?"}
                    </div>
                    <div>
                      <CardTitle className="text-base">{char.name}</CardTitle>
                      <p className="text-xs text-muted-foreground">
                        {[char.gender, char.age].filter(Boolean).join(" · ") || "未设定"}
                      </p>
                    </div>
                  </div>
                  <Badge variant={char.status === "locked" ? "success" : "outline"} className="text-xs">
                    {char.status === "locked" ? "已锁定" : char.status}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="pb-3">
                <div className="space-y-1 text-xs text-muted-foreground">
                  {char.hair && <p>发型: {char.hair}</p>}
                  {char.eyes && <p>瞳色: {char.eyes}</p>}
                  {char.outfit && <p>服装: {char.outfit}</p>}
                  {char.personality && <p>性格: {char.personality}</p>}
                  {char.catchphrase && <p>口头禅: &ldquo;{char.catchphrase}&rdquo;</p>}
                </div>
                <div className="flex gap-2 mt-3">
                  <Button size="sm" variant="outline" className="text-xs flex-1"
                    onClick={() => { setEditingChar(char); setShowForm(true) }}>
                    编辑
                  </Button>
                  <Button size="sm" variant="outline" className="text-xs"
                    onClick={() => lockMutation.mutate(char.id)}
                    disabled={lockMutation.isPending}>
                    {char.status === "locked" ? <Unlock className="h-3 w-3" /> : <Lock className="h-3 w-3" />}
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

// ============================================================================
// 角色表单
// ============================================================================
function CharacterForm({
  projectId, character, onClose,
}: {
  projectId: string
  character: CharacterCard | null
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const isEdit = !!character
  const [form, setForm] = useState({
    name: character?.name || "",
    age: character?.age || "",
    gender: character?.gender || "",
    hair: character?.hair || "",
    eyes: character?.eyes || "",
    outfit: character?.outfit || "",
    personality: character?.personality || "",
    catchphrase: character?.catchphrase || "",
    appearance_prompt: character?.appearance_prompt || "",
  })

  const mutation = useMutation({
    mutationFn: () => {
      const data = { ...form, project_id: projectId }
      return isEdit
        ? api.updateCharacter(character!.id, data)
        : api.createCharacter(data)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["characters", projectId] })
      onClose()
    },
  })

  const fields: { key: keyof typeof form; label: string; required?: boolean }[] = [
    { key: "name", label: "姓名", required: true },
    { key: "age", label: "年龄" },
    { key: "gender", label: "性别" },
    { key: "hair", label: "发型" },
    { key: "eyes", label: "瞳色" },
    { key: "outfit", label: "服装" },
    { key: "personality", label: "性格" },
    { key: "catchphrase", label: "口头禅" },
  ]

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">{isEdit ? "编辑角色" : "新建角色"}</CardTitle>
          <Button variant="ghost" size="sm" onClick={onClose}><X className="h-4 w-4" /></Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {fields.map((f) => (
            <div key={f.key} className="space-y-1">
              <Label className="text-xs">{f.label}{f.required && " *"}</Label>
              <Input
                value={form[f.key]}
                placeholder={f.label}
                onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
              />
            </div>
          ))}
        </div>
        <div className="space-y-1">
          <Label className="text-xs">外貌提示词（用于 AI 出图一致性）</Label>
          <Textarea
            rows={2}
            value={form.appearance_prompt}
            placeholder="详细描述角色外貌，如：黑色长发、红色瞳孔、身穿黑色斗篷..."
            onChange={(e) => setForm({ ...form, appearance_prompt: e.target.value })}
          />
        </div>
        <div className="flex gap-2">
          <Button onClick={() => mutation.mutate()} disabled={mutation.isPending || !form.name}>
            {mutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
            {isEdit ? "保存修改" : "创建角色"}
          </Button>
          <Button variant="outline" onClick={onClose}>取消</Button>
        </div>
      </CardContent>
    </Card>
  )
}

// ============================================================================
// 画风设定
// ============================================================================
function ArtStylePanel({ projectId, existingStyle }: { projectId: string; existingStyle?: Record<string, unknown> }) {
  const [form, setForm] = useState({
    style_name: (existingStyle?.style_name as string) || "",
    line_style: (existingStyle?.line_style as string) || "",
    lighting: (existingStyle?.lighting as string) || "",
    base_prompt: (existingStyle?.base_prompt as string) || "",
  })
  const [saved, setSaved] = useState(false)

  const createMutation = useMutation({
    mutationFn: () => api.createStyle({ project_id: projectId, ...form }),
    onSuccess: () => { setSaved(true); setTimeout(() => setSaved(false), 2000) },
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">画风设定</CardTitle>
        <CardDescription>定义漫剧的整体视觉风格</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <Label>画风名称</Label>
            <Input placeholder="如：日系赛璐璐 / 国风水墨 / 厚涂" value={form.style_name}
              onChange={(e) => setForm({ ...form, style_name: e.target.value })} />
          </div>
          <div className="space-y-2">
            <Label>线条风格</Label>
            <Input placeholder="如：细腻线稿 / 无线条 / 粗犷" value={form.line_style}
              onChange={(e) => setForm({ ...form, line_style: e.target.value })} />
          </div>
        </div>
        <div className="space-y-2">
          <Label>光影风格</Label>
          <Input placeholder="如：柔和自然光 / 强对比 / 赛博朋克霓虹" value={form.lighting}
            onChange={(e) => setForm({ ...form, lighting: e.target.value })} />
        </div>
        <div className="space-y-2">
          <Label>基础提示词</Label>
          <Textarea rows={3} placeholder="全局画风提示词，会注入到每个镜头的出图提示词中..."
            value={form.base_prompt}
            onChange={(e) => setForm({ ...form, base_prompt: e.target.value })} />
        </div>
        <Button onClick={() => createMutation.mutate()} disabled={createMutation.isPending || !form.style_name}>
          {createMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
          {saved ? "已保存" : "保存画风"}
        </Button>
      </CardContent>
    </Card>
  )
}

// ============================================================================
// 负面词库
// ============================================================================
function NegativePanel({ projectId, libraries }: { projectId: string; libraries: NegativePromptLibrary[] }) {
  const queryClient = useQueryClient()
  const categories = ["universal", "character", "scene"]
  const categoryLabels: Record<string, string> = { universal: "通用", character: "角色", scene: "场景" }
  const [activeCat, setActiveCat] = useState("universal")
  const [text, setText] = useState("")

  const currentLib = libraries.find(l => l.category === activeCat)

  const saveMutation = useMutation({
    mutationFn: () => {
      const prompts = text.split("\n").map(s => s.trim()).filter(Boolean)
      return api.saveNegativePrompts(projectId, activeCat, prompts)
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["negative-prompts", projectId] }),
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">负面词库</CardTitle>
        <CardDescription>定义不希望出现在画面中的元素</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Category tabs */}
        <div className="flex gap-2">
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => {
                setActiveCat(cat)
                const lib = libraries.find(l => l.category === cat)
                setText((lib?.prompts || []).join("\n"))
              }}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm font-medium transition-colors border",
                activeCat === cat
                  ? "bg-primary text-primary-foreground border-primary"
                  : "bg-background text-muted-foreground border-input hover:bg-accent"
              )}
            >
              {categoryLabels[cat]}
            </button>
          ))}
        </div>

        <div className="space-y-2">
          <Label>负面提示词（每行一个）</Label>
          <Textarea
            rows={8}
            placeholder={"low quality\nblurry\ndeformed hands\nextra fingers"}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            当前 {text.split("\n").filter(s => s.trim()).length} 条负面提示词
          </p>
        </div>

        <Button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
          {saveMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
          保存词库
        </Button>
      </CardContent>
    </Card>
  )
}
