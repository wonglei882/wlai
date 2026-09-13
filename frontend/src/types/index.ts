/** WLai 后端 API 类型定义 */

// ---- 认证 ----
export interface LoginRequest {
  username: string
  password: string
}

export interface RegisterRequest {
  username: string
  password: string
  display_name?: string
}

export interface User {
  id: string
  username: string
  display_name: string
  role: string
}

export interface AuthResponse {
  access_token: string
  user: User
}

// ---- 项目 ----
export interface Project {
  id: string
  user_id: string
  title: string
  description: string | null
  theme: string | null
  genre: string | null
  target_words: number
  current_words: number
  status: string
  chapter_count: number | null
  narrative_perspective: string | null
  character_count: number | null
  cover_image_url: string | null
  cover_status: string
  created_at: string
  updated_at: string
}

export interface CreateProjectRequest {
  title: string
  description?: string
  genre?: string
  target_words?: number
  theme?: string
}

// ---- PM Agent ----
export interface PMControlStatus {
  kill_switch: boolean
  pause_switch: boolean
  killed_at: string | null
  paused_at: string | null
  health?: Record<string, unknown>
}

export interface PMDecision {
  id: string
  project_id: string
  user_id: string
  diag_type: string
  severity: string
  original_message: string
  decision: string
  decision_reason: string | null
  fix_result: string | null
  fix_action: string | null
  verified: boolean
  verify_message: string | null
  user_feedback: string | null
  feedback_note: string | null
  created_at: string
}

export interface DiagnosticLog {
  id: string
  project_id: string
  diag_type: string
  severity: string
  message: string
  suggestion: string | null
  resolved: boolean
  created_at: string
}

// ---- 健康检查 ----
export interface HealthStatus {
  status: "ok" | "degraded" | "error"
  service?: string
  version?: string
  components?: Record<string, { status: string; detail?: string }>
  timestamp: number
}

// ---- 漫剧：设定圣经 ----
export interface SettingBible {
  id: string
  project_id: string
  user_id: string
  world_name: string
  summary: string | null
  time_period: string | null
  location_rules: Record<string, unknown> | null
  magic_system: Record<string, unknown> | null
  tone: string | null
  extra: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

// ---- 漫剧：角色卡 ----
export interface CharacterCard {
  id: string
  project_id: string
  user_id: string
  bible_id: string | null
  name: string
  age: string | null
  gender: string | null
  hair: string | null
  eyes: string | null
  outfit: string | null
  accessories: string[] | null
  personality: string | null
  catchphrase: string | null
  voice_timbre: string | null
  appearance_prompt: string | null
  reference_images: string[] | null
  negative_traits: string[] | null
  status: string
  created_at: string
  updated_at: string
}

// ---- 漫剧：画风卡 ----
export interface ArtStyleCard {
  id: string
  project_id: string
  user_id: string
  style_name: string
  color_palette: string[] | null
  line_style: string | null
  lighting: string | null
  base_prompt: string | null
  negative_prompt: string | null
  seed: number | null
  reference_images: string[] | null
  created_at: string
}

// ---- 漫剧：负面词库 ----
export interface NegativePromptLibrary {
  id: string
  project_id: string
  user_id: string
  category: string
  prompts: string[] | null
  created_at: string
  updated_at: string
}

// ---- 漫剧：集数 ----
export interface ComicEpisode {
  id: string
  project_id: string
  user_id: string
  episode_number: number
  title: string | null
  summary: string | null
  next_hook: string | null
  status: string
  created_at: string
  updated_at: string
}

// ---- 漫剧：分镜表 ----
export interface Storyboard {
  id: string
  project_id: string
  episode_id: string | null
  user_id: string
  title: string | null
  source_text: string | null
  shot_count: number
  status: string
  created_at: string
  updated_at: string
}

// ---- 漫剧：镜头 ----
export interface Shot {
  id: string
  project_id: string
  storyboard_id: string
  episode_id: string | null
  user_id: string
  shot_number: number
  duration: number | null
  scene_type: string | null
  visual_description: string | null
  character_action: string | null
  dialogue: string | null
  sound_effect: string | null
  camera_movement: string | null
  status: string
  compiled_prompt: string | null
  negative_prompt: string | null
  seed: number | null
  retry_count: number
  corrected_prompt: string | null
  last_consistency_score: number | null
  metadata_json: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

// ---- 漫剧：素材 ----
export interface ShotAsset {
  id: string
  shot_id: string
  project_id: string
  user_id: string
  asset_type: string
  version: number
  file_url: string | null
  prompt_used: string | null
  parameters: Record<string, unknown> | null
  status: string
  qc_result: Record<string, unknown> | null
  naming: string | null
  created_at: string
}

// ---- 通用 ----
export interface Chapter {
  id: string
  project_id: string
  chapter_number: number
  title: string
  content: string | null
  summary: string | null
  word_count: number
  status: string
  outline_id: string | null
  expansion_plan: string | null
  created_at: string
  updated_at: string
}

// ---- 通用 ----
export interface ApiResponse<T = unknown> {
  status: string
  data?: T
  error?: string
  message?: string
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}
