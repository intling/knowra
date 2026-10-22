import { createPinia, setActivePinia } from "pinia"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { makeUser } from "../__tests__/fixtures/users"
import { ApiError } from "../api/client"
import { login, logout, register } from "../api/auth"
import { changeMyPassword, getCurrentUser, updateMyProfile } from "../api/users"
import { useChatStore } from "./chat"
import { LOGOUT_SIGNAL_KEY, useUserStore } from "./user"

vi.mock("../api/users", () => ({
  getCurrentUser: vi.fn(),
  updateMyProfile: vi.fn(),
  changeMyPassword: vi.fn(),
}))

vi.mock("../api/auth", () => ({
  login: vi.fn(),
  register: vi.fn(),
  logout: vi.fn(),
}))

vi.mock("../shared/logger", () => ({
  createLogger: () => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }),
  getRingBuffer: () => ({ push: vi.fn(), size: 0, getAll: () => [] }),
}))

const getCurrentUserMock = vi.mocked(getCurrentUser)
const loginMock = vi.mocked(login)
const registerMock = vi.mocked(register)
const logoutMock = vi.mocked(logout)
const updateMyProfileMock = vi.mocked(updateMyProfile)
const changeMyPasswordMock = vi.mocked(changeMyPassword)

function unauthorized() {
  return new ApiError(401, "auth_required", "请先登录")
}

