"use client"

import { useCallback, useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Image as ImageIcon, Plus, RefreshCw, Upload, X } from "lucide-react"
import { api } from "@/lib/api-client"
import { toast } from "@/store/toast-store"

// =============================================================================
// AssetLibraryPanel — VisGuard 角色视觉资产库
//
// 左侧面板内嵌组件：角色卡片网格 + 注册/追加/删除/展开查看参考图。
// 说明:
// - 图片一律通过 fetch + blob URL 加载（<img src> 不携带 Authorization 头，
//   后端图片端点要求 JWT，裸 <img> 会 401）。
// - 全部交互走 api-client，与后端 /api/v1/visguard/* 对齐。
// =============================================================================

// ---- 认证图片加载：fetch + blob（解决 <img> 无法带 Authorization 的问题） ----
function useAuthImage(url: string | null) {
  const [src, setSrc] = useState<string | null>(null)
  // 记录「已完成加载」的 url：loading = 有 url 且尚未加载完成（派生值，不 setState）
  const [loadedUrl, setLoadedUrl] = useState<string | null>(null)
  const loading = !!url && loadedUrl !== url

  useEffect(() => {
    if (!url) return
    let objectUrl: string | null = null
    let cancelled = false

    ;(async () => {
      try {
        const token = localStorage.getItem("wlai_token")
        const res = await fetch(url, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        })
        if (!res.ok) throw new Error(`图片加载失败 (${res.status})`)
        const blob = await res.blob()
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setSrc(objectUrl)
        setLoadedUrl(url)
      } catch {
        // 失败也标记「已完成」（src 保持 null → 渲染 fallback）
        if (!cancelled) setLoadedUrl(url)
      }
    })()

    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [url])

  return { src, loading }
}

// ---- 认证图片 <img>（封装 useAuthImage） ----
function AuthImage({
  url,
  alt,
  className,
  fallbackClassName,
}: {
  url: string | null
  alt: string
  className?: string
  fallbackClassName?: string
}) {
  const { src, loading } = useAuthImage(url)

  if (loading) {
    return (
      <div className={`flex items-center justify-center bg-[#2B2B2B] ${className ?? ""}`}>
        <RefreshCw className="h-4 w-4 animate-spin text-[#515151]" />
      </div>
    )
  }
  // url 为空或加载失败 → 占位
  if (!url || !src) {
    return (
      <div className={`flex items-center justify-center bg-[#2B2B2B] ${fallbackClassName ?? className ?? ""}`}>
        <ImageIcon className="h-5 w-5 text-[#515151]" />
      </div>
    )
  }
  // blob: URL 无法走 next/image 优化管线（需 Authorization 的私有资源也禁止外链），此处豁免
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={src} alt={alt} className={className} draggable={false} />
}

// =============================================================================
// 主面板
// =============================================================================

export function AssetLibraryPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const [showRegister, setShowRegister] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ["visguard-characters", projectId],
    queryFn: () => api.getVisGuardCharacters(projectId),
  })
  const characters = (data?.characters ?? []) as Record<string, unknown>[]

  const invalidate = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["visguard-characters", projectId] })
  }, [queryClient, projectId])

  const deleteMutation = useMutation({
    mutationFn: (characterId: string) =>
      api.deleteVisGuardCharacter(characterId, projectId),
    onSuccess: () => {
      toast.success("角色已删除")
      invalidate()
    },
    onError: () => {
      toast.error("删除角色失败")
    },
  })

  const handleDelete = (characterId: string, name: string) => {
    if (window.confirm(`确认删除角色「${name}」及其全部参考图？`)) {
      deleteMutation.mutate(characterId)
    }
  }

  return (
    <div className="flex h-full flex-col bg-[#2B2B2B] text-[#A9B7C6] text-xs">
      {/* 工具栏 */}
      <div className="flex h-7 shrink-0 items-center gap-1 border-b border-[#515151] bg-[#3C3F41] px-2">
        <span className="flex-1">
          资产库
          <span className="ml-1 text-[#6A7579]">({characters.length})</span>
        </span>
        <button
          onClick={() => setShowRegister(true)}
          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-[#6A7579] hover:bg-[#4B6EAF]/40 hover:text-[#A9B7C6]"
          title="注册新角色"
        >
          <Plus className="h-3 w-3" />
          注册
        </button>
      </div>

      {/* 角色网格 */}
      <div className="flex-1 overflow-auto p-2">
        {isLoading ? (
          <div className="flex h-full items-center justify-center text-[#6A7579]">
            <RefreshCw className="mr-1.5 h-3 w-3 animate-spin" />
            加载中...
          </div>
        ) : characters.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center text-[#6A7579]">
            <ImageIcon className="mb-2 h-8 w-8 opacity-30" />
            <p>暂无角色资产</p>
            <p className="mt-1 text-[10px] w-40">上传角色参考图，建立项目的视觉一致性资产库</p>
            <button
              onClick={() => setShowRegister(true)}
              className="mt-3 flex items-center gap-1 rounded bg-[#4B6EAF] px-2.5 py-1 text-[10px] text-white hover:bg-[#4B6EAF]/80"
            >
              <Plus className="h-3 w-3" />
              注册第一个角色
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-2">
            {characters.map((char) => (
              <CharacterCard
                key={String(char.id)}
                character={char}
                projectId={projectId}
                onDelete={() =>
                  handleDelete(String(char.id), String(char.name ?? char.id))
                }
                onChanged={invalidate}
              />
            ))}
          </div>
        )}
      </div>

      {/* 注册弹窗 */}
      {showRegister && (
        <RegisterOverlay
          projectId={projectId}
          onClose={() => setShowRegister(false)}
          onSuccess={() => {
            setShowRegister(false)
            invalidate()
          }}
        />
      )}
    </div>
  )
}

