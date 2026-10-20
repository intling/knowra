# Frontend Redesign Specification

## Purpose

提供围绕“上传资料 → 提问 → 核对来源”的主界面，包含响应式侧边栏、对话管理、附件上传、欢迎引导和可访问的输入交互；使用暖纸、松烟青与朱砂的语义令牌和本地中文字体栈。

## Requirements

### Requirement: 主页面左右分栏布局
系统 SHALL 在 `/` 路由提供左右分栏的主页面布局，左侧为固定宽度侧边栏，右侧为自适应宽度的对话主区域。桌面端侧边栏宽度 SHALL 为 272px 并使用暖纸色（`bg-paper-deep`）底色与 1px `border-line` 右侧描边；移动端侧边栏以抽屉形式覆盖对话区。

#### Scenario: 桌面端默认显示分栏布局
- **WHEN** 用户在桌面端（视口宽度 ≥ 768px）访问 `/`
- **THEN** 左侧侧边栏默认可见（宽度 272px），右侧对话区填充剩余宽度
- **AND** 侧边栏使用 `paper-deep` 底色，右侧有 1px `border-line` 分割线

#### Scenario: 移动端侧边栏默认折叠
- **WHEN** 用户在移动端（视口宽度 < 768px）访问 `/`
- **THEN** 侧边栏抽屉默认隐藏（屏幕外 `-translate-x-full`）
- **AND** 顶栏左侧显示菜单按钮，用于展开抽屉

#### Scenario: 移动端切换侧边栏可见性
- **WHEN** 用户在移动端点击菜单按钮
- **THEN** 侧边栏从左侧滑入覆盖对话区（overlay 模式），并显示遮罩层
- **AND** 点击遮罩层、按 Esc 或点击抽屉内关闭按钮都能关闭抽屉

#### Scenario: 抽屉关闭时内部控件不可聚焦
- **WHEN** 移动端抽屉处于关闭状态
- **THEN** 抽屉元素带有 `inert` 属性与 `aria-hidden="true"`
- **AND** 键盘用户 Tab 时不会聚焦到抽屉内的任何按钮或链接

#### Scenario: 打开抽屉后焦点进入抽屉
- **WHEN** 用户点击菜单按钮打开抽屉
- **THEN** 菜单按钮 `aria-expanded="true"`
- **AND** 焦点移动到抽屉内第一个可聚焦控件（"新建对话"按钮）

#### Scenario: 关闭抽屉后焦点回到菜单按钮
- **WHEN** 用户按 Esc、点击遮罩或点击抽屉内的关闭按钮关闭抽屉
- **THEN** 抽屉恢复 `inert` 与 `aria-hidden="true"`
- **AND** 键盘焦点回到菜单按钮

#### Scenario: 选择或新建对话后自动收起抽屉
- **WHEN** 移动端抽屉打开，用户点击某个历史对话、当前对话或"新建对话"按钮
- **THEN** 抽屉自动关闭（即使活跃对话 ID 未变化）

#### Scenario: 抽屉打开时焦点不逃逸
- **WHEN** 移动端抽屉打开，焦点位于抽屉最后一个可聚焦控件时按 Tab
- **THEN** 焦点回到抽屉第一个可聚焦控件
- **AND** 在第一个控件按 Shift+Tab 时焦点移到最后一个控件

#### Scenario: 只挂载一个侧边栏实例
- **WHEN** 主页面在任一视口加载
- **THEN** 只挂载桌面侧边栏或移动抽屉之一，已解析文档接口只请求一次

#### Scenario: 菜单按钮不遮挡对话标题
- **WHEN** 在 390px 宽的视口中打开主页面
- **THEN** 菜单按钮与顶栏中的对话标题在视觉上互不重叠（菜单按钮位于标题左侧的布局流中）

### Requirement: App.vue 纯路由壳
系统 SHALL 将 `App.vue` 简化为仅包含 `<RouterView>` 的纯路由壳，移除全局 header 和导航栏。

#### Scenario: 路由壳渲染
- **WHEN** 应用初始化完成
- **THEN** `App.vue` 仅渲染 `<RouterView>` 组件，不包含全局 header 或导航菜单

