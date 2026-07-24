# A+B 实施计划：产品化收口 + 创作助手聊天

> 日期：2026-07-24  
> 范围：先收口当前工作区（A），再实现「创作助手」聊天 MVP（B）  
> 原则：最小可验证闭环；不混入无关重构；按钮工作流与聊天入口并行共存

---

## 总目标

1. **A — 产品化收口**：把当前未提交改动按主题拆清、补齐边界、跑通测试，形成可独立验收的交付块（不必一次全部 commit，但计划按可 commit 边界划分）。
2. **B — 创作助手**：在已有 `AgentConversation` / `AgentMessage` 上补齐 API + 项目页侧栏 UI，形成「多轮对话 + 项目上下文 + 流式回复」的工作台聊天；第二阶段才接 intent → 派发已有 Task。

### 成功标准（可验证）

| 块 | 成功标准 |
|---|---|
| A1 归档 | `pytest backend/tests/test_project_archive.py` 全绿；首页可导入/导出 ZIP；批量删除可用 |
| A2 桌面鉴权 | 打包路径下无 token 请求 401；健康检查带 token 且校验 `app` 名；开发模式无 token 仍可访问 |
| A3 首页/壳 | 搜索排序分页封面卡片；无边框窗口控件；服务状态点 |
| A4 Agent 抽离 | 一句话初始化走 `ProjectInitializationAgent`；原 API 行为不变 |
| B1 API | 获取/创建默认会话、列消息、发消息（同步完整回复 + 任务流式预览） |
| B2 UI | 项目页可开侧栏聊天，历史可回放，发送后能看到回复 |
| B3 测试 | 新增 `test_assistant_chat.py`（或等价）覆盖会话与发消息主路径 |

### 非目标（本轮不做）

- 多会话管理 UI、重命名/归档会话
- 复杂 tool-calling / 多 Agent 编排
- 向量检索记忆
- 改掉现有按钮入口（一句话初始化等仍走原 generate API）
- 强制用户现在就 git commit（计划给出拆分建议，commit 需用户明确指示）

---

## 现状盘点

### 已有地基

- 模型：`AgentConversation`（默认 title「创作助手」）、`AgentMessage`（role/content/intent/task_id/payload）
- 迁移：`0002_agent_conversation.py`
- Agent 运行时：`BaseAgent` + `AgentRuntime` + `AgentRun`（面向后台 Task）
- 流式文本：`AIService.generate_text_stream(system, user, on_delta)`
- 上下文：`ContextAssemblyService`（章节级完善；项目级需轻量摘要）
- 任务轮询：`ProjectView` 已有 `pollActiveTasks` + `TerminalDialog`

### 工作区未提交主线（A）

| 主题 | 关键文件 |
|---|---|
| 项目 ZIP 归档 | `project_archive_service.py`, `projects.py`, `export.py`, `test_project_archive.py` |
| 首页/壳 UI | `HomeView.vue`, `App.vue`, `style.css`, `ProjectHeader.vue` 等 |
| 桌面鉴权/无边框 | `desktop/main.cjs`, `preload.cjs`, `backend/app/main.py` |
| 一句话初始化 Agent 化 | `project_initialization_agent.py`, `generation.py` |
| 对话表占位 | `models.py`, `0002_agent_conversation.py` |

### B 缺口

- 无 conversation/message 路由与 schema
- 无聊天 service / 项目摘要上下文
- 前端无 Assistant 面板
- 归档服务 `PROJECT_TABLES` 尚未包含对话表（导入导出需决定是否纳入）

---

## A — 产品化收口（实现细节）

### A0. 验收与修补顺序

```
1. 跑归档测试 → 修红
2. 跑 management / ai_service 相关测试 → 修红
3. 手工核对 API 边界（import/archive/batch-delete）
4. 确认 archive 是否应序列化对话表（建议：MVP 纳入，避免导入丢聊天）
5. 不主动 git commit，除非用户要求
```

### A1. 项目归档（已大体完成，计划内核对项）

