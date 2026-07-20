# 小说级漫画管理系统一步到位实施计划

## 目标

把当前系统从“漫画生成器 + 基础管理底座”升级为“小说/长篇漫画项目管理系统”。

最终能力：

1. 章节内容可生成、保存、编辑、预览。
2. 章节可绑定大纲、小纲、分镜、任务、人物状态、设定、记忆。
3. 支持人物关系系统。
4. 支持当前进度/当前状态系统。
5. 支持记忆系统前端管理和 AI 上下文接入。
6. 支持服饰、人物关系、当前状态、设定、记忆共同影响分镜和图片 prompt。
7. 支持章节级创作工作流：大纲 → 正文 → 分镜 → 图片 → 审核。

---

## 非目标

本阶段暂不做：

1. 多用户登录。
2. 云端同步。
3. 向量数据库。
4. 复杂多 Agent 编排。
5. Figma/专业排版导出。
6. 完整小说写作 IDE。

但数据结构会预留后续扩展空间。

---

## 一、后端数据模型设计

文件：`backend/app/models/models.py`

### 1. 扩展 Chapter

当前已有：

```python
class ChapterBase(SQLModel):
    sequence: int
    title: str
    summary: Optional[str] = None
    content: Optional[str] = None
    goal: Optional[str] = None
    conflict: Optional[str] = None
    status: str = "draft"
```

需要扩展为：

```python
class ChapterBase(SQLModel):
    sequence: int
    title: str
    summary: Optional[str] = None
    content: Optional[str] = None
    preview_text: Optional[str] = None
    goal: Optional[str] = None
    conflict: Optional[str] = None
    status: str = "draft"
    current_location: Optional[str] = None
    current_time: Optional[str] = None
    pov_character: Optional[str] = None
    word_count: int = 0
    metadata: Dict = Field(default={}, sa_column=Column(JSON))
```

用途：

- `content`：章节正文/生成结果。
- `preview_text`：可选的预览摘要或渲染缓存。
- `current_location`：章节当前地点。
- `current_time`：章节当前时间线。
- `pov_character`：视角角色。
- `word_count`：统计。
- `metadata`：后续扩展。

---

### 2. 新增 CharacterRelationship

```python
class CharacterRelationshipBase(SQLModel):
    source_character_id: int = Field(foreign_key="character.id")
    target_character_id: int = Field(foreign_key="character.id")
    relationship_type: str
    description: Optional[str] = None
    status: str = "active"
    intensity: int = 3
    chapter_id: Optional[int] = Field(default=None, foreign_key="chapter.id")
    tags: List[str] = Field(default=[], sa_column=Column(JSON))

class CharacterRelationship(CharacterRelationshipBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

关系类型示例：

```text
师徒
亲人
敌对
同盟
恋人
主仆
竞争
欠债
隐瞒身份
```

用途：

- 展示人物关系网。
- 生成章节时注入人物关系。
- 生成分镜时避免角色关系错乱。

---

### 3. 新增 CharacterState

```python
class CharacterStateBase(SQLModel):
    character_id: int = Field(foreign_key="character.id")
    chapter_id: Optional[int] = Field(default=None, foreign_key="chapter.id")
    physical_state: Optional[str] = None
    emotional_state: Optional[str] = None
    location: Optional[str] = None
    outfit_id: Optional[int] = Field(default=None, foreign_key="characteroutfit.id")
    goal: Optional[str] = None
    secret: Optional[str] = None
    power_level: Optional[str] = None
    inventory: List[str] = Field(default=[], sa_column=Column(JSON))
    notes: Optional[str] = None