### Requirement: 路由精简为两条
系统 SHALL 将前端路由精简为 `/`（主页 ChatLayout）和 `/verify`（流程验证页），删除 `/home` 和 `/chat` 路由。

#### Scenario: 访问 `/` 渲染主页面
- **WHEN** 用户导航至 `/`
- **THEN** 系统渲染 `ChatLayout` 组件

#### Scenario: 访问 `/verify` 渲染流程验证页
- **WHEN** 用户导航至 `/verify`
- **THEN** 系统渲染 `VerificationView` 组件

#### Scenario: 旧路由重定向
- **WHEN** 用户访问 `/home` 或 `/chat`
- **THEN** 系统自动重定向至 `/`

### Requirement: 侧边栏头部
系统 SHALL 在侧边栏顶部显示中文衬线字标"知寻"、拉丁字标"knowra"和全宽"新对话"按钮。"新对话"按钮 SHALL 使用品牌强调色（`bg-brand-700`）并在悬停时加深为 `bg-brand-800`。

#### Scenario: 侧边栏头部渲染
- **WHEN** 主页面加载
- **THEN** 侧边栏顶部显示"知寻"与"knowra"字标
- **AND** 显示全宽"新对话"按钮，样式为 `bg-brand-700`

#### Scenario: 新建对话按钮点击
- **WHEN** 用户点击"新对话"按钮
- **THEN** 系统创建一个新对话，设置为当前活跃对话
- **AND** 对话区切换为空状态（WelcomeView）
- **AND** 新对话出现在历史对话列表顶部

### Requirement: 知识库信息展示
系统 SHALL 在侧边栏"资料库"分区中展示知识库概要信息，数据只读来源于 `GET /api/parsed-documents`，并至少展示已解析资料数量（解析完成不代表已完成向量化，UI 不得宣称“可检索”）。分区 SHALL 覆盖加载、有资料、空和错误四种状态，并提供进入 `/verify` 流程验证页的入口。

#### Scenario: 资料库有资料时显示数量
- **WHEN** 已解析文档接口返回 3 条记录
- **THEN** 侧边栏"资料库"分区显示"3 份已解析资料"
- **AND** 同时显示"流程验证"入口

#### Scenario: 资料库加载中
- **WHEN** 已解析文档请求尚未返回
- **THEN** 分区显示加载骨架，且不显示错误文案

#### Scenario: 资料库为空
- **WHEN** 已解析文档接口返回空数组
- **THEN** 分区显示"还没有已解析的资料"以及上传引导文案

#### Scenario: 资料库加载失败可重试
- **WHEN** 已解析文档接口返回错误
- **THEN** 分区显示"资料库状态获取失败"和"重试"按钮
- **AND** 点击"重试"后再次调用已解析文档接口
- **AND** 通过前端日志系统记录失败（module_name="components:KnowledgeInfo"）

### Requirement: 对话历史列表
系统 SHALL 在侧边栏"最近对话"分区中以列表形式展示所有历史对话，支持切换、重命名和删除操作。分区标题 SHALL 渲染在列表与空状态之前。对话条目主体 SHALL 为可聚焦的原生按钮，当前对话使用 `aria-current="page"` 标记。

#### Scenario: 分区标题位于列表之前
- **WHEN** 侧边栏渲染且存在历史对话
- **THEN** "最近对话"标题出现在所有对话条目的上方

#### Scenario: 分区标题位于空状态之前
- **WHEN** 侧边栏渲染且没有任何对话
- **THEN** "最近对话"标题出现在"暂无对话"空状态的上方

#### Scenario: 对话列表渲染
- **WHEN** 主页面加载且存在历史对话
- **THEN** 侧边栏按时间倒序显示对话列表，每项显示对话标题

#### Scenario: 切换对话
- **WHEN** 用户点击某个历史对话的条目主体
- **THEN** 该对话设为当前活跃对话，对话区加载对应消息历史
- **AND** 该对话条目高亮显示，并带有 `aria-current="page"`

#### Scenario: 重命名对话
- **WHEN** 用户对某个对话触发重命名操作
- **THEN** 对话标题变为可编辑状态，输入框自动获得焦点
- **AND** 用户确认后标题更新并持久化到 localStorage

