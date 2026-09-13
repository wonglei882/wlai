"use client"

import { use, useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { useWorkspaceStore } from "@/store/workspace-store"
import type { CharacterCard } from "@/types"
import { cn } from "@/lib/utils"
import {
  BookOpen, Users, Palette, Ban, Loader2, Plus, Save, Lock, Unlock, X,
} from "lucide-react"

type BibleTab = "world" | "characters" | "style" | "negative"

export function BiblePanel({ projectId }: { projectId: string }) {
  const [activeTab, setActiveTab] = useState<BibleTab>("characters")
  const { selectCharacter } = useWorkspaceStore()

  const { data: charsData, isLoading: charsLoading } = useQuery({
    queryKey: ["characters", projectId],
    queryFn: () => api.listCharacters(projectId),
  })

  const characters = charsData?.characters ?? []

  const tabs: { key: BibleTab; label: string; icon: typeof BookOpen; count?: number }[] = [
    { key: "world", label: "世界", icon: BookOpen },
    { key: "characters", label: "角色", icon: Users, count: characters.length },
    { key: "style", label: "画风", icon: Palette },
    { key: "negative", label: "负面", icon: Ban },
  ]

  return (
    <div className="flex h-full flex-col bg-[#2B2B2B]">
      {/* Mini tab bar */}
      <div className="flex h-7 shrink-0 border-b border-[#515151] bg-[#3C3F41]">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={cn(
              "flex items-center gap-1 px-2 text-[10px] font-medium transition-colors border-b-2 -mb-px",
              activeTab === tab.key
                ? "border-[#4B6EAF] text-[#A9B7C6]"
                : "border-transparent text-[#6A7579] hover:text-[#A9B7C6]"
            )}
          >
            <tab.icon className="h-3 w-3" />
            {tab.label}
            {tab.count != null && tab.count > 0 && (
              <span className="rounded bg-[#4B6EAF]/40 px-1 text-[9px]">{tab.count}</span>
            )}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {activeTab === "world" && <WorldForm projectId={projectId} />}
        {activeTab === "characters" && (
          <CharacterList
            projectId={projectId}
            characters={characters}
            isLoading={charsLoading}
            onSelect={(id) => selectCharacter(id)}
          />
        )}
        {activeTab === "style" && <StyleForm projectId={projectId} />}
        {activeTab === "negative" && <NegativeForm projectId={projectId} />}
      </div>
    </div>
  )
}

// ---- World Form ----
function WorldForm({ projectId }: { projectId: string }) {
  const [form, setForm] = useState({ world_name: "", summary: "", time_period: "", tone: "" })
  const [saved, setSaved] = useState(false)

  const mutation = useMutation({
    mutationFn: () => api.createBible({ project_id: projectId, ...form }),
    onSuccess: () => { setSaved(true); setTimeout(() => setSaved(false), 2000) },
  })

  return (
    <div className="space-y-2 p-2">
      <MiniInput label="世界名称" value={form.world_name} onChange={(v) => setForm({ ...form, world_name: v })} placeholder="九州大陆" />
      <MiniInput label="时代" value={form.time_period} onChange={(v) => setForm({ ...form, time_period: v })} placeholder="架空古代" />
      <MiniInput label="基调" value={form.tone} onChange={(v) => setForm({ ...form, tone: v })} placeholder="热血" />
      <div className="space-y-1">
        <label className="text-[10px] text-[#6A7579]">概述</label>
        <textarea
          rows={3}
          className="w-full rounded border border-[#515151] bg-[#3C3F41] px-2 py-1 text-xs text-[#A9B7C6] placeholder:text-[#6A7579] focus:border-[#4B6EAF] focus:outline-none"
          placeholder="世界核心设定..."
          value={form.summary}
          onChange={(e) => setForm({ ...form, summary: e.target.value })}
        />
      </div>
      <button
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending || !form.world_name}
        className="flex items-center gap-1 rounded bg-[#4B6EAF] px-2 py-1 text-[10px] text-white hover:bg-[#5A7DBF] disabled:opacity-50"
      >
        {mutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
        {saved ? "已保存" : "保存"}
      </button>
    </div>
  )
}

// ---- Character List ----
function CharacterList({
  projectId, characters, isLoading, onSelect,
}: {
  projectId: string
  characters: CharacterCard[]
  isLoading: boolean
  onSelect: (id: string) => void
}) {
  const queryClient = useQueryClient()
  const { selectCharacter } = useWorkspaceStore()
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ name: "", gender: "", hair: "", appearance_prompt: "" })

  const createMutation = useMutation({
    mutationFn: () => api.createCharacter({ project_id: projectId, ...form }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["characters", projectId] })
      setShowForm(false)
      setForm({ name: "", gender: "", hair: "", appearance_prompt: "" })
    },
  })

  const lockMutation = useMutation({
    mutationFn: (charId: string) => api.lockCharacter(charId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["characters", projectId] }),
  })

  if (isLoading) {
    return <div className="flex justify-center py-4"><Loader2 className="h-4 w-4 animate-spin text-[#6A7579]" /></div>
  }

  return (
    <div className="space-y-1 p-1">
      <button
        onClick={() => setShowForm(!showForm)}
        className="flex w-full items-center gap-1 rounded px-2 py-1 text-[10px] text-[#A9B7C6] hover:bg-[#4B6EAF]/30"
      >
        <Plus className="h-3 w-3" /> 新建角色
      </button>

      {showForm && (
        <div className="space-y-1 rounded border border-[#515151] bg-[#3C3F41] p-2">
          <MiniInput label="姓名 *" value={form.name} onChange={(v) => setForm({ ...form, name: v })} placeholder="角色名" />
          <MiniInput label="性别" value={form.gender} onChange={(v) => setForm({ ...form, gender: v })} placeholder="男/女" />
          <MiniInput label="发型" value={form.hair} onChange={(v) => setForm({ ...form, hair: v })} placeholder="黑色长发" />
          <div className="space-y-1">
            <label className="text-[10px] text-[#6A7579]">外貌提示词</label>
            <textarea
              rows={2}
              className="w-full rounded border border-[#515151] bg-[#2B2B2B] px-2 py-1 text-xs text-[#A9B7C6] placeholder:text-[#6A7579] focus:border-[#4B6EAF] focus:outline-none"
              placeholder="详细描述..."
              value={form.appearance_prompt}
              onChange={(e) => setForm({ ...form, appearance_prompt: e.target.value })}
            />
          </div>
          <div className="flex gap-1">
            <button
              onClick={() => createMutation.mutate()}
              disabled={createMutation.isPending || !form.name}
              className="flex items-center gap-1 rounded bg-[#4B6EAF] px-2 py-0.5 text-[10px] text-white hover:bg-[#5A7DBF] disabled:opacity-50"
            >
              {createMutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
              创建
            </button>
            <button onClick={() => setShowForm(false)} className="rounded px-2 py-0.5 text-[10px] text-[#6A7579] hover:bg-[#515151]">
              取消
            </button>
          </div>
        </div>
      )}

      {characters.length === 0 ? (
        <div className="px-2 py-4 text-center text-[10px] text-[#6A7579]">暂无角色卡</div>
      ) : (
        characters.map((char) => (
          <div
            key={char.id}
            className="group flex items-center gap-1.5 rounded px-2 py-1 hover:bg-[#4B6EAF]/30 cursor-pointer"
            onClick={() => onSelect(char.id)}
          >
            <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[#4B6EAF]/40 text-[9px] font-bold text-white">
              {char.name?.[0] || "?"}
            </div>
            <span className="truncate text-[11px] text-[#A9B7C6]">{char.name}</span>
            {char.status === "locked" && (
              <span className="text-[9px] text-green-400">锁定</span>
            )}
            <button
              className="ml-auto rounded p-0.5 opacity-0 group-hover:opacity-100 hover:bg-[#4B6EAF] hover:text-white text-[#6A7579]"
              onClick={(e) => { e.stopPropagation(); lockMutation.mutate(char.id) }}
              disabled={lockMutation.isPending}
            >
              {char.status === "locked" ? <Unlock className="h-3 w-3" /> : <Lock className="h-3 w-3" />}
            </button>
          </div>
        ))
      )}
    </div>
  )
}

// ---- Style Form ----
function StyleForm({ projectId }: { projectId: string }) {
  const [form, setForm] = useState({ style_name: "", line_style: "", lighting: "", base_prompt: "" })
  const [saved, setSaved] = useState(false)

  const mutation = useMutation({
    mutationFn: () => api.createStyle({ project_id: projectId, ...form }),
    onSuccess: () => { setSaved(true); setTimeout(() => setSaved(false), 2000) },
  })

  return (
    <div className="space-y-2 p-2">
      <MiniInput label="画风名称" value={form.style_name} onChange={(v) => setForm({ ...form, style_name: v })} placeholder="日系赛璐璐" />
      <MiniInput label="线条风格" value={form.line_style} onChange={(v) => setForm({ ...form, line_style: v })} placeholder="细腻线稿" />
      <MiniInput label="光影风格" value={form.lighting} onChange={(v) => setForm({ ...form, lighting: v })} placeholder="柔和自然光" />
      <div className="space-y-1">
        <label className="text-[10px] text-[#6A7579]">基础提示词</label>
        <textarea
          rows={3}
          className="w-full rounded border border-[#515151] bg-[#3C3F41] px-2 py-1 text-xs text-[#A9B7C6] placeholder:text-[#6A7579] focus:border-[#4B6EAF] focus:outline-none"
          placeholder="全局画风提示词..."
          value={form.base_prompt}
          onChange={(e) => setForm({ ...form, base_prompt: e.target.value })}
        />
      </div>
      <button
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending || !form.style_name}
        className="flex items-center gap-1 rounded bg-[#4B6EAF] px-2 py-1 text-[10px] text-white hover:bg-[#5A7DBF] disabled:opacity-50"
      >
        {mutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
        {saved ? "已保存" : "保存画风"}
      </button>
    </div>
  )
}

// ---- Negative Prompts Form ----
function NegativeForm({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const [category, setCategory] = useState("universal")
  const [text, setText] = useState("")

  const { data: negData } = useQuery({
    queryKey: ["negative-prompts", projectId],
    queryFn: () => api.getNegativePrompts(projectId),
  })

  const libraries = negData?.libraries ?? []

  const mutation = useMutation({
    mutationFn: () => {
      const prompts = text.split("\n").map((s) => s.trim()).filter(Boolean)
      return api.saveNegativePrompts(projectId, category, prompts)
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["negative-prompts", projectId] }),
  })

  const cats = [
    { key: "universal", label: "通用" },
    { key: "character", label: "角色" },
    { key: "scene", label: "场景" },
  ]

  return (
    <div className="space-y-2 p-2">
      <div className="flex gap-1">
        {cats.map((c) => (
          <button
            key={c.key}
            onClick={() => {
              setCategory(c.key)
              const lib = libraries.find((l) => l.category === c.key)
              setText((lib?.prompts || []).join("\n"))
            }}
            className={cn(
              "rounded px-2 py-0.5 text-[10px] border",
              category === c.key
                ? "bg-[#4B6EAF] text-white border-[#4B6EAF]"
                : "bg-[#3C3F41] text-[#A9B7C6] border-[#515151] hover:bg-[#4B6EAF]/30"
            )}
          >
            {c.label}
          </button>
        ))}
      </div>
      <textarea
        rows={6}
        className="w-full rounded border border-[#515151] bg-[#3C3F41] px-2 py-1 text-xs text-[#A9B7C6] placeholder:text-[#6A7579] focus:border-[#4B6EAF] focus:outline-none font-mono"
        placeholder={"low quality\nblurry\ndeformed hands"}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <button
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending}
        className="flex items-center gap-1 rounded bg-[#4B6EAF] px-2 py-1 text-[10px] text-white hover:bg-[#5A7DBF] disabled:opacity-50"
      >
        {mutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
        保存
      </button>
    </div>
  )
}

// ---- Shared Mini Input ----
function MiniInput({
  label, value, onChange, placeholder,
}: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string
}) {
  return (
    <div className="space-y-0.5">
      <label className="text-[10px] text-[#6A7579]">{label}</label>
      <input
        className="w-full rounded border border-[#515151] bg-[#3C3F41] px-2 py-1 text-xs text-[#A9B7C6] placeholder:text-[#6A7579] focus:border-[#4B6EAF] focus:outline-none"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  )
}
