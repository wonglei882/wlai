"use client"

import { useEffect } from "react"
import { usePathname, useRouter } from "next/navigation"
import { useAuthStore } from "@/store/auth-store"
import { Sidebar } from "@/components/layout/sidebar"
import { Header } from "@/components/layout/header"
import { Skeleton } from "@/components/ui/skeleton"

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading, mustChangePassword, checkAuth } = useAuthStore()
  const router = useRouter()
  const pathname = usePathname()

  useEffect(() => {
    checkAuth()
  }, [checkAuth])

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push("/login")
    }
  }, [isLoading, isAuthenticated, router])

  useEffect(() => {
    if (isAuthenticated && mustChangePassword && pathname !== "/change-password") {
      router.push("/change-password")
    }
  }, [isAuthenticated, mustChangePassword, pathname, router])

  if (isLoading) {
    return (
      <div className="flex h-screen overflow-hidden">
        {/* 侧边栏骨架 */}
        <div className="w-14 border-r border-[#515151] bg-[#3C3F41] p-2 space-y-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-8 w-8 mx-auto" />
          ))}
        </div>
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* 头部骨架 */}
          <div className="h-12 border-b border-[#515151] bg-[#3C3F41] flex items-center px-4">
            <Skeleton className="h-5 w-32" />
          </div>
          {/* 内容区骨架 */}
          <main className="flex-1 overflow-auto p-6 space-y-4">
            <Skeleton className="h-8 w-48" />
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-32 w-full rounded-lg" />
              ))}
            </div>
          </main>
        </div>
      </div>
    )
  }

  if (!isAuthenticated) {
    return null
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Header />
        <main className="flex-1 overflow-auto p-6">{children}</main>
      </div>
    </div>
  )
}
