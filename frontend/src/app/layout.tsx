import type { Metadata } from "next"
import { GeistSans } from "geist/font/sans"
import { GeistMono } from "geist/font/mono"
import "./globals.css"
import { Providers } from "./providers"

const geistSans = GeistSans
const geistMono = GeistMono

export const metadata: Metadata = {
  title: "WLai - AI 内容一致性守护 + AI 漫剧制片",
  description: "让 AI 不敢乱来 — 外置记忆 + 提示词编译 + 人工审核 + 反馈闭环",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="zh-CN"
      className={`dark ${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col">
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