describe("useUserStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })

  // 测试：会话恢复成功后保存用户与权限，状态为 authenticated，并把对话存储绑定到该用户。
  it("ensureSession 恢复已登录用户并绑定对话空间", async () => {
    const user = makeUser("member")
    getCurrentUserMock.mockResolvedValue(user)

    const store = useUserStore()
    await store.ensureSession()

    expect(store.status).toBe("authenticated")
    expect(store.currentUser).toEqual(user)
    expect(store.userError).toBeNull()
    expect(useChatStore().ownerId).toBe(user.id)
  })

  // 测试：会话探测返回 401 时视为未登录（不是错误），不保留任何用户。
  it("ensureSession 遇到 401 进入 anonymous", async () => {
    getCurrentUserMock.mockRejectedValue(unauthorized())

    const store = useUserStore()
    await store.ensureSession()

    expect(store.status).toBe("anonymous")
    expect(store.currentUser).toBeNull()
    expect(store.userError).toBeNull()
  })

  // 测试：网络或服务错误进入 error 状态并保存可重试的错误原因，不展示任何用户资料。
  it("ensureSession 遇到网络错误进入 error", async () => {
    getCurrentUserMock.mockRejectedValue(new TypeError("Failed to fetch"))

    const store = useUserStore()
    await store.ensureSession()

    expect(store.status).toBe("error")
    expect(store.currentUser).toBeNull()
    expect(store.userError).toBe("Failed to fetch")
    expect(useChatStore().ownerId).toBeNull()
  })

  // 测试：并发调用只发起一次探测；已确定状态后不重复请求；force 时重新探测。
  it("ensureSession 单飞且可强制刷新", async () => {
    getCurrentUserMock.mockResolvedValue(makeUser("member"))
    const store = useUserStore()

    await Promise.all([store.ensureSession(), store.ensureSession()])
    await store.ensureSession()
    expect(getCurrentUserMock).toHaveBeenCalledTimes(1)

    await store.ensureSession({ force: true })
    expect(getCurrentUserMock).toHaveBeenCalledTimes(2)
  })

  // 测试：登录成功后保存用户并绑定对话；登录失败把错误抛给页面且保持未登录。
  it("login 成功建立会话，失败保持未登录", async () => {
    const store = useUserStore()
    loginMock.mockRejectedValueOnce(
      new ApiError(401, "invalid_credentials", "邮箱或密码错误"),
    )

    await expect(
      store.login({ email: "a@example.com", password: "wrong-pass-1" }),
    ).rejects.toMatchObject({
      code: "invalid_credentials",
    })
    expect(store.status).not.toBe("authenticated")
    expect(store.currentUser).toBeNull()

    const user = makeUser("viewer")
    loginMock.mockResolvedValueOnce(user)
    await store.login({
      email: "viewer@example.com",
      password: "Knowra-Pass-2026",
    })

    expect(store.status).toBe("authenticated")
    expect(store.currentUser).toEqual(user)
    expect(useChatStore().ownerId).toBe(user.id)
  })

  // 测试：注册成功即登录并绑定对话空间。
  it("register 成功后进入已登录状态", async () => {
    const user = makeUser("member", { id: "new-user" })
    registerMock.mockResolvedValue(user)

    const store = useUserStore()
    await store.register({
      display_name: "新用户",
      email: "new@example.com",
      password: "Knowra-Pass-2026",
    })

    expect(store.status).toBe("authenticated")
    expect(useChatStore().ownerId).toBe("new-user")
  })

  // 测试：退出请求服务端撤销会话，清空用户与对话内存，并写入跨标签页退出信号。
  it("logout 撤销服务端会话并清理私有状态", async () => {
    getCurrentUserMock.mockResolvedValue(makeUser("member"))
    logoutMock.mockResolvedValue(undefined)
    const store = useUserStore()
    await store.ensureSession()
    useChatStore().addConversation("私有对话")

    await store.logout()

    expect(logoutMock).toHaveBeenCalledTimes(1)
    expect(store.status).toBe("anonymous")
    expect(store.currentUser).toBeNull()
    expect(useChatStore().conversations).toEqual([])
    expect(useChatStore().ownerId).toBeNull()
    expect(localStorage.getItem(LOGOUT_SIGNAL_KEY)).toBeTruthy()
  })

  // 测试：会话失效处理只清理本地私有状态，不再请求服务端。
  it("handleUnauthorized 清理用户与对话内存", async () => {
    getCurrentUserMock.mockResolvedValue(makeUser("member"))
    const store = useUserStore()
    await store.ensureSession()
    useChatStore().addConversation("私有对话")

    store.handleUnauthorized()

    expect(store.status).toBe("anonymous")
    expect(store.currentUser).toBeNull()
    expect(useChatStore().conversations).toEqual([])
    expect(logoutMock).not.toHaveBeenCalled()
  })

  // 测试：权限判断以服务端返回的 permissions 为准，未登录时一律无权限。
  it("hasPermission 基于服务端权限集", async () => {
    const store = useUserStore()
    expect(store.hasPermission("knowledge:read")).toBe(false)

    getCurrentUserMock.mockResolvedValue(makeUser("viewer"))
    await store.ensureSession()

    expect(store.hasPermission("knowledge:read")).toBe(true)
    expect(store.hasPermission("knowledge:write")).toBe(false)
    expect(store.hasPermission("users:manage")).toBe(false)
  })

  // 测试：修改资料后更新当前用户（侧栏等处即时反映新名称）。
  it("updateProfile 更新当前用户", async () => {
    getCurrentUserMock.mockResolvedValue(makeUser("member"))
    const updated = makeUser("member", { display_name: "新名字" })
    updateMyProfileMock.mockResolvedValue(updated)
    const store = useUserStore()
    await store.ensureSession()

    await store.updateProfile({ display_name: "新名字" })

    expect(store.currentUser?.display_name).toBe("新名字")
  })

  // 测试：改密成功后服务端已撤销全部会话，前端清理私有状态并要求重新登录。
  it("changePassword 成功后清理会话", async () => {
    getCurrentUserMock.mockResolvedValue(makeUser("member"))
    changeMyPasswordMock.mockResolvedValue(undefined)
    const store = useUserStore()
    await store.ensureSession()

    await store.changePassword({
      current_password: "Old-Pass-2026",
      new_password: "New-Pass-2027",
    })

    expect(store.status).toBe("anonymous")
    expect(store.currentUser).toBeNull()
    expect(useChatStore().ownerId).toBeNull()
  })

  // 测试：同一浏览器 A 退出、B 登录后看不到 A 的对话；A 再次登录能恢复自己的历史。
  it("账号切换时对话历史按用户隔离", async () => {
    const alice = makeUser("member", { id: "alice" })
    const bob = makeUser("member", { id: "bob" })
    logoutMock.mockResolvedValue(undefined)
    const store = useUserStore()
    const chat = useChatStore()

    loginMock.mockResolvedValueOnce(alice)
    await store.login({
      email: "alice@example.com",
      password: "Knowra-Pass-2026",
    })
    chat.addConversation("Alice 的对话")
    await store.logout()

    loginMock.mockResolvedValueOnce(bob)
    await store.login({
      email: "bob@example.com",
      password: "Knowra-Pass-2026",
    })
    expect(chat.conversations).toEqual([])
    await store.logout()

    loginMock.mockResolvedValueOnce(alice)
    await store.login({
      email: "alice@example.com",
      password: "Knowra-Pass-2026",
    })
    expect(chat.conversations.map((c) => c.title)).toEqual(["Alice 的对话"])
  })
})