#### Scenario: 删除对话需要二次确认
- **WHEN** 用户对某个对话触发删除操作
- **THEN** 系统弹出模态确认框（`role="dialog"`、`aria-modal="true"`），初始焦点落在"取消"按钮
- **AND** 用户点击"删除"后该对话从列表和 localStorage 中移除
- **AND** 如果删除的是当前活跃对话，对话区切换到空状态

#### Scenario: 确认框焦点循环与归还
- **WHEN** 删除确认框打开
- **THEN** Tab / Shift+Tab 在确认框内的按钮之间循环
- **AND** 确认框关闭后焦点回到触发它的删除按钮

#### Scenario: 抽屉内的确认框只关闭最上层
- **WHEN** 移动端抽屉打开，用户在抽屉中删除对话并弹出确认框后按 Esc
- **THEN** 只关闭确认框，抽屉保持打开，焦点回到删除按钮
- **AND** 确认框打开期间 Tab / Shift+Tab 不会把焦点交给抽屉的焦点循环
- **AND** 再按一次 Esc 才关闭抽屉

#### Scenario: 取消删除不产生副作用
- **WHEN** 删除确认框打开后，用户点击"取消"或按 Esc
- **THEN** 确认框关闭，对话仍然保留，`deleteConversation` 未被调用

#### Scenario: 对话操作按钮键盘可达
- **WHEN** 用户用键盘将焦点移入某个对话条目
- **THEN** 该条目的重命名与删除按钮可见且可聚焦
- **AND** 每个按钮带有明确的中文 `aria-label`

#### Scenario: 无对话时的空状态
- **WHEN** 用户没有任何历史对话
- **THEN** "最近对话"分区显示"暂无对话"空状态提示

### Requirement: 对话数据持久化
系统 SHALL 将对话列表和消息内容持久化到浏览器 localStorage，确保页面刷新后对话历史不丢失。

#### Scenario: 页面刷新后对话保留
- **WHEN** 用户创建对话并发送消息后刷新页面
- **THEN** 侧边栏仍显示之前的对话列表
- **AND** 上次活跃对话的消息历史仍然可用

#### Scenario: localStorage 数据异常处理
- **WHEN** localStorage 中对话数据格式异常或损坏
- **THEN** 系统初始化空对话列表，不崩溃
- **AND** 通过日志记录数据异常，module_name="chat-store"

### Requirement: 空状态欢迎页
系统 SHALL 在无活跃对话或当前对话尚无消息时显示欢迎页，说明"上传资料 → 提问 → 核对来源"的起手路径，并提供可操作的上传入口与推荐问题。推荐问题 SHALL 只把文本填入输入框并聚焦，不直接发送请求。

#### Scenario: 欢迎页展示起手路径
- **WHEN** 用户创建新对话或删除当前活跃对话后对话为空
- **THEN** 对话区显示欢迎标题与副标题
- **AND** 显示三个步骤：上传资料、提问、核对来源
- **AND** 第一个步骤内含"上传资料"按钮

#### Scenario: 点击上传按钮触发文件选择
- **WHEN** 用户点击欢迎页的"上传资料"按钮
- **THEN** 触发与输入框附件按钮相同的文件选择流程（同一隐藏 file input）
- **AND** 不发送任何检索请求

#### Scenario: 推荐问题填入输入框而非直接发送
- **WHEN** 用户点击任一推荐问题
- **THEN** 该问题的文本被写入输入框
- **AND** 输入框获得焦点
- **AND** 不发送检索请求，推荐问题文本保留给用户继续编辑

#### Scenario: 推荐问题不少于三条
- **WHEN** 欢迎页渲染
- **THEN** 至少渲染 3 个推荐问题按钮
- **AND** 文案不包含具体文档名或伪造的知识库内容

#### Scenario: 空输入仍然无法发送
- **WHEN** 用户未在输入框输入任何文本且未选择附件
- **THEN** 发送按钮保持禁用

