# knowra 前端章程

## 1. 项目定位与目标
**knowra 前端** 是 knowra 项目的前端部分，基于 Vue 3 + TypeScript + Vite 构建的单页应用（SPA）。
**当前阶段目标**：建立前端基础架构，实现与后端的联调、健康检查展示，建立稳定、可维护的前端基线。

## 2. 范围界定
### 2.1 包含内容
- **UI 框架**：Vue 3 Composition API、基础路由（Vue Router）、状态管理（Pinia）。
- **样式**：Tailwind CSS 4.0 样式框架。
- **API 集成**：健康检查接口调用、代理配置（Vite Proxy）。
- **工程化**：TypeScript 配置、ESLint + Prettier 代码规范、Vitest 测试框架。

## 3. 关键成功指标
1. **联调成功**：通过代理成功调用后端 `/api/health` 接口并展示数据。

## 4. 技术架构标准
### 4.1 核心技术栈
- **框架**：Vue 3.5.0 + TypeScript 5.9.0
- **构建工具**：Vite 8.0.12
- **状态管理**：Pinia 3.0.0
- **路由**：Vue Router 4.5.0
- **样式**：Tailwind CSS 4.0.0
- **测试**：Vitest 4.0.0 + @vue/test-utils 2.4.0
- **代码规范**：ESLint 9.0.0 + Prettier 3.0.0

### 4.2 交互与通信规范
- **API 前缀**：所有 API 调用通过 `/api` 前缀，由 Vite Proxy 转发至后端 `localhost:8000`。
- **配置管理**：API 基础 URL 通过环境变量 `VITE_API_BASE_URL` 配置，默认 `/api`。

---

**变更说明**：本章程为前端子项目最高指导原则，具体的启动命令、API 字段细节请参考前端根目录下的 `README.md` 。