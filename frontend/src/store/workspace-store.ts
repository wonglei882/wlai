import { create } from "zustand"

export type LeftPanelType = "explorer" | "bible" | null
export type BottomPanelTab = "review" | "log"

export interface CenterTab {
  id: string
  label: string
  type: "storyboard" | "shot" | "bible"
  shotId?: string
}

export interface LogEntry {
  id: string
  timestamp: string
  action: string
  target: string
  result: "success" | "error" | "info"
  detail?: string
}

interface WorkspaceState {
  // 左侧面板
  leftPanel: LeftPanelType
  // 中央 Tab
  centerTabs: CenterTab[]
  activeCenterTab: string
  // 右侧面板
  rightPanelVisible: boolean
  // 底部面板
  bottomPanelVisible: boolean
  bottomPanelTab: BottomPanelTab
  // 选中项
  selectedShotId: string | null
  selectedEpisodeId: string | null
  selectedCharacterId: string | null
  // 操作日志
  logs: LogEntry[]
  // Actions
  setLeftPanel: (panel: LeftPanelType) => void
  toggleLeftPanel: (panel: LeftPanelType) => void
  addCenterTab: (tab: CenterTab) => void
  setActiveCenterTab: (id: string) => void
  closeCenterTab: (id: string) => void
  toggleRightPanel: () => void
  setRightPanelVisible: (v: boolean) => void
  toggleBottomPanel: () => void
  setBottomPanelTab: (tab: BottomPanelTab) => void
  selectShot: (shotId: string | null) => void
  selectEpisode: (episodeId: string | null) => void
  selectCharacter: (characterId: string | null) => void
  addLog: (action: string, target: string, result: LogEntry["result"], detail?: string) => void
  clearLogs: () => void
  // 持久化
  layout: Record<string, number>
  setLayout: (layout: Record<string, number>) => void
  saveToStorage: (projectId: string) => void
  restoreFromStorage: (projectId: string) => void
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  leftPanel: "explorer",
  centerTabs: [{ id: "storyboard", label: "分镜网格", type: "storyboard" }],
  activeCenterTab: "storyboard",
  rightPanelVisible: true,
  bottomPanelVisible: true,
  bottomPanelTab: "review",
  selectedShotId: null,
  selectedEpisodeId: null,
  selectedCharacterId: null,
  logs: [],
  layout: {},

  setLeftPanel: (panel) => set({ leftPanel: panel }),

  toggleLeftPanel: (panel) =>
    set((s) => ({ leftPanel: s.leftPanel === panel ? null : panel })),

  addCenterTab: (tab) =>
    set((s) => {
      const exists = s.centerTabs.find((t) => t.id === tab.id)
      if (exists) {
        return { activeCenterTab: tab.id }
      }
      return {
        centerTabs: [...s.centerTabs, tab],
        activeCenterTab: tab.id,
      }
    }),

  setActiveCenterTab: (id) => set({ activeCenterTab: id }),

  closeCenterTab: (id) =>
    set((s) => {
      const idx = s.centerTabs.findIndex((t) => t.id === id)
      const tabs = s.centerTabs.filter((t) => t.id !== id)
      if (tabs.length === 0) return s
      let next = s.activeCenterTab
      if (next === id) {
        const fallback = tabs[Math.min(idx, tabs.length - 1)]
        next = fallback.id
      }
      return { centerTabs: tabs, activeCenterTab: next }
    }),

  toggleRightPanel: () => set((s) => ({ rightPanelVisible: !s.rightPanelVisible })),
  setRightPanelVisible: (v) => set({ rightPanelVisible: v }),
  toggleBottomPanel: () => set((s) => ({ bottomPanelVisible: !s.bottomPanelVisible })),
  setBottomPanelTab: (tab) => set({ bottomPanelTab: tab, bottomPanelVisible: true }),

  selectShot: (shotId) =>
    set((s) => ({
      selectedShotId: shotId,
      selectedCharacterId: null,
      rightPanelVisible: shotId != null,
      // 如果选中 shot，自动打开对应 tab
      ...(shotId
        ? (() => {
            const tabId = `shot-${shotId}`
            const exists = s.centerTabs.find((t) => t.id === tabId)
            if (exists) return { activeCenterTab: tabId }
            return {
              centerTabs: [
                ...s.centerTabs,
                { id: tabId, label: `镜头 #${shotId.slice(0, 6)}`, type: "shot" as const, shotId },
              ],
              activeCenterTab: tabId,
            }
          })()
        : {}),
    })),

  selectEpisode: (episodeId) => set({ selectedEpisodeId: episodeId }),

  selectCharacter: (characterId) =>
    set({
      selectedCharacterId: characterId,
      selectedShotId: null,
      rightPanelVisible: characterId != null,
    }),

  addLog: (action, target, result, detail) =>
    set((s) => ({
      logs: [
        ...s.logs.slice(-99),
        {
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
          timestamp: new Date().toLocaleTimeString(),
          action,
          target,
          result,
          detail,
        },
      ],
    })),

  clearLogs: () => set({ logs: [] }),

  setLayout: (layout) => set({ layout }),

  saveToStorage: (projectId) => {
    if (typeof window === "undefined") return
    const s = useWorkspaceStore.getState()
    const data = {
      leftPanel: s.leftPanel,
      rightPanelVisible: s.rightPanelVisible,
      bottomPanelVisible: s.bottomPanelVisible,
      bottomPanelTab: s.bottomPanelTab,
      layout: s.layout,
    }
    localStorage.setItem(`wlai_ws_${projectId}`, JSON.stringify(data))
  },

  restoreFromStorage: (projectId) => {
    if (typeof window === "undefined") return
    try {
      const raw = localStorage.getItem(`wlai_ws_${projectId}`)
      if (raw) {
        const data = JSON.parse(raw)
        set({
          leftPanel: data.leftPanel ?? "explorer",
          rightPanelVisible: data.rightPanelVisible ?? true,
          bottomPanelVisible: data.bottomPanelVisible ?? true,
          bottomPanelTab: data.bottomPanelTab ?? "review",
          layout: data.layout ?? {},
        })
      }
    } catch { /* ignore */ }
  },
}))