#### Scenario: 发送后新一轮问答进入视野
- **WHEN** 对话已有多轮内容，用户发送新问题
- **THEN** 消息区滚动使新问题与其等待/回答占位进入可视区域
- **AND** 异步回答返回时不强制滚动，已向上翻阅的用户不会被拉回底部

#### Scenario: 发送消息后欢迎页消失
- **WHEN** 用户在欢迎页状态下发送第一条消息
- **THEN** 欢迎页替换为对话消息流视图

### Requirement: 用户消息气泡
系统 SHALL 以气泡样式展示用户发送的消息，与 AI 回答形成视觉区分，并保留消息中的换行与长单词折行。

#### Scenario: 用户消息渲染
- **WHEN** 用户发送一条消息
- **THEN** 消息以右对齐气泡展示，引用品牌强调色令牌（`bg-brand-700`）与白色文字
- **AND** 外层容器使用 `justify-end`

#### Scenario: 多行消息保留换行
- **WHEN** 用户消息文本包含换行符
- **THEN** 气泡以 `whitespace-pre-wrap` 呈现，换行在渲染结果中被保留

#### Scenario: 超长无空格文本不撑破布局
- **WHEN** 用户消息包含连续的长串无空格字符
- **THEN** 气泡使用 `overflow-wrap: anywhere`（或等效类）自动折行

### Requirement: AI 回答加载骨架屏
系统 SHALL 在等待 AI 回答时，在回答位置显示占位骨架与阶段文案，并通过 `aria-live="polite"` 播报当前阶段。发送按钮 SHALL 同时处于禁用状态。

#### Scenario: 检索阶段占位
- **WHEN** 用户发送问题后检索尚未完成
- **THEN** 回答位置显示骨架与"正在检索资料…"
- **AND** 发送按钮处于禁用状态

#### Scenario: 生成阶段占位
- **WHEN** 检索完成但 AI 回答尚未返回（气泡阶段为 `generating`）
- **THEN** 回答位置文案变更为"正在生成回答…"

#### Scenario: 阶段变化被读屏播报
- **WHEN** 加载阶段从检索切换为生成
- **THEN** 承载阶段文案的元素带有 `aria-live="polite"` 与 `role="status"`

#### Scenario: 加载完成骨架屏消失
- **WHEN** AI 回答返回
- **THEN** 骨架屏替换为 AnswerPanel、SourceList 与检索详情入口

### Requirement: 内嵌多文件附件上传
系统 SHALL 在对话输入框中提供内嵌附件上传功能，支持选择多个文件、预览文件 chips 和独立删除。仅附件发送 SHALL 以至少一个文件已上传成功为前提，选择文件本身不代表上传成功。

#### Scenario: 选择文件后显示 chips
- **WHEN** 用户点击输入框附件按钮并选择一个或多个文件
- **THEN** 输入框上方或内部显示文件 chips，每个 chip 包含文件名、文件大小和删除按钮

#### Scenario: 单文件独立删除
- **WHEN** 用户点击某个文件 chip 上的删除按钮
- **THEN** 该文件从待上传列表中移除，不影响其他已选文件

#### Scenario: 文件上传中状态
- **WHEN** 文件正在上传中
- **THEN** 对应的文件 chip 显示上传进度指示
- **AND** 相同的文件不可重复提交

#### Scenario: 文件上传成功后状态
- **WHEN** 文件上传成功
- **THEN** 文件 chip 变更为已上传状态（如显示 ✓ 标记）
- **AND** 用户可发送附带已上传文件引用的消息

#### Scenario: 文件上传失败后处理
- **WHEN** 文件上传失败
- **THEN** 对应的文件 chip 显示错误状态和错误提示
- **AND** 用户可移除该 chip 或重新尝试上传

#### Scenario: 附件按钮与文本发送互不干扰
- **WHEN** 用户未输入文本，且至少一个附件已上传成功、当前没有上传任务
- **THEN** 发送按钮可用
- **AND** 系统发送时仅携带已上传成功的文件信息

#### Scenario: 未上传成功的附件不启用发送
- **WHEN** 用户未输入文本，附件均在上传中或均上传失败
- **THEN** 发送按钮保持禁用，不发送搜索请求

