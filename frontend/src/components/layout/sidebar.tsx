"use client"

import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import { cn } from "@/lib/utils"
import { useAuthStore } from "@/store/auth-store"
import {
  LayoutDashboard,
  BookOpen,
  Film,
  Shield,
  Settings,
  LogOut,
  ChevronLeft,
  ChevronRight,
  BarChart3,
} from "lucide-react"
import { useState } from "react"

const navItems = [
  { href: "/projects", label: "项目", icon: LayoutDashboard },
  { href: "/novel", label: "小说工作台", icon: BookOpen },
  { href: "/comic", label: "漫剧工作台", icon: Film },
  { href: "/pm", label: "PM Agent", icon: Shield },
  { href: "/token-usage", label: "用量统计", icon: BarChart3 },
  { href: "/settings", label: "设置", icon: Settings },
]

export function Sidebar() {
  const pathname = usePathname()
  const router = useRouter()
  const { user, logout } = useAuthStore()
  const [collapsed, setCollapsed] = useState(false)

  const handleLogout = () => {
    logout()
    router.push("/login")
  }

  return (
    <aside
      className={cn(
        "flex flex-col border-r bg-background transition-all duration-200",
        collapsed ? "w-16" : "w-64"
      )}
    >
      {/* Logo */}
      <div className="flex h-14 items-center border-b px-4">
        <Link href="/projects" className="flex items-center gap-2 font-bold text-lg">
          <Shield className="h-6 w-6 text-primary" />
          {!collapsed && <span>WLai</span>}
        </Link>
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="ml-auto rounded-md p-1 hover:bg-accent"
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 p-2">
        {navItems.map((item) => {
          const isActive = pathname.startsWith(item.href)
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              )}
            >
              <item.icon className="h-4 w-4 shrink-0" />
              {!collapsed && <span>{item.label}</span>}
            </Link>
          )
        })}
      </nav>

      {/* User */}
      <div className="border-t p-2">
        <div className={cn("flex items-center gap-2 rounded-md px-3 py-2", collapsed && "justify-center")}>
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground text-sm font-bold">
            {user?.display_name?.[0] || user?.username?.[0] || "?"}
          </div>
          {!collapsed && (
            <div className="flex-1 truncate">
              <p className="text-sm font-medium truncate">{user?.display_name || user?.username}</p>
            </div>
          )}
          {!collapsed && (
            <button onClick={handleLogout} className="rounded-md p-1 hover:bg-accent" title="退出登录">
              <LogOut className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </aside>
  )
}