// =============================================================================
// 角色卡片
// =============================================================================

function CharacterCard({
  character,
  projectId,
  onDelete,
  onChanged,
}: {
  character: Record<string, unknown>
  projectId: string
  onDelete: () => void
  onChanged: () => void
}) {
  const characterId = String(character.id)
  const name = String(character.name ?? characterId)
  const imageCount = Number(character.image_count ?? 0)
  const [expanded, setExpanded] = useState(false)

  // 展开或封面需要图片时加载图片列表
  const { data: imagesData, isLoading: imagesLoading } = useQuery({
    queryKey: ["visguard-images", characterId, projectId],
    queryFn: () => api.getVisGuardCharacterImages(characterId, projectId),
    enabled: expanded || imageCount > 0,
  })
  const imageIds = (imagesData?.image_ids ?? []) as string[]

  // 封面 = 第一张参考图（grid 缩略）+ 展开区复用同一列表
  const coverId = imageIds[0] ?? null
  const coverUrl = coverId
    ? api.getVisGuardImageUrl(characterId, coverId, projectId)
    : null

  // 追加图片 mutation
  const queryClient = useQueryClient()
  const addImageMutation = useMutation({
    mutationFn: (file: File) =>
      api.addVisGuardCharacterImage(characterId, projectId, file),
    onSuccess: () => {
      toast.success("参考图已追加")
      queryClient.invalidateQueries({ queryKey: ["visguard-images", characterId, projectId] })
      queryClient.invalidateQueries({ queryKey: ["visguard-characters", projectId] })
      onChanged()
    },
    onError: () => {
      toast.error("追加失败")
    },
  })

  const handleAddImage = (file: File | undefined) => {
    if (file) addImageMutation.mutate(file)
  }

  return (
    <div
      className={`rounded border transition-all ${
        expanded
          ? "border-[#4B6EAF] bg-[#4B6EAF]/10"
          : "border-[#515151] bg-[#3C3F41] hover:border-[#6A7579]"
      }`}
    >
      {/* 封面（点击展开） */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="block w-full cursor-pointer text-left"
        title={expanded ? "收起" : "查看参考图"}
      >
        <div className="flex aspect-square items-center justify-center overflow-hidden">
          {expanded ? null : (
            <AuthImage url={coverUrl} alt={name} className="h-full w-full object-cover" />
          )}
        </div>
        <div className="px-1.5 py-1">
          <p className="truncate text-[11px] font-medium">{name}</p>
          <p className="text-[9px] text-[#6A7579]">
            {imageCount} 张参考图
          </p>
        </div>
      </button>

      {/* 展开区：全部参考图 + 追加/删除 */}
      {expanded && (
        <div className="border-t border-[#515151] p-1.5">
          {imagesLoading ? (
            <div className="flex items-center justify-center py-3 text-[#6A7579]">
              <RefreshCw className="mr-1 h-3 w-3 animate-spin" />
              加载中...
            </div>
          ) : imageIds.length === 0 ? (
            <p className="py-2 text-center text-[10px] text-[#6A7579]">暂无参考图</p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {imageIds.map((imgId) => (
                <div key={imgId} className="h-14 w-10 overflow-hidden rounded border border-[#515151]">
                  <AuthImage
                    url={api.getVisGuardImageUrl(characterId, imgId, projectId)}
                    alt={`${name} ${imageIds.indexOf(imgId) + 1}`}
                    className="h-full w-full object-cover"
                    fallbackClassName="h-full w-full"
                  />
                </div>
              ))}
            </div>
          )}

          {/* 操作行 */}
          <div className="mt-2 flex items-center gap-1">
            <label className="cursor-pointer rounded bg-[#4B6EAF]/30 px-2 py-1 text-[10px] hover:bg-[#4B6EAF]/50">
              追加图片
              <input
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => {
                  handleAddImage(e.target.files?.[0])
                  e.target.value = ""
                }}
              />
            </label>
            <button
              onClick={onDelete}
              className="rounded bg-red-500/20 px-2 py-1 text-[10px] text-red-400 hover:bg-red-500/40 hover:text-red-300"
            >
              删除角色
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// =============================================================================
// 注册弹窗
// =============================================================================

function RegisterOverlay({
  projectId,
  onClose,
  onSuccess,
}: {
  projectId: string
  onClose: () => void
  onSuccess: () => void
}) {
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)

  const registerMutation = useMutation({
    mutationFn: (data: { name: string; image: File; description?: string }) =>
      api.registerVisGuardCharacter(projectId, data.name, data.image, data.description),
    onSuccess: () => {
      toast.success("角色注册成功")
      onSuccess()
    },
    onError: () => {
      toast.error("角色注册失败")
    },
  })

  // 清理预览 blob
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl)
    }
  }, [previewUrl])

  const handleFile = (f: File | undefined) => {
    if (!f) return
    setFile(f)
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    setPreviewUrl(URL.createObjectURL(f))
  }

  const handleSubmit = () => {
    if (!name.trim()) {
      toast.warning("请输入角色名称")
      return
    }
    if (!file) {
      toast.warning("请选择参考图")
      return
    }
    registerMutation.mutate({
      name: name.trim(),
      image: file,
      description: description.trim() || undefined,
    })
  }

  return (
    <div
      className="absolute inset-0 z-10 flex items-center justify-center bg-black/50"
      onClick={onClose}
    >
      <div
        className="w-72 rounded-lg border border-[#515151] bg-[#3C3F41] shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 标题栏 */}
        <div className="flex items-center justify-between border-b border-[#515151] px-3 py-2">
          <span className="text-[12px] font-medium">注册角色</span>
          <button
            onClick={onClose}
            className="rounded p-0.5 text-[#6A7579] hover:bg-[#4B6EAF]/30 hover:text-[#A9B7C6]"
            title="关闭"
          >
            <X className="h-3 w-3" />
          </button>
        </div>

        <div className="space-y-2 p-3">
          {/* 图片选择 */}
          <label className="block cursor-pointer overflow-hidden rounded border border-dashed border-[#515151] bg-[#2B2B2B] hover:border-[#4B6EAF]/60">
            {previewUrl ? (
              // 本地 blob: 预览，next/image 无法处理 blob: 协议 → 豁免
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={previewUrl}
                alt="预览"
                className="mx-auto h-40 object-contain"
              />
            ) : (
              <div className="flex h-32 flex-col items-center justify-center text-[#6A7579]">
                <Upload className="mb-1 h-5 w-5" />
                <span className="text-[10px]">点击选择参考图</span>
                <span className="mt-0.5 text-[9px]">JPG / PNG，≤10MB</span>
              </div>
            )}
            <input
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => handleFile(e.target.files?.[0])}
            />
          </label>

          {/* 名称 */}
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="角色名称（必填）"
            className="w-full rounded border border-[#515151] bg-[#2B2B2B] px-2 py-1.5 text-[11px] outline-none placeholder:text-[#6A7579] focus:border-[#4B6EAF]"
          />

          {/* 描述 */}
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="角色描述（可选）"
            rows={2}
            className="w-full resize-none rounded border border-[#515151] bg-[#2B2B2B] px-2 py-1.5 text-[11px] outline-none placeholder:text-[#6A7579] focus:border-[#4B6EAF]"
          />

          {/* 提交 */}
          <button
            onClick={handleSubmit}
            disabled={registerMutation.isPending}
            className="w-full rounded bg-[#4B6EAF] py-1.5 text-[11px] font-medium text-white hover:bg-[#4B6EAF]/80 disabled:opacity-50"
          >
            {registerMutation.isPending ? "注册中..." : "确认注册"}
          </button>
        </div>
      </div>
    </div>
  )
}