### Requirement: 对话输入增强
系统 SHALL 保留文本输入、附件上传与发送功能，并把 Top-K 与"替换同名文件"设置收纳进默认关闭的设置弹层。输入区 SHALL 为文本框独占整行、工具栏位于下方的结构，文本区在 390px 视口下宽度不小于 300px。

#### Scenario: 文本框独占整行
- **WHEN** 对话输入区渲染
- **THEN** 文本框与工具栏为上下两行结构，文本框宽度随容器铺满

#### Scenario: Enter 发送文本
- **WHEN** 用户在输入框中按下 Enter（未按 Shift、Ctrl 或 Cmd，且未处于输入法组字状态）
- **THEN** 系统发送当前输入内容

#### Scenario: Shift+Enter 换行
- **WHEN** 用户在输入框中按下 Shift+Enter
- **THEN** 输入框内插入换行符，不发送

#### Scenario: 输入法组字时 Enter 不发送
- **WHEN** 用户使用中文输入法组字，按 Enter 确认候选词（keydown 事件 `isComposing=true` 或 keyCode 229）
- **THEN** 不发送请求，输入框草稿保留
- **AND** 组字结束后再按 Enter 正常发送

#### Scenario: Ctrl/Cmd+Enter 换行
- **WHEN** 用户在输入框中按下 Ctrl+Enter 或 Cmd+Enter
- **THEN** 输入框内插入换行符，不发送

#### Scenario: Top-K 调节保留
- **WHEN** 用户打开设置弹层并调整 Top-K 滑块
- **THEN** 下一条搜索请求使用调整后的 top_k 值

#### Scenario: 设置按钮用直白文案显示检索片段数
- **WHEN** 设置弹层未打开且 Top-K 为 5
- **THEN** 设置按钮可见文案为"检索 5 段"，不在主工具栏出现 "Top-K" 技术术语
- **AND** 弹层内的高级设置标签仍注明 Top-K，请求参数仍为 top_k

#### Scenario: Esc 关闭设置弹层并归还焦点
- **WHEN** 设置弹层打开时用户按 Esc
- **THEN** 弹层关闭
- **AND** 焦点回到设置按钮

#### Scenario: 空文本且无附件时发送按钮禁用
- **WHEN** 输入框为空（或仅含空白）且无已上传附件
- **THEN** 发送按钮处于禁用状态

### Requirement: 全局视觉令牌与排版基础
系统 SHALL 使用语义化设计令牌（`paper` / `paper-deep` / `surface` / `ink` / `ink-muted` / `ink-faint` / `line` / `brand` / `cite`）定义颜色，并使用 Tailwind v4 字体命名空间令牌（`--font-display` / `--font-sans` / `--font-mono`）定义字体。页面加载 SHALL NOT 依赖外部字体服务。

#### Scenario: 字体令牌生效
- **WHEN** 使用 `font-display`、`font-sans`、`font-mono` 工具类
- **THEN** 编译后的 CSS 分别输出对应的 `font-family` 声明（引用 `var(--font-display)` 等）
- **AND** 字体栈包含中文字体与 `serif` / `sans-serif` 回退
- **AND** 字体栈不包含 Inter、Roboto 或 Arial

#### Scenario: 不依赖外网字体
- **WHEN** 应用入口 HTML 渲染
- **THEN** 不包含指向外部字体服务（如 `fonts.googleapis.com`、`fonts.gstatic.com`）的链接
- **AND** 离线环境下页面仍按回退字体栈正常阅读

#### Scenario: 减少动画偏好
- **WHEN** 用户系统启用 `prefers-reduced-motion: reduce`
- **THEN** 全局样式把动画与过渡时长压缩到近乎为零
- **AND** 不依赖动画传达状态（加载与错误状态均有静态文案）

#### Scenario: 纸面氛围
- **WHEN** 主对话区渲染
- **THEN** 背景在纸色基础上叠加极低对比度的径向渐变（同一色板），不使用图片或纹理，不影响正文对比度

#### Scenario: 焦点可见
- **WHEN** 用户使用键盘 Tab 浏览
- **THEN** 每个可聚焦控件显示 2px 品牌色焦点环，且不被容器裁切