class CharacterState(CharacterStateBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

用途：

- 每章记录角色当前状态。
- 可作为下一章上下文。
- 生图时读取当前服饰和身体状态。

---

### 4. 新增 ProjectProgress

```python
class ProjectProgressBase(SQLModel):
    current_chapter_id: Optional[int] = Field(default=None, foreign_key="chapter.id")
    current_arc: Optional[str] = None
    current_location: Optional[str] = None
    current_time: Optional[str] = None
    main_conflict: Optional[str] = None
    active_threads: List[str] = Field(default=[], sa_column=Column(JSON))
    resolved_threads: List[str] = Field(default=[], sa_column=Column(JSON))
    pending_hooks: List[str] = Field(default=[], sa_column=Column(JSON))
    notes: Optional[str] = None

class ProjectProgress(ProjectProgressBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id", unique=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

用途：

- 对标小说系统 Current State。
- 表示当前剧情进行到哪里。
- 作为生成上下文的核心摘要。

---

### 5. 新增 ChapterVersion

```python
class ChapterVersionBase(SQLModel):
    chapter_id: int = Field(foreign_key="chapter.id")
    title: str
    content: str
    change_note: Optional[str] = None
    version_no: int = 1

class ChapterVersion(ChapterVersionBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

用途：

- 每次保存/生成章节正文时可生成版本。
- 支持后续回滚。

---

### 6. 扩展 MemoryEntry

当前已有：

```python
class MemoryEntryBase(SQLModel):
    scope: str = "project"
    content: str
    tags: List[str] = Field(default=[], sa_column=Column(JSON))
    importance: int = 3
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    is_active: bool = True
```

扩展为：

```python
class MemoryEntryBase(SQLModel):
    scope: str = "project"
    content: str
    memory_type: str = "event"
    chapter_id: Optional[int] = Field(default=None, foreign_key="chapter.id")
    character_id: Optional[int] = Field(default=None, foreign_key="character.id")
    tags: List[str] = Field(default=[], sa_column=Column(JSON))
    importance: int = 3
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    is_active: bool = True
```

类型示例：

```text
event
relationship
foreshadowing
world_state
character_state
constraint
```

---

## 二、数据库兼容策略

当前项目没有 Alembic，使用：

```python
SQLModel.metadata.create_all(engine)
```

所以要继续扩展：

文件：`backend/app/core/database.py`

在 `SQLITE_COLUMN_DEFAULTS` 中追加旧表补列：

```python
SQLITE_COLUMN_DEFAULTS = {
    "chapter": {
        "preview_text": "VARCHAR",
        "current_location": "VARCHAR",
        "current_time": "VARCHAR",
        "pov_character": "VARCHAR",
        "word_count": "INTEGER DEFAULT 0",
        "metadata": "JSON DEFAULT '{}'",
    },
    "memoryentry": {
        "memory_type": "VARCHAR DEFAULT 'event'",
        "chapter_id": "INTEGER",
        "character_id": "INTEGER",
    },
}
```

新增表由 `create_all` 自动创建。

---

## 三、后端 Schema 设计

文件：`backend/app/schemas/schemas.py`

新增：

```python
class CharacterRelationshipCreate(CharacterRelationshipBase):
    pass

class CharacterRelationshipUpdate(BaseModel):
    source_character_id: Optional[int] = None
    target_character_id: Optional[int] = None
    relationship_type: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    intensity: Optional[int] = None
    chapter_id: Optional[int] = None
    tags: Optional[List[str]] = None

class CharacterRelationshipRead(CharacterRelationshipBase):
    id: int
    project_id: str
    created_at: datetime
    updated_at: datetime
```

```python
class CharacterStateCreate(CharacterStateBase):
    pass

class CharacterStateUpdate(BaseModel):
    character_id: Optional[int] = None
    chapter_id: Optional[int] = None
    physical_state: Optional[str] = None
    emotional_state: Optional[str] = None
    location: Optional[str] = None
    outfit_id: Optional[int] = None
    goal: Optional[str] = None
    secret: Optional[str] = None
    power_level: Optional[str] = None
    inventory: Optional[List[str]] = None
    notes: Optional[str] = None

class CharacterStateRead(CharacterStateBase):
    id: int
    project_id: str
    created_at: datetime
    updated_at: datetime
```

```python
class ProjectProgressCreate(ProjectProgressBase):
    pass

class ProjectProgressUpdate(BaseModel):
    current_chapter_id: Optional[int] = None
    current_arc: Optional[str] = None
    current_location: Optional[str] = None
    current_time: Optional[str] = None
    main_conflict: Optional[str] = None
    active_threads: Optional[List[str]] = None
    resolved_threads: Optional[List[str]] = None
    pending_hooks: Optional[List[str]] = None
    notes: Optional[str] = None

class ProjectProgressRead(ProjectProgressBase):
    id: int
    project_id: str
    created_at: datetime
    updated_at: datetime
```

```python
class ChapterVersionCreate(ChapterVersionBase):
    pass

class ChapterVersionRead(ChapterVersionBase):
    id: int
    project_id: str
    created_at: datetime
```

扩展 `ChapterUpdate`：

```python
class ChapterUpdate(BaseModel):
    sequence: Optional[int] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    content: Optional[str] = None
    preview_text: Optional[str] = None
    goal: Optional[str] = None
    conflict: Optional[str] = None
    status: Optional[str] = None
    current_location: Optional[str] = None
    current_time: Optional[str] = None
    pov_character: Optional[str] = None
    metadata: Optional[Dict] = None
```

---

## 四、后端 API 设计

继续扩展：`backend/app/routers/management.py`

### 1. 章节正文保存/预览

```text
GET    /api/v1/projects/{project_id}/chapters/{chapter_id}
PUT    /api/v1/projects/{project_id}/chapters/{chapter_id}/content
GET    /api/v1/projects/{project_id}/chapters/{chapter_id}/preview
GET    /api/v1/projects/{project_id}/chapters/{chapter_id}/versions
POST   /api/v1/projects/{project_id}/chapters/{chapter_id}/versions
```

实现示例：

```python
@router.put("/{project_id}/chapters/{chapter_id}/content", response_model=ChapterRead)
def update_chapter_content(project_id: str, chapter_id: int, payload: ChapterContentUpdate, session: Session = Depends(get_session)):
    chapter = get_project_item(session, Chapter, project_id, chapter_id)
    chapter.content = payload.content
    chapter.preview_text = payload.preview_text or payload.content[:500]
    chapter.word_count = len(payload.content)
    chapter.updated_at = datetime.utcnow()
    session.add(chapter)
    session.commit()
    session.refresh(chapter)

    version_no = get_next_chapter_version_no(session, project_id, chapter_id)
    version = ChapterVersion(
        project_id=project_id,
        chapter_id=chapter_id,
        title=chapter.title,
        content=chapter.content,
        change_note=payload.change_note,
        version_no=version_no,
    )
    session.add(version)
    session.commit()
    return chapter
```

---

### 2. 人物关系 CRUD

```text
GET    /api/v1/projects/{project_id}/relationships
POST   /api/v1/projects/{project_id}/relationships
PUT    /api/v1/projects/{project_id}/relationships/{relationship_id}
DELETE /api/v1/projects/{project_id}/relationships/{relationship_id}
```

校验：

- source 和 target 必须属于同一个项目。
- source 和 target 不能相同。
- intensity 取 1-5。

---

### 3. 角色状态 CRUD

```text
GET    /api/v1/projects/{project_id}/character-states
POST   /api/v1/projects/{project_id}/character-states
PUT    /api/v1/projects/{project_id}/character-states/{state_id}
DELETE /api/v1/projects/{project_id}/character-states/{state_id}
```

支持 query：

```text
?chapter_id=1
?character_id=2
```

---

### 4. 当前进度 API

```text
GET /api/v1/projects/{project_id}/progress
PUT /api/v1/projects/{project_id}/progress
```

如果不存在，GET 时自动返回默认空对象或创建。

---

### 5. 章节生成 API

新增：`backend/app/routers/generation.py`

```text
POST /api/v1/generate/chapter-content/{chapter_id}
POST /api/v1/generate/chapter-storyboard/{chapter_id}
```

请求：

```python
class ChapterGenerateRequest(BaseModel):
    user_input: Optional[str] = None
    save_version: bool = True
```

行为：

- 读取章节。
- 调用 `ContextAssemblyService` 组装上下文。
- 让 AI 生成章节正文。
- 保存到 `Chapter.content`。
- 创建 `ChapterVersion`。

---

## 五、ContextAssemblyService 设计

新增文件：`backend/app/services/context_assembly_service.py`

目标：生成前统一组装上下文。

```python
class ContextAssemblyService:
    def __init__(self, session: Session):
        self.session = session

    def build_chapter_context(self, project_id: str, chapter_id: int) -> dict:
        project = self.session.get(Project, project_id)
        chapter = self.session.get(Chapter, chapter_id)
        progress = self.get_progress(project_id)
        outlines = self.get_outlines(project_id, chapter_id)
        settings = self.get_active_settings(project_id)
        characters = self.get_characters(project_id)
        relationships = self.get_relationships(project_id, chapter_id)
        states = self.get_character_states(project_id, chapter_id)
        memories = self.get_relevant_memories(project_id, chapter_id)

        return {
            "project": project,
            "chapter": chapter,
            "progress": progress,
            "outlines": outlines,
            "settings": settings,
            "characters": characters,
            "relationships": relationships,
            "states": states,
            "memories": memories,
        }
```

### Prompt 文本生成

```python
    def render_context_prompt(self, context: dict) -> str:
        return f"""
你是长篇漫画/小说改漫创作助手。必须严格遵守以下项目上下文。

【项目】
标题：{context['project'].title}
主题：{context['project'].theme or '未指定'}
语言：{context['project'].language}

【当前进度】
{self.render_progress(context['progress'])}

【当前章节】
{self.render_chapter(context['chapter'])}

【大纲/小纲】
{self.render_outlines(context['outlines'])}

【世界设定】
{self.render_settings(context['settings'])}

【角色】
{self.render_characters(context['characters'])}

【人物关系】
{self.render_relationships(context['relationships'])}

【角色当前状态】
{self.render_states(context['states'])}

【记忆与连续性约束】
{self.render_memories(context['memories'])}
"""
```

### 记忆筛选规则

暂不引入向量数据库，使用规则筛选：

```python
get_relevant_memories(project_id, chapter_id):
    - is_active = True
    - scope in ['project', 'chapter']
    - chapter_id is null or chapter_id == 当前章节
    - importance >= 3
    - 按 importance desc 排序
    - 最多取 30 条
```

---

## 六、AIService 扩展

文件：`backend/app/services/ai_service.py`

新增：

```python
    def generate_chapter_content(self, context_prompt: str, user_input: str = "") -> str:
        system_prompt = "你是专业长篇小说与漫画脚本创作助手。请生成结构清晰、可用于漫画改编的章节正文。"
        full_input = f"""
{context_prompt}

【用户补充要求】
{user_input or '无'}

请输出当前章节正文，要求：
1. 保持人物关系一致。
2. 保持当前状态一致。
3. 不违反世界设定。
4. 章节结尾留下可继续推进的钩子。
"""
        return self.generate_text(system_prompt, full_input)
```

如果当前 `AIService` 没有统一 `generate_text`，则新增内部 provider 分发：

```python
    def generate_text(self, system_prompt: str, user_input: str) -> str:
        config = self._get_config("text")
        provider = self._provider_name(config)
        if provider == "openai_compatible":
            return self._generate_storyboard_openai_compatible(config, system_prompt, user_input)
        return self._generate_storyboard_google(config, system_prompt, user_input)
```

后续 `generate_storyboard` 也可复用 `generate_text`。

---

## 七、前端页面设计

### 1. ChapterTab 升级

文件：`frontend/src/views/project/ChapterTab.vue`

新增三个区域：

```text
左侧：章节列表
右侧上：章节基础信息 + 当前状态
右侧中：章节正文编辑/预览
右侧下：大纲、小纲、章节任务
```

新增功能：

- 点击章节后显示详情。
- 正文编辑器。
- 预览模式。
- 保存正文。
- 生成章节正文按钮。
- 查看版本历史。
- 当前地点/时间/视角角色。

关键状态：

```js
const selectedChapter = computed(() => chapters.value.find(c => c.id === selectedChapterId.value))
const chapterContent = ref('')
const previewMode = ref('preview')
const versions = ref([])
```

保存正文：

```js
const saveChapterContent = async () => {
  await axios.put(`/api/v1/projects/${props.projectId}/chapters/${selectedChapterId.value}/content`, {
    content: chapterContent.value,
    change_note: '手动保存'
  })
  ElMessage.success('章节正文已保存')
  await loadData()
}
```

生成正文：

```js
const generateChapterContent = async () => {
  await axios.post(`/api/v1/generate/chapter-content/${selectedChapterId.value}`, {
    user_input: chapterGenerateInput.value,
    save_version: true
  })
  ElMessage.success('章节正文生成任务已启动')
}
```

---

### 2. 新增 MemoryPanel.vue

文件：`frontend/src/views/project/MemoryPanel.vue`

功能：

- 记忆列表。
- 按类型筛选。
- 按章节筛选。
- 新增/编辑/删除记忆。
- 启用/停用记忆。

字段：

```js
memoryForm = {
  scope: 'project',
  memory_type: 'event',
  chapter_id: null,
  character_id: null,
  content: '',
  tags: [],
  importance: 3,
  is_active: true
}
```

---

### 3. 新增 RelationshipPanel.vue

文件：`frontend/src/views/project/RelationshipPanel.vue`

功能：

- 人物关系列表。
- 新增人物关系。
- 编辑关系强度、状态、说明。
- 按章节过滤。

MVP 展示为列表，不先做图谱。

后续可升级为关系图。

---

### 4. 新增 ProgressPanel.vue

文件：`frontend/src/views/project/ProgressPanel.vue`

功能：

- 当前章节。
- 当前篇章。
- 当前地点。
- 当前时间。
- 主冲突。
- 活跃伏笔。
- 已解决伏笔。
- 待回收钩子。
- 备注。

保存接口：

```js
await axios.put(`/api/v1/projects/${props.projectId}/progress`, progressForm.value)
```

---

### 5. CharacterTab 升级

文件：`frontend/src/views/project/CharacterTab.vue`

在角色服饰下方新增：

- 当前状态列表。
- 与其他角色关系。

但为了避免单页过长，建议只显示摘要，编辑放到 `RelationshipPanel` 和 `ProgressPanel`。

---

### 6. ProjectView Tab 调整

当前：

```text
1. 故事与配置
2. 设定中心
3. 章节规划
4. 角色工坊
5. 分镜画布
```

升级为：

```text
1. 故事与配置
2. 设定中心
3. 章节创作
4. 人物关系
5. 当前进度
6. 记忆库
7. 角色工坊
8. 分镜画布
```

如果 tab 太多，可合并为：

```text
1. 故事与配置
2. 设定中心
3. 章节创作
4. 关系与状态
5. 记忆库
6. 角色工坊
7. 分镜画布
```

本次建议采用第二种，避免导航过长。

---

## 八、章节内容生成流程

### 流程

```text
用户选择章节
→ 填写章节目标/小纲/补充要求
→ 点击生成章节正文
→ 后端 ContextAssemblyService 组装上下文
→ AIService 调用文本模型
→ 保存 Chapter.content
→ 创建 ChapterVersion
→ 前端刷新正文预览
```

### 验收

1. 点击“生成章节正文”后可以看到正文结果。
2. 正文持久化到数据库。
3. 刷新页面后仍可预览。
4. 版本历史出现一条新记录。
5. 生成内容中包含设定/角色/关系/记忆上下文。

---

## 九、章节分镜生成流程

新增：

```text
POST /api/v1/generate/chapter-storyboard/{chapter_id}
```

行为：

1. 读取章节正文。
2. 读取章节上下文。
3. 生成该章节分镜 JSON。
4. 保存为 `StoryboardItem`，带 `chapter_id`。
5. 分镜画布可按章节筛选。

伪代码：

```python
@router.post("/chapter-storyboard/{chapter_id}")
def generate_chapter_storyboard(chapter_id: int, request: ChapterGenerateRequest, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    chapter = session.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    task = create_task(...)
    background_tasks.add_task(run_chapter_storyboard_task, task.id, chapter.id, request.user_input)
    return task
```

---

## 十、Prompt 注入策略

### 章节正文生成 Prompt

```text
你是长篇小说/漫画脚本创作助手。
请根据项目设定、当前进度、人物关系、角色状态、记忆和章节小纲生成章节正文。

必须遵守：
- 不得改变已定义世界设定。
- 不得让角色知道其不应知道的信息。
- 人物关系必须符合关系库。
- 当前角色状态必须延续。
- 章节结尾需要保留推进钩子。
```

### 章节分镜生成 Prompt

```text
请把当前章节正文改写为漫画分镜 JSON。
每个分镜必须包含：
- scene
- action
- dialogue
- characters
- selected_outfits
- prompt
- negative_prompt

必须遵守角色当前服饰和人物关系。
```

### 图片生成 Prompt

后续扩展 `generate_image` 时注入：

```text
角色当前状态：...
角色服饰：...
人物关系：...
章节地点/时间：...
视觉风格设定：...
```

---

## 十一、测试计划

### 后端测试

新增：`backend/tests/test_novel_system.py`

覆盖：

1. 章节正文保存生成版本。
2. 章节预览读取。
3. 人物关系 CRUD。
4. 角色状态 CRUD。
5. 当前进度 GET/PUT。
6. 记忆按章节/角色保存。
7. ContextAssemblyService 能组装设定、关系、状态、记忆。
8. 非法关系校验：source=target 返回 400。
9. 非法 intensity 返回 400。
10. 非法章节引用返回 404。

### 前端构建

```bash
pnpm --dir frontend build
```

### 后端测试

```bash
python -m unittest discover -s backend/tests -v
```

---

## 十二、MCP 验收计划

使用 Playwright MCP 验收：

1. 打开项目页。
2. 进入章节创作。
3. 新增章节。
4. 填写章节正文。
5. 保存正文。
6. 刷新页面，正文仍存在。
7. 切换预览模式，正文可读。
8. 新增人物关系。
9. 新增角色状态。
10. 新增当前进度。
11. 新增记忆。
12. 生成章节正文接口可触发。
13. 分镜画布按章节筛选正常。
14. 控制台 0 error。
15. 新接口网络请求均为 200。

---

## 十三、AI Bridge 与 MCP HTTP 服务

本项目新增两个独立本地服务，端口避开已有 `48621/48622`：

```text
AI Bridge 服务：127.0.0.1:48721
MCP HTTP 服务：127.0.0.1:48722
```

### AI Bridge

文件：`backend/app/bridge/ai_bridge.py`

启动：

```bash
python -m uvicorn app.bridge.ai_bridge:app --app-dir backend --host 127.0.0.1 --port 48721
```

Windows 快捷启动：

```bash
start_ai_bridge.bat
```

接口：

```text
GET  /health
POST /text/generate
POST /chapter/context
POST /chapter/generate
```

用途：

- 给外部工具提供统一文本生成入口。
- 给外部工具提供章节上下文 prompt。
- 支持直接生成章节正文并保存版本。

### MCP HTTP 服务

文件：`backend/app/bridge/mcp_http_server.py`

启动：

```bash
python -m uvicorn app.bridge.mcp_http_server:app --app-dir backend --host 127.0.0.1 --port 48722
```

Windows 快捷启动：

```bash
start_mcp_http_server.bat
```

接口：

```text
GET  /health
GET  /mcp/manifest
POST /mcp/call
```

当前工具：

```text
list_projects
list_chapters
get_chapter_context
```

验收：

- `GET /health` 返回 online。
- `GET /mcp/manifest` 返回工具清单。
- `POST /mcp/call` 可以列出项目、章节和章节上下文。

---

## 十四、实施任务拆分

### 任务 1：后端模型扩展

修改：

- `backend/app/models/models.py`
- `backend/app/core/database.py`

完成：

- Chapter 扩展字段。
- MemoryEntry 扩展字段。
- 新增 CharacterRelationship。
- 新增 CharacterState。
- 新增 ProjectProgress。
- 新增 ChapterVersion。
- SQLite 旧表补列。

验收：

```bash
python -m unittest discover -s backend/tests -v
```

---

### 任务 2：后端 Schema + CRUD API

修改：

- `backend/app/schemas/schemas.py`
- `backend/app/routers/management.py`

完成：

- 章节正文保存/预览/版本 API。
- 人物关系 CRUD。
- 角色状态 CRUD。
- 当前进度 GET/PUT。
- 记忆扩展字段 CRUD。

验收：

- TestClient 创建/读取/更新/删除全部通过。

---

### 任务 3：ContextAssemblyService

新增：

- `backend/app/services/context_assembly_service.py`

完成：

- 组装项目、章节、大纲、设定、角色、服饰、人物关系、角色状态、记忆、当前进度。
- 输出 prompt 文本。

验收：

- 单元测试确认 prompt 包含关键上下文。

---

### 任务 4：章节正文生成接口

修改：

- `backend/app/services/ai_service.py`
- `backend/app/routers/generation.py`

完成：

- `generate_text` 统一文本生成入口。
- `generate_chapter_content`。
- `/generate/chapter-content/{chapter_id}`。
- 生成后保存正文和版本。

验收：

- mock AI 返回正文后可保存到 Chapter。

---

### 任务 5：前端章节创作升级

修改：

- `frontend/src/views/project/ChapterTab.vue`

完成：

- 章节详情。
- 正文编辑器。
- 预览模式。
- 保存正文。
- 版本历史。
- 生成章节正文按钮。

验收：

- 保存后刷新仍显示正文。

---

### 任务 6：记忆库前端

新增：

- `frontend/src/views/project/MemoryPanel.vue`

完成：

- 记忆 CRUD。
- 类型筛选。
- 章节/角色关联。
- 重要度和启用开关。

---

### 任务 7：人物关系和当前状态前端

新增：

- `frontend/src/views/project/RelationshipPanel.vue`
- `frontend/src/views/project/ProgressPanel.vue`

完成：

- 人物关系 CRUD。
- 当前进度编辑。
- 角色状态 CRUD。

---

### 任务 8：ProjectView 集成

修改：

- `frontend/src/views/ProjectView.vue`

完成：

Tab 调整为：

```text
1. 故事与配置
2. 设定中心
3. 章节创作
4. 关系与状态
5. 记忆库
6. 角色工坊
7. 分镜画布
```

---

### 任务 9：测试与 MCP 验收

新增/修改：

- `backend/tests/test_novel_system.py`

执行：

```bash
python -m unittest discover -s backend/tests -v
pnpm --dir frontend build
```

MCP 验收：

- 全流程页面操作。
- 控制台 0 error。
- 网络请求无 4xx/5xx。

---

## 十四、最终验收标准

完成后必须满足：

1. 章节正文可保存。
2. 章节正文可预览。
3. 刷新页面正文不丢失。
4. 章节版本历史可查看。
5. 人物关系可新增/编辑/删除。
6. 当前进度可保存。
7. 角色状态可保存。
8. 记忆库可管理。
9. AI 生成章节正文时会读取上下文。
10. 分镜能按章节过滤。
11. 后端测试通过。
12. 前端构建通过。
13. MCP 真实页面验收通过。

---

## 十五、推荐实施顺序

必须按以下顺序：

```text
1. 后端模型扩展
2. 后端 API
3. 后端测试
4. ContextAssemblyService
5. 章节生成接口
6. 前端章节创作
7. 前端记忆库
8. 前端人物关系/当前进度
9. ProjectView 集成
10. 构建 + 测试 + MCP 验收
```

这样可以避免前端先写完但接口不稳定。
