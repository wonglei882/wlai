"use client"

import { use, useEffect } from "react"
import { Group, Panel, Separator } from "react-resizable-panels"
import { useWorkspaceStore } from "@/store/workspace-store"
import { ToolWindowBar } from "@/components/workspace/tool-window-bar"
import { TabBar } from "@/components/workspace/tab-bar"
import { ToolWindow } from "@/components/workspace/tool-window"
import { ExplorerPanel } from "@/components/workspace/explorer-panel"
import { BiblePanel } from "@/components/workspace/bible-panel"
import { StoryboardEditor } from "@/components/workspace/storyboard-editor"
import { ShotEditor } from "@/components/workspace/shot-editor"
import { PropertiesPanel } from "@/components/workspace/properties-panel"
import { ReviewConsole } from "@/components/workspace/review-console"
import { OutputLog } from "@/components/workspace/output-log"
import { StatusBar } from "@/components/workspace/status-bar"
import { cn } from "@/lib/utils"

// JetBrains Darcula theme colors
// bg: #2B2B2B, panel: #3C3F41, border: #515151, accent: #4B6EAF, text: #A9B7C6

export default function ComicWorkspacePage({ params }: { params: Promise<{ id: string }> }) {
  const { id: projectId } = use(params)
  const {
    leftPanel, centerTabs, activeCenterTab,
    rightPanelVisible, bottomPanelVisible, bottomPanelTab,
    setBottomPanelTab, toggleBottomPanel,
    restoreFromStorage, saveToStorage, setLayout,
  } = useWorkspaceStore()

  // 恢复持久化状态
  useEffect(() => {
    restoreFromStorage(projectId)
  }, [projectId, restoreFromStorage])

  // 布局变化时保存
  const handleLayoutChanged = (layout: Record<string, number>) => {
    setLayout(layout)
    saveToStorage(projectId)
  }

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col bg-[#2B2B2B]">
      {/* Main panel area */}
      <Group orientation="horizontal" className="flex-1" onLayoutChanged={handleLayoutChanged}>
        {/* Tool Window Bar (left icon strip) */}
        <ToolWindowBar />

        {/* Left Panel (Explorer / Bible) */}
        {leftPanel && (
          <>
            <Panel defaultSize={20} minSize={12} maxSize={35} id="left-panel">
              <ToolWindow
                title={leftPanel === "explorer" ? "资源管理器" : "设定圣经"}
              >
                {leftPanel === "explorer" ? (
                  <ExplorerPanel projectId={projectId} />
                ) : (
                  <BiblePanel projectId={projectId} />
                )}
              </ToolWindow>
            </Panel>
            <Separator className="w-1 bg-[#515151] data-[separator=true]:bg-[#4B6EAF]" />
          </>
        )}

        {/* Center + Right area */}
        <Panel defaultSize={60} minSize={30} id="center-area">
          <Group orientation="vertical" className="h-full">
            {/* Center Editor + Properties */}
            <Panel defaultSize={70} minSize={30} id="editor-area">
              <Group orientation="horizontal" className="h-full">
                {/* Center Editor */}
                <Panel defaultSize={70} minSize={20} id="center-editor">
                  <div className="flex h-full flex-col bg-[#2B2B2B]">
                    <TabBar />
                    <div className="flex-1 overflow-hidden">
                      <CenterContent projectId={projectId} />
                    </div>
                  </div>
                </Panel>

                {/* Properties Panel */}
                {rightPanelVisible && (
                  <>
                    <Separator className="w-1 bg-[#515151]" />
                    <Panel defaultSize={30} minSize={15} maxSize={45} id="properties">
                      <ToolWindow title="属性">
                        <PropertiesPanel projectId={projectId} />
                      </ToolWindow>
                    </Panel>
                  </>
                )}
              </Group>
            </Panel>

            {/* Bottom Panel (Review + Log) */}
            {bottomPanelVisible && (
              <>
                <Separator className="h-1 bg-[#515151]" />
                <Panel defaultSize={30} minSize={10} maxSize={50} id="bottom-panel">
                  <div className="flex h-full flex-col bg-[#2B2B2B]">
                    {/* Bottom tab bar */}
                    <div className="flex h-7 shrink-0 items-center border-b border-[#515151] bg-[#3C3F41]">
                      <button
                        onClick={() => setBottomPanelTab("review")}
                        className={cn(
                          "h-full px-3 text-[11px] font-medium border-b-2 transition-colors",
                          bottomPanelTab === "review"
                            ? "border-[#4B6EAF] text-[#A9B7C6]"
                            : "border-transparent text-[#6A7579] hover:text-[#A9B7C6]"
                        )}
                      >
                        审核控制台
                      </button>
                      <button
                        onClick={() => setBottomPanelTab("log")}
                        className={cn(
                          "h-full px-3 text-[11px] font-medium border-b-2 transition-colors",
                          bottomPanelTab === "log"
                            ? "border-[#4B6EAF] text-[#A9B7C6]"
                            : "border-transparent text-[#6A7579] hover:text-[#A9B7C6]"
                        )}
                      >
                        输出日志
                      </button>
                      <div className="ml-auto pr-2">
                        <button
                          onClick={toggleBottomPanel}
                          className="rounded p-0.5 text-[#6A7579] hover:text-[#A9B7C6]"
                          title="关闭面板"
                        >
                          ×
                        </button>
                      </div>
                    </div>
                    {/* Bottom content */}
                    <div className="flex-1 overflow-hidden">
                      {bottomPanelTab === "review" ? (
                        <ReviewConsole projectId={projectId} />
                      ) : (
                        <OutputLog />
                      )}
                    </div>
                  </div>
                </Panel>
              </>
            )}
          </Group>
        </Panel>
      </Group>

      {/* Status Bar */}
      <StatusBar projectId={projectId} />
    </div>
  )
}

// ---- Center content router ----
function CenterContent({ projectId }: { projectId: string }) {
  const { centerTabs, activeCenterTab } = useWorkspaceStore()
  const activeTab = centerTabs.find((t) => t.id === activeCenterTab)

  if (!activeTab) {
    return (
      <div className="flex h-full items-center justify-center text-[#6A7579]">
        选择一个标签页开始编辑
      </div>
    )
  }

  switch (activeTab.type) {
    case "storyboard":
      return <StoryboardEditor projectId={projectId} />
    case "shot":
      return activeTab.shotId ? (
        <ShotEditor projectId={projectId} shotId={activeTab.shotId} />
      ) : null
    case "bible":
      return <BiblePanel projectId={projectId} />
    default:
      return null
  }
}
