/** WLai 后端 API 客户端 */

import { toast } from "@/store/toast-store"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE}${path}`
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  }

  // 附加 JWT token（认证）
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("wlai_token")
    if (token && !headers["Authorization"]) {
      headers["Authorization"] = `Bearer ${token}`
    }
  }

  let res: Response
  try {
    res = await fetch(url, {
      ...options,
      headers,
    })
  } catch {
    // 网络不可达
    if (typeof window !== "undefined") {
      toast.error("无法连接后端服务")
    }
    throw new ApiError("无法连接后端服务", 0)
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const message = body.message || body.error || `请求失败 (${res.status})`

    // 401: token 过期，跳转登录
    if (res.status === 401 && typeof window !== "undefined") {
      localStorage.removeItem("wlai_token")
      window.location.href = "/login"
      throw new ApiError(message, res.status)
    }

    // 全局错误提示
    if (typeof window !== "undefined") {
      toast.error(message)
    }
    throw new ApiError(message, res.status)
  }

  return res.json()
}

export const api = {
  // ---- 认证 ----
  login: (username: string, password: string) =>
    request<{ access_token: string; must_change_password?: boolean }>("api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  register: (username: string, password: string, displayName?: string) =>
    request<{ access_token: string; must_change_password?: boolean }>("api/auth/register", {
      method: "POST",
      body: JSON.stringify({
        username,
        password,
        display_name: displayName,
      }),
    }),

  me: () => request<{ id: string; username: string; display_name: string; role: string; must_change_password?: boolean }>("api/auth/me"),

  changePassword: (oldPassword: string, newPassword: string) =>
    request<{ access_token: string }>("api/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
    }),

  // ---- 项目 ----
  getProjects: () =>
    request<{ projects: import("@/types").Project[] }>("api/projects"),

  getProject: (id: string) =>
    request<import("@/types").Project>(`api/projects/${id}`),

  createProject: (data: import("@/types").CreateProjectRequest) =>
    request<import("@/types").Project>("api/projects", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  updateProject: (id: string, data: Partial<import("@/types").CreateProjectRequest>) =>
    request<import("@/types").Project>(`api/projects/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  deleteProject: (id: string) =>
    request<void>(`api/projects/${id}`, { method: "DELETE" }),

  // ---- PM Agent 控制 ----
  getPMStatus: () =>
    request<import("@/types").PMControlStatus>("api/pm-control/status"),

  pmKill: () =>
    request<import("@/types").PMControlStatus>("api/pm-control/kill", { method: "POST" }),

  pmPause: () =>
    request<import("@/types").PMControlStatus>("api/pm-control/pause", { method: "POST" }),

  pmResume: () =>
    request<import("@/types").PMControlStatus>("api/pm-control/resume", { method: "POST" }),

  // ---- PM 诊断面板 ----
  getPMDashboard: (projectId: string, userId: string) =>
    request<Record<string, unknown>>(
      `api/pm/dashboard/${projectId}?user_id=${userId}`
    ),

  getDiagnosticSummary: (projectId: string) =>
    request<Record<string, unknown>>(
      `api/pm-diagnostic-logs/summary?project_id=${projectId}`
    ),

  getDiagnosticLogs: (projectId: string, limit = 20) =>
    request<{ total: number; items: import("@/types").DiagnosticLog[] }>(
      `api/pm-diagnostic-logs?project_id=${projectId}&limit=${limit}`
    ),

  getFixReport: (projectId: string, hours = 2) =>
    request<{ total: number; items: Record<string, unknown>[] }>(
      `api/pm-diagnostic-logs/report?project_id=${projectId}&hours=${hours}`
    ),

  submitFixFeedback: (logId: string, action: string, note?: string) =>
    request<{ ok: boolean }>(`api/pm-diagnostic-logs/${logId}/feedback`, {
      method: "POST",
      body: JSON.stringify({ action, note: note || "" }),
    }),

  resolveDiagnostic: (logId: string) =>
    request<{ ok: boolean }>(`api/pm-diagnostic-logs/${logId}/resolve`, {
      method: "POST",
    }),

  // ---- PM 决策 ----
  getDecisions: (projectId: string, limit = 50) =>
    request<{ decisions: import("@/types").PMDecision[] }>(
      `api/pm/decisions?project_id=${projectId}&limit=${limit}`
    ),

  submitDecisionFeedback: (decisionId: string, feedback: string, comment?: string) =>
    request<Record<string, unknown>>(
      `api/pm/decisions/${decisionId}/feedback?feedback=${feedback}&comment=${encodeURIComponent(comment || "")}`,
      { method: "POST" }
    ),

  // ---- PM 自主度 ----
  getAutonomyConfig: (projectId: string, userId: string) =>
    request<Record<string, unknown>>(
      `api/pm/autonomy/${projectId}?user_id=${userId}`
    ),

  setAutonomyConfig: (projectId: string, userId: string, level: string, threshold: number, types?: string) =>
    request<Record<string, unknown>>(
      `api/pm/autonomy/${projectId}?user_id=${userId}&level=${level}&confidence_threshold=${threshold}&auto_execute_types=${types || "outline,suggest,foreshadow,character,world_setting"}`,
      { method: "POST" }
    ),

  // ---- PM 巡检 ----
  inspectProject: (projectId: string, userId: string) =>
    request<Record<string, unknown>>(
      `api/pm/inspect/${projectId}?user_id=${userId}`
    ),

  triggerRerun: () =>
    request<Record<string, unknown>>("api/pm/rerun", { method: "POST" }),

  getSuggestions: (projectId: string, userId: string) =>
    request<{ suggestions: Record<string, unknown>[]; total: number }>(
      `api/pm/suggestions/${projectId}?user_id=${userId}`
    ),

  getProactiveReport: (projectId: string, userId: string) =>
    request<Record<string, unknown>>(
      `api/pm/proactive-report/${projectId}?user_id=${userId}`
    ),

  // ---- PM Token 用量 ----
  getTokenSummary: (days = 7, projectId?: string) =>
    request<Record<string, unknown>>(
      `api/pm-token-usage/summary?days=${days}${projectId ? `&project_id=${projectId}` : ""}`
    ),

  getTokenTrend: (days = 7, projectId?: string) =>
    request<Record<string, unknown>>(
      `api/pm-token-usage/trend?days=${days}${projectId ? `&project_id=${projectId}` : ""}`
    ),

  // ---- 小说：章节 ----
  listChapters: (projectId: string) =>
    request<{ chapters: import("@/types").Chapter[]; total: number }>(
      `api/v1/novel/chapters?project_id=${projectId}`
    ),

  createChapter: (data: { project_id: string; chapter_number: number; title: string; content?: string }) =>
    request<import("@/types").Chapter>("api/v1/novel/chapters", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  getChapter: (chapterId: string) =>
    request<import("@/types").Chapter>(`api/v1/novel/chapters/${chapterId}`),

  updateChapter: (chapterId: string, data: { title?: string; content?: string; summary?: string }) =>
    request<import("@/types").Chapter>(`api/v1/novel/chapters/${chapterId}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  deleteChapter: (chapterId: string) =>
    request<{ ok: boolean }>(`api/v1/novel/chapters/${chapterId}`, {
      method: "DELETE",
    }),

  // ---- 漫剧：设定圣经 ----
  createBible: (data: Record<string, unknown>) =>
    request<Record<string, unknown>>("api/v1/comic/bibles", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  getBible: (bibleId: string) =>
    request<Record<string, unknown>>(`api/v1/comic/bibles/${bibleId}`),

  updateBible: (bibleId: string, data: Record<string, unknown>) =>
    request<Record<string, unknown>>(`api/v1/comic/bibles/${bibleId}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  // ---- 漫剧：角色卡 ----
  createCharacter: (data: Record<string, unknown>) =>
    request<Record<string, unknown>>("api/v1/comic/characters", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  listCharacters: (projectId: string) =>
    request<{ characters: import("@/types").CharacterCard[]; total: number }>(
      `api/v1/comic/characters?project_id=${projectId}`
    ),

  updateCharacter: (charId: string, data: Record<string, unknown>) =>
    request<Record<string, unknown>>(`api/v1/comic/characters/${charId}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  lockCharacter: (charId: string) =>
    request<Record<string, unknown>>(`api/v1/comic/characters/${charId}/lock`, {
      method: "POST",
    }),

  // ---- 漫剧：画风卡 ----
  createStyle: (data: Record<string, unknown>) =>
    request<Record<string, unknown>>("api/v1/comic/styles", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  getStyle: (projectId: string) =>
    request<Record<string, unknown>>(`api/v1/comic/styles/${projectId}`),

  // ---- 漫剧：负面词库 ----
  saveNegativePrompts: (projectId: string, category: string, prompts: string[]) =>
    request<Record<string, unknown>>("api/v1/comic/negative-prompts", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, category, prompts }),
    }),

  getNegativePrompts: (projectId: string) =>
    request<{ libraries: import("@/types").NegativePromptLibrary[]; total: number }>(
      `api/v1/comic/negative-prompts/${projectId}`
    ),

  // ---- 漫剧：集数 ----
  createEpisode: (data: Record<string, unknown>) =>
    request<Record<string, unknown>>("api/v1/comic/episodes", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  listEpisodes: (projectId: string) =>
    request<{ episodes: import("@/types").ComicEpisode[]; total: number }>(
      `api/v1/comic/episodes?project_id=${projectId}`
    ),

  updateEpisode: (episodeId: string, data: Record<string, unknown>) =>
    request<Record<string, unknown>>(`api/v1/comic/episodes/${episodeId}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  // ---- 漫剧：分镜 ----
  generateStoryboard: (data: Record<string, unknown>) =>
    request<Record<string, unknown>>("api/v1/comic/storyboards/generate", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  getStoryboard: (storyboardId: string) =>
    request<Record<string, unknown>>(`api/v1/comic/storyboards/${storyboardId}`),

  confirmStoryboard: (storyboardId: string) =>
    request<Record<string, unknown>>(`api/v1/comic/storyboards/${storyboardId}/confirm`, {
      method: "POST",
    }),

  // ---- 漫剧：镜头 ----
  getShotsByProject: (projectId: string) =>
    request<{ shots: Record<string, unknown>[]; total: number }>(
      `api/v1/comic/shots?project_id=${projectId}`
    ),

  getShotsByStoryboard: (storyboardId: string) =>
    request<{ shots: Record<string, unknown>[]; total: number }>(
      `api/v1/comic/shots?storyboard_id=${storyboardId}`
    ),

  updateShotStatus: (shotId: string, targetStatus: string) =>
    request<Record<string, unknown>>(`api/v1/comic/shots/${shotId}/status`, {
      method: "PUT",
      body: JSON.stringify({ target_status: targetStatus }),
    }),

  compileShotPrompt: (shotId: string, platform = "midjourney") =>
    request<Record<string, unknown>>(`api/v1/comic/shots/${shotId}/compile`, {
      method: "POST",
      body: JSON.stringify({ platform }),
    }),

  // ---- 漫剧：素材 ----
  createAsset: (data: Record<string, unknown>) =>
    request<Record<string, unknown>>("api/v1/comic/assets", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  listAssets: (shotId: string) =>
    request<{ assets: Record<string, unknown>[]; total: number }>(
      `api/v1/comic/assets?shot_id=${shotId}`
    ),

  // ---- 漫剧：审核 ----
  getReviews: (projectId: string, status = "pending") =>
    request<{ reviews: Record<string, unknown>[]; total: number }>(
      `api/v1/comic/reviews?project_id=${projectId}&status=${status}`
    ),

  updateReview: (reviewId: string, status: string, notes?: string) =>
    request<Record<string, unknown>>(`api/v1/comic/reviews/${reviewId}`, {
      method: "PUT",
      body: JSON.stringify({ status, reviewer_notes: notes || "" }),
    }),

  // ---- 健康检查 ----
  health: () => request<import("@/types").HealthStatus>("health"),
  healthReady: () => request<import("@/types").HealthStatus>("health/ready"),
}

export { ApiError }
