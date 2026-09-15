import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /** API 代理转发：浏览器请求 → Next.js 服务器 → 后端
   *
   * Docker 环境：API_PROXY_TARGET=http://app:8000（通过 docker-compose 传入）
   * 本地开发：默认 http://127.0.0.1:8000
   */
  async rewrites() {
    const target = process.env.API_PROXY_TARGET || "http://127.0.0.1:8000"
    return [
      {
        source: "/api/:path*",
        destination: `${target}/api/:path*`,
      },
      // 健康检查路由（后端 prefix=/health，无 /api 前缀）
      {
        source: "/health",
        destination: `${target}/health`,
      },
      {
        source: "/health/:path*",
        destination: `${target}/health/:path*`,
      },
    ]
  },
}

export default nextConfig;