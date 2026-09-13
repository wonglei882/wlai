import Link from "next/link"
import { Shield, BookOpen, Film, Scan, GitBranch, Eye, Zap } from "lucide-react"

export default function HomePage() {
  return (
    <div className="flex flex-col min-h-screen">
      {/* Nav */}
      <header className="border-b">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
          <div className="flex items-center gap-2 font-bold text-xl">
            <Shield className="h-6 w-6 text-primary" />
            <span>WLai</span>
          </div>
          <div className="flex items-center gap-4">
            <Link
              href="/login"
              className="text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              登录
            </Link>
            <Link href="/register">
              <button className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors">
                免费开始
              </button>
            </Link>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="flex-1">
        <div className="mx-auto max-w-6xl px-6 py-24 text-center">
          <h1 className="text-5xl font-bold tracking-tight sm:text-6xl">
            让 AI <span className="text-primary">不敢乱来</span>
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-lg text-muted-foreground leading-8">
            AI 内容一致性守护平台 — 外置记忆 + 提示词编译 + 人工审核 + 反馈闭环
            <br />
            支持长篇小说和 AI 漫剧制片两大场景
          </p>
          <div className="mt-10 flex items-center justify-center gap-4">
            <Link href="/register">
              <button className="rounded-lg bg-primary px-8 py-3 text-base font-medium text-primary-foreground hover:bg-primary/90 transition-colors">
                立即体验
              </button>
            </Link>
            <a
              href="https://github.com"
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-lg border px-8 py-3 text-base font-medium hover:bg-accent transition-colors"
            >
              GitHub
            </a>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="border-t bg-muted/50">
        <div className="mx-auto max-w-6xl px-6 py-20">
          <h2 className="text-center text-3xl font-bold tracking-tight">核心能力</h2>
          <p className="mt-3 text-center text-muted-foreground">
            从巡检到修复的全自动闭环，守护你的 AI 内容质量
          </p>
          <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            <FeatureCard
              icon={<Scan className="h-6 w-6" />}
              title="自主巡检"
              description="PM Agent 自动扫描所有项目，检测一致性问题，无需人工干预"
            />
            <FeatureCard
              icon={<Eye className="h-6 w-6" />}
              title="多维诊断"
              description="角色一致性、场景连续性、伏笔追踪、剧情连贯性四维扫描"
            />
            <FeatureCard
              icon={<Zap className="h-6 w-6" />}
              title="自动修复"
              description="发现问题后自动触发修复流程，验证通过后才提交"
            />
            <FeatureCard
              icon={<BookOpen className="h-6 w-6" />}
              title="小说工作台"
              description="章节编辑器、角色管理、伏笔看板，完整的长篇小说创作工具"
            />
            <FeatureCard
              icon={<Film className="h-6 w-6" />}
              title="漫剧制片"
              description="设定圣经、分镜工作台、审核工作流，AI 漫剧全流程管理"
            />
            <FeatureCard
              icon={<GitBranch className="h-6 w-6" />}
              title="经验进化"
              description="修复模式库、画像学习、引导反馈，Agent 越用越聪明"
            />
          </div>
        </div>
      </section>

      {/* Architecture */}
      <section className="border-t">
        <div className="mx-auto max-w-6xl px-6 py-20 text-center">
          <h2 className="text-3xl font-bold tracking-tight">巡检 → 诊断 → 修复 → 验证</h2>
          <p className="mt-3 text-muted-foreground">
            事件总线驱动的全自动闭环，确保 AI 生成内容的每一处细节都经得起检验
          </p>
          <div className="mt-12 flex flex-wrap items-center justify-center gap-4 text-sm">
            <div className="rounded-lg border bg-card px-6 py-4 shadow-sm">
              <p className="font-semibold">事件触发</p>
              <p className="text-muted-foreground">定时 / 手动 / Webhook</p>
            </div>
            <span className="text-2xl text-muted-foreground">→</span>
            <div className="rounded-lg border bg-card px-6 py-4 shadow-sm">
              <p className="font-semibold">四维扫描</p>
              <p className="text-muted-foreground">角色 / 场景 / 伏笔 / 剧情</p>
            </div>
            <span className="text-2xl text-muted-foreground">→</span>
            <div className="rounded-lg border bg-card px-6 py-4 shadow-sm">
              <p className="font-semibold">智能决策</p>
              <p className="text-muted-foreground">严重度评估 + 修复方案</p>
            </div>
            <span className="text-2xl text-muted-foreground">→</span>
            <div className="rounded-lg border bg-card px-6 py-4 shadow-sm">
              <p className="font-semibold">自动修复</p>
              <p className="text-muted-foreground">执行修复 + 验证通过</p>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t">
        <div className="mx-auto max-w-6xl px-6 py-8 text-center text-sm text-muted-foreground">
          <p>WLai — 开源自部署 AI 内容一致性守护平台</p>
          <p className="mt-2">Docker 一键部署 · 数据完全自控 · 支持本地多模态模型</p>
        </div>
      </footer>
    </div>
  )
}

function FeatureCard({ icon, title, description }: { icon: React.ReactNode; title: string; description: string }) {
  return (
    <div className="rounded-lg border bg-card p-6 shadow-sm transition-shadow hover:shadow-md">
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-md bg-primary/10 text-primary">
        {icon}
      </div>
      <h3 className="font-semibold">{title}</h3>
      <p className="mt-2 text-sm text-muted-foreground leading-relaxed">{description}</p>
    </div>
  )
}