**API**

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/api/v1/projects/` | 列表 + `cover_image` + `chapter_count` |
| POST | `/api/v1/projects/import` | 流式读 body，上限 1GB，落临时 zip 再 import |
| GET | `/api/v1/projects/{id}/archive` | 导出 zip，`FileResponse` + 后台删临时文件 |
| POST | `/api/v1/projects/batch-delete` | body: `{ project_ids: string[] }` |

**服务约束（保持）**

- `MAX_ARCHIVE_BYTES = 1GB`，未压缩上限 2GB，压缩比限制，成员数限制
- 媒体仅允许 `characters/`、`panels/`，防 path traversal 与 Windows 保留名

**B 联动修补**

- `PROJECT_TABLES` 增加：
  - `agent_conversations` → `AgentConversation`
  - `agent_messages` → `AgentMessage`
- 导入时按 FK 顺序：conversation → message；导出时带上
- 测试：有消息的项目 zip 往返后消息条数一致

### A2. 桌面本地鉴权

**后端 `main.py`**

- `TrustedHostMiddleware`: `127.0.0.1`, `localhost`, `testserver`
- 中间件：若设置 `COMIC_APP_AUTH_TOKEN`（或 `COMIC_APP_AUTH_REQUIRED`），则 `/api/v1/*` 与 `/static/*` 校验 `X-Comic-App-Token`（`hmac.compare_digest`）
- 开发：不设 token → 开放；pytest 用 `testserver` host

**Electron**

- 启动时 `crypto.randomBytes(32)` → 注入子进程 env
- `webRequest.onBeforeSendHeaders` 给 `127.0.0.1:port` 加 token
- 健康检查校验 `status===ok && app===EXPECTED_BACKEND_APP`
- 端口优先 `48730+`

### A3. 首页与壳

- 搜索/排序/分页/封面/导入导出/批量管理：`HomeView.vue`
- 顶栏、健康点、窗口控件：`App.vue` + `preload` 暴露的 `windowControls`
- 默认封面：`frontend/public/default-project-cover.png`

### A4. 一句话初始化 Agent 化

- `generate_project_initialization_task` 仅调度 `ProjectInitializationAgent` + `AgentRuntime`
- 保留 `build_project_initialization_prompt` / `persist_project_initialization_payload` / `has_initialized_content` 供 Agent 与 API 共用
- 流式预览仍写入 `task.result.stream_preview`，前端 `TerminalDialog` 已兼容

### A 建议 commit 拆分（用户授权后再执行）

1. `feat: project zip import/export and batch delete`
2. `feat: home project grid with search sort import export`
3. `feat: desktop local auth token and frameless window chrome`
4. `refactor: project initialization via ProjectInitializationAgent`
5. `feat: agent conversation models and migration`（可与 B 合并）

---

## B — 创作助手聊天 MVP（完整实现细节）

### B0. 产品决策（本轮冻结）

| 决策 | 选择 | 理由 |
|---|---|---|
| MVP 能力 | **只聊天 + 项目上下文**；intent→Task 为 Phase 2 | 最快闭环，复用现有按钮工作流 |
| UI 位置 | **项目页右侧抽屉**，Header 按钮打开 | 不抢 Tab 工作流，随时可开 |
| 会话模型 | 每项目 **一个默认 active 会话**（get-or-create） | 表已支持多会话，UI 暂不暴露 |
| 回复方式 | 创建 `Task(type=assistant_chat)` 后台生成 + 前端轮询消息/任务 | 与现有任务体系一致，可取消/重试扩展 |
| 流式 | 写入 `task.result.stream_preview`；同时可轮询最后一条 assistant 草稿或完成后落库 | 对齐章节流式体验 |
| 历史窗口 |  assembles 最近 N 条消息（默认 20）+ 项目摘要 | 控制 token |
| 归档 | 对话表纳入 zip | 迁移项目不丢助手历史 |

### B1. 数据与 Schema

模型已存在，**一般不再改表结构**。补充 Pydantic：

文件：`backend/app/schemas/schemas.py`

```python
class AgentMessageCreate(BaseModel):
    content: str  # 用户输入，strip 后非空，max 8000 字符

class AgentMessageRead(BaseModel):
    id: int
    conversation_id: int
    project_id: str
    role: str
    content: str
    intent: Optional[str] = None
    task_id: Optional[str] = None
    payload: Dict[str, Any] = {}
    created_at: datetime

class AgentConversationRead(BaseModel):
    id: int
    project_id: str
    title: str
    status: str
    created_at: datetime
    updated_at: datetime
    messages: List[AgentMessageRead] = []  # list 接口可不带；get 可带最近消息

class AssistantChatResponse(BaseModel):
    conversation_id: int
    user_message: AgentMessageRead
    task_id: str  # 后台生成任务
```

### B2. 服务层

#### 2.1 `backend/app/services/assistant_service.py`（新建）

职责：

1. `get_or_create_default_conversation(session, project_id) -> AgentConversation`  
   - 查 `status=="active"` 按 `updated_at` 最新；无则创建 title=`创作助手`
2. `list_messages(session, conversation_id, limit=100, before_id=None) -> list[AgentMessage]`  
   - 按 `id` 升序返回（若 before 分页则取更早再反转）
3. `build_project_brief(session, project_id) -> str`  
   - 轻量摘要，避免整库塞 prompt：
     - 标题、描述、theme、workflow_mode、language
     - 章节数 + 前 8 章标题/摘要（截断）
     - 角色名列表（最多 20）
     - 设定条目标题（最多 15）
     - 大纲条目标题（最多 10）
     - 当前进度一行（若有）
4. `build_chat_system_prompt(brief: str) -> str`  
   - 角色：漫画/小说改编创作助手  
   - 约束：基于项目事实；不知则说明；不捏造已生成图片 URL；可建议用户去对应 Tab 点按钮执行重任务  
   - 附上 `brief`
5. `build_chat_user_payload(history: list[AgentMessage], latest: str) -> str`  
   - 将历史格式化为：
     ```
     ### 对话历史
     [user]: ...
     [assistant]: ...
     ### 当前用户
     ...
     ```
   - 或若后续 AIService 支持 messages 数组再升级；MVP 用单 user 字符串拼历史即可（与现有 `generate_text_stream` 签名对齐）
6. `create_user_message_and_task(...)`  
   - 校验项目存在  
   - get_or_create conversation  
   - 写入 user `AgentMessage`  
   - 创建 `Task(type="assistant_chat", ...)`  
   - user message 的 `task_id` 可先空；assistant 消息在 runner 里创建并挂 task_id  
   - **策略（选定）**：  
     - 发消息时只落 user message  
     - runner 开始时插入 role=assistant content="" 或「生成中…」placeholder，payload=`{streaming:true}`，task_id=task.id  
     - 流式更新 **仅** `task.result.stream_preview`（避免高频写 message 表）  
     - 完成后把完整文本写入 assistant message，payload=`{streaming:false}`，conversation.updated_at 刷新

#### 2.2 Runner：`generate_assistant_chat_task(task_id: str)`

位置：优先 `backend/app/routers/generation.py` 内薄封装，或 `assistant_service` 内函数 + dispatch 引用（与现有 generation runners 一致，**放 generation.py 底部或独立 `assistant_chat` 模块由 dispatch 调用**）。

推荐文件：`backend/app/services/assistant_chat_runner.py` 避免 generation.py 继续膨胀。

流程：

```
load task → status processing
load conversation_id, project_id, user_message_id from input_payload
create assistant placeholder message
build brief + history (最近 20 条，不含空 placeholder 或含并忽略空 content)
AIService.generate_text_stream(system, user_payload, on_delta)
  on_delta: 节流 1s 写 task.result.stream_preview / stream_chars；raise_if_cancelled
写满 assistant.content；task completed；result 含 message_id
失败：assistant.content 写错误摘要或删 placeholder 并 task failed
```

`input_payload`：

```json
{
  "project_id": "...",
  "conversation_id": 1,
  "user_message_id": 12
}
```

#### 2.3 `task_dispatch.py`

```python
RECOVERABLE_TASK_TYPES.add("assistant_chat")  # input_payload 完整则可恢复

# run_task:
elif task_type == "assistant_chat":
    from app.services.assistant_chat_runner import run_assistant_chat_task
    run_assistant_chat_task(task_id)
```

### B3. API 路由

新建：`backend/app/routers/assistant.py`  
挂载：`app.include_router(..., prefix=f"{settings.API_V1_STR}/projects", tags=["assistant"])`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/{project_id}/assistant/conversation` | get-or-create 默认会话（不含全量消息或只带 last 50） |
| GET | `/{project_id}/assistant/messages?limit=100&before_id=` | 消息列表 |
| POST | `/{project_id}/assistant/messages` | body: `AgentMessageCreate` → 创建 user + task，返回 `AssistantChatResponse` |
| POST | `/{project_id}/assistant/conversation/clear` | 可选 MVP+：软清或新建会话；**本轮可做简单版：status=archived 旧会话并新建** |

错误：

- 404 project
- 400 空 content / 超长
- 409 可选：同一 conversation 已有 running `assistant_chat` 时拒绝或排队（**选定：允许并行**，但 UI 发送中 disable 输入，降低并发）

### B4. 前端

#### 4.1 `AssistantPanel.vue`（新建）

路径：`frontend/src/views/project/AssistantPanel.vue`

UI：

- `el-drawer` size 400px，title「创作助手」
- 消息列表：user 右对齐气泡，assistant 左对齐；`pre-wrap`；时间小字
- 若最后一条 assistant 关联 task 且 task 仍 running：显示 `stream_preview`（轮询 task 或父组件传入）
- 底部 textarea + 发送；Enter 发送，Shift+Enter 换行
- 空状态文案：可问设定、剧情、角色一致性、分镜建议等
- 可选：消息上若有 task_id 且已完成，显示「查看任务」链到 `open-terminal`

数据流：

```
open drawer → GET conversation + GET messages
send → POST messages → 得到 task_id
poll: 每 1s GET messages 或 GET /tasks/{id}
  - stream: 用 task.result.stream_preview 渲染临时气泡
  - completed: 刷新 messages，清临时预览
```

#### 4.2 接入 `ProjectView.vue` / `ProjectHeader.vue`

- Header 增加按钮「创作助手」→ `emit('open-assistant')`
- ProjectView：`showAssistant` ref + `AssistantPanel`
- 发送成功后 `pollActiveTasks()`，使 TaskManager 也能看到 `assistant_chat`

#### 4.3 任务展示文案

`TaskManager.vue` / `TerminalDialog.vue` 增加：

```js
assistant_chat: '创作助手回复'
```

摘要：显示已生成字数 / 完成提示。

### B5. 系统 Prompt 草案

```
你是「AI 漫画生成器」内的创作助手，帮助用户推进当前项目的故事、设定、角色与分镜规划。

规则：
1. 优先依据下方【项目摘要】中的事实回答；摘要没有的信息请明确说不确定，并建议用户在对应页签补充。
2. 回答简洁、可执行；需要长文时用小标题与条目。
3. 不要编造已生成的图片路径或任务 ID。
4. 涉及耗时生成（批量出图、一句话初始化、原文分析等）时，指导用户使用界面已有按钮，而不是假装已经执行。
5. 默认使用与项目 language 一致的语言（通常是中文）。

【项目摘要】
{brief}
```

### B6. 测试

文件：`backend/tests/test_assistant_chat.py`

用例：

1. get conversation 两次返回同一 id  
2. post message 创建 user message + pending/processing task  
3. mock `AIService.generate_text_stream` 返回固定字符串 → runner 后 assistant message content 匹配  
4. 空 content → 400  
5. 不存在 project → 404  
6. （可选）clear conversation 后新 id，旧消息不可见  

归档测试增量：

7. 含对话的项目 export/import 后 message 内容保留（若 A1 纳入对话表）

### B7. 实现顺序（任务模式）

```
Wave 1（可并行思想，实际串行更稳）：
  T1  schemas + assistant_service + runner + dispatch + router + main 挂载
  T2  pytest test_assistant_chat
  T3  归档表纳入对话 + 测试修补

Wave 2：
  T4  AssistantPanel.vue + Header/ProjectView 接入
  T5  TaskManager/TerminalDialog 文案
  T6  手动/测试回归：发消息 → 流式/完成 → 历史回放

Wave 0 穿插：
  T0  A 区测试跑绿（archive / management / 相关）
```

---

## Phase 2（本轮文档记录，不实现）

- intent 分类（规则或小模型）：`init` / `chapter_write` / `draw_character` / …
- 匹配到 intent 时创建对应已有 Task，assistant 回复带操作卡片
- `AgentMessage.intent` 写入；UI 展示「已启动任务 xxx」
- 多会话列表
- SSE 直推消息（替代轮询）

---

## 风险与对策

| 风险 | 对策 |
|---|---|
| generate_text_stream 只支持 system+user 单轮 | 历史拼进 user 文本 |
| 高频写库 | 流式只写 task.result，完成再写 message |
| 对话撑爆上下文 | brief 截断 + 历史 20 条 + 单条 content 上限 |
| 与桌面 token 中间件冲突 | 测试 client 默认无 token；路由挂在 API_V1 下自动受保护 |
| generation.py 过大 | runner 独立文件 |
| 归档 ID 重映射 | 与现有 archive 对 FK 表同一套 remap 逻辑；实现时对照 `import_project_archive` |

---

## 文件清单（B 预计触碰）

**新建**

- `backend/app/services/assistant_service.py`
- `backend/app/services/assistant_chat_runner.py`
- `backend/app/routers/assistant.py`
- `backend/tests/test_assistant_chat.py`
- `frontend/src/views/project/AssistantPanel.vue`

**修改**

- `backend/app/main.py` — include_router
- `backend/app/schemas/schemas.py` — 读写模型
- `backend/app/services/task_dispatch.py` — assistant_chat
- `backend/app/services/project_archive_service.py` — 对话表
- `backend/tests/test_project_archive.py` — 往返含消息
- `frontend/src/views/project/ProjectHeader.vue`
- `frontend/src/views/ProjectView.vue`
- `frontend/src/views/project/TaskManager.vue`
- `frontend/src/views/project/TerminalDialog.vue`

**A 已改文件**：维持现状，仅修测试失败与归档对话表缺口。

---

## 停止条件

- B1–B3 成功标准满足  
- A 相关 pytest 不因 B 变红  
- 不扩展 Phase 2 intent 派发  

---

## 执行备注

- 语言：用户沟通中文；代码标识符英文  
- 不主动 commit / push  
- 遵循 Karpathy：只做清单内改动，完成后不做无关清理  
