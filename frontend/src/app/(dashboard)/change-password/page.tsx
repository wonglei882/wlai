"use client"

import { useState, type FormEvent } from "react"
import { useRouter } from "next/navigation"
import { useAuthStore } from "@/store/auth-store"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { KeyRound } from "lucide-react"

export default function ChangePasswordPage() {
  const [oldPassword, setOldPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)
  const { changePassword } = useAuthStore()
  const router = useRouter()

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError("")
    if (newPassword !== confirm) {
      setError("两次输入的新密码不一致")
      return
    }
    if (newPassword.length < 4) {
      setError("新密码至少 4 位")
      return
    }
    setLoading(true)
    try {
      await changePassword(oldPassword, newPassword)
      router.push("/projects")
    } catch (err) {
      setError(err instanceof Error ? err.message : "修改密码失败")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="mx-auto max-w-md pt-12">
      <Card className="shadow-lg">
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
            <KeyRound className="h-6 w-6 text-primary" />
          </div>
          <CardTitle className="text-2xl">修改密码</CardTitle>
          <CardDescription>当前账号使用初始密码，为安全请先设置新密码</CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit}>
          <CardContent className="space-y-4">
            {error && (
              <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{error}</div>
            )}
            <div className="space-y-2">
              <Label htmlFor="old">当前密码</Label>
              <Input
                id="old"
                type="password"
                placeholder="请输入当前密码"
                value={oldPassword}
                onChange={(e) => setOldPassword(e.target.value)}
                required
                autoFocus
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="new">新密码</Label>
              <Input
                id="new"
                type="password"
                placeholder="至少 4 位"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirm">确认新密码</Label>
              <Input
                id="confirm"
                type="password"
                placeholder="再次输入新密码"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
              />
            </div>
          </CardContent>
          <CardFooter>
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "提交中..." : "确认修改"}
            </Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  )
}
