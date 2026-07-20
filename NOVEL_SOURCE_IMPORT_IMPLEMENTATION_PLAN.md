# 整本小说导入与原文驱动创作实现计划

## 目标

支持用户导入整本 `.txt` 小说，系统保存原文、自动切分章节，并让 AI 基于原文生成完整项目骨架：设定、角色、服饰、关系、大纲、章节任务、进度和记忆。后续生成某一章正文或分镜时，AI 应读取该章对应原文与项目上下文，而不是只靠概括信息乱编。

目标用户流程：

1. 新建项目。
2. 在故事页导入整本小说 TXT。
3. 系统自动识别编码、保存全文、切分章节。
4. 前端显示导入文件、总字数、识别章节数、章节列表。
5. 点击“基于原文初始化项目”。
6. 后台任务分析原文并生成设定、角色、关系、大纲、章节任务、进度、记忆。
7. 打开章节页，看到项目章节与原文章节的关联。
8. 点击生成章节正文/分镜时，AI 自动读取对应原文章节、相邻章节摘要和项目设定。

---

## 核心原则

- 不把整本小说全文直接塞给 AI。
- 原文和 AI 生成正文分开存储。
- `Project.story_input` 可继续保存用户输入，但不作为唯一原文存储。
- 新增原文导入层：`SourceImport` 和 `SourceChapter`。
- 章节生成优先读取 `Chapter.source_chapter_id` 对应的 `SourceChapter.raw_text`。
- 第一版先做稳定的一对一映射：一个漫画章节对应一个原文章节。
- 后续再支持一章拆多章、多章合一章、自定义切章正则。

---

## 阶段 1：原文导入与自动切章

### 目标

导入整本小说后，后端保存全文并自动切分章节，前端可以看到章节列表和原文预览。

### 后端改动

#### 1. 修改 `backend/app/models/models.py`

新增 `SourceImport`：

```python
class SourceImport(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    file_name: str
    raw_text: str
    text_length: int = 0
    chapter_count: int = 0
    import_status: str = "imported"
    split_strategy: str = "auto"
    book_summary: Optional[str] = None
    world_summary: Optional[str] = None
    character_summary: Optional[str] = None
    outline_summary: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

新增 `SourceChapter`：

```python
class SourceChapter(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    source_import_id: int = Field(foreign_key="sourceimport.id", index=True)
    sequence: int
    title: str
    raw_text: str
    raw_word_count: int = 0
    summary_short: Optional[str] = None
    summary_medium: Optional[str] = None
    key_characters: list = Field(default_factory=list, sa_column=Column(JSON))
    key_locations: list = Field(default_factory=list, sa_column=Column(JSON))
    key_events: list = Field(default_factory=list, sa_column=Column(JSON))
    time_markers: list = Field(default_factory=list, sa_column=Column(JSON))
    mapped_chapter_id: Optional[int] = Field(default=None, foreign_key="chapter.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

扩展 `Chapter`：

```python
source_chapter_id: Optional[int] = Field(default=None, foreign_key="sourcechapter.id")
adaptation_mode: str = "adapt"
source_context_note: Optional[str] = None
```

#### 2. 修改 `backend/app/schemas/schemas.py`

新增 schema：

- `SourceImportCreate`
- `SourceImportRead`
- `SourceChapterRead`
- `SourceChapterUpdate`
- `SourceImportWithChapters`

#### 3. 新增 `backend/app/services/source_import_service.py`

实现：

```python
def split_novel_chapters(raw_text: str) -> list[dict]:
    ...
```

第一版支持：

```text
第1章 标题
第 1 章 标题
第001章 标题
第一章 标题
第十章 标题
第1267章 标题
第1回 标题
第1节 标题
```

推荐正则：

```regex
(?m)^\s*(第\s*[0-9一二三四五六七八九十百千万零〇两]+\s*[章节回卷].*)$
```

如果没有匹配到章节标题，则创建一个章节：

```text
sequence = 1
title = 全文
raw_text = 全文
```

#### 4. 新增 `backend/app/routers/source.py`

接口：

```http
POST /api/v1/projects/{project_id}/source-imports
GET /api/v1/projects/{project_id}/source-imports
GET /api/v1/projects/{project_id}/source-imports/{source_import_id}
GET /api/v1/projects/{project_id}/source-chapters
GET /api/v1/projects/{project_id}/source-chapters/{source_chapter_id}
PUT /api/v1/projects/{project_id}/source-chapters/{source_chapter_id}
POST /api/v1/projects/{project_id}/source-imports/{source_import_id}/resplit
```

#### 5. 修改 `backend/app/main.py`

注册 source router：

```python
from app.routers import source
app.include_router(source.router, prefix="/api/v1", tags=["source"])
```

### 前端改动

#### 1. 修改 `frontend/src/views/project/StoryTab.vue`

新增“整本小说导入”区域：

- 文件名
- 总字数
- 识别章节数
- 保存原文并切章按钮
- 章节列表预览
- 原文预览弹窗

保留现有“一句话 AI 初始化”。

#### 2. API 调用

导入后调用：

```js
POST /api/v1/projects/${projectId}/source-imports
```

章节列表调用：

```js
GET /api/v1/projects/${projectId}/source-chapters?limit=50
```

### 阶段 1 验收

- 导入 `D:\download\644566\我真不想修仙啊！.txt` 不乱码。
- 后端生成 `SourceImport`。
- 后端生成约 1267 个 `SourceChapter`。
- 前端显示文件名、总字数、章节数。
- 可以打开第 1 章看到正常中文原文。
- `python -m unittest discover -s backend/tests -v` 通过。
- `pnpm --dir frontend build` 通过。

---

## 阶段 2：原文摘要与分析任务

### 目标

后台任务对原文章节进行摘要，生成整本小说级摘要、世界观摘要、角色摘要和大纲摘要。

### 后端改动

#### 1. 修改 `backend/app/routers/generation.py`

新增任务类型：

```text
source_analysis
```

新增接口：

```http
POST /api/v1/generate/source-analyze/{project_id}
```

#### 2. 新增或扩展服务

可新增：

```text
backend/app/services/source_analysis_service.py
```

职责：

- 读取 `SourceChapter`
- 对章节生成 `summary_short`
- 每 5-10 章生成分组摘要
- 汇总生成 `SourceImport.book_summary`
- 汇总生成 `world_summary`、`character_summary`、`outline_summary`

### AI 输入策略

逐章摘要 prompt：

```text
请总结以下小说章节，输出 JSON：
{
  "summary_short": "200-400字摘要",
  "key_characters": [],
  "key_locations": [],
  "key_events": [],
  "time_markers": []
}
```

整本摘要 prompt 输入：

- 章节目录
- 前 20 章摘要
- 每 10 章分组摘要
- 关键角色/地点/事件列表

不要输入全文。

### 前端改动

`StoryTab.vue` 新增按钮：

```text
分析原文
```

任务进度显示在现有 `TaskManager.vue`。

`TaskManager.vue` 增加任务名：

```js
source_analysis: '原文分析'
```

### 阶段 2 验收

- 点击分析后后台任务可见。
- 任务日志显示正在分析章节。
- `SourceChapter.summary_short` 有内容。
- `SourceImport.book_summary` 有内容。

---

## 阶段 3：基于原文初始化项目骨架

### 目标

AI 基于原文摘要和章节结构生成项目设定、角色、服饰、关系、大纲、章节任务、进度、记忆。

### 后端改动

#### 1. 修改 `backend/app/routers/generation.py`

新增接口：

```http
POST /api/v1/generate/project-initialize-from-source/{project_id}
```

任务类型：

```text
source_project_initialization
```

#### 2. 复用现有初始化落库逻辑

现有 `project_initialization` 已经能写入：

- Project
- SettingCategory
- SettingEntry
- Character
- CharacterOutfit
- CharacterRelationship
- Outline
- Chapter
- ChapterTask
- MemoryEntry
- ProjectProgress

需要抽取公共函数，避免复制一大段落库逻辑。

建议抽成：

```python
def persist_project_initialization_payload(session, project_id, payload, source_chapters=None):
    ...
```

#### 3. 章节关联原文

AI 输出 chapters 时，尽量带 `source_sequence`：

```json
{
  "sequence": 1,
  "source_sequence": 1,
  "title": "第1章 修仙可以，吃苦不行",
  "summary": "..."
}
```

落库时：

```python
chapter.source_chapter_id = source_chapter_by_sequence.get(source_sequence).id
source_chapter.mapped_chapter_id = chapter.id
```

### AI 输入策略

初始化 prompt 输入：

- `SourceImport.book_summary`
- `SourceImport.world_summary`
- `SourceImport.character_summary`
- `SourceImport.outline_summary`
- 章节目录
- 前 20 章摘要
- 每隔 20-50 章抽样摘要

输出结构沿用现有初始化 JSON，但 chapters 增加 `source_sequence`。

### 前端改动

`StoryTab.vue` 新增按钮：

```text
基于原文生成项目设定
```

调用：

```js
POST /api/v1/generate/project-initialize-from-source/${projectId}
```

完成后刷新：

- 设定中心
- 章节创作
- 人物关系
- 当前进度
- 记忆库

现有 `ProjectView.vue` 的任务完成刷新机制可复用。

### 阶段 3 验收

- 导入小说后可一键生成完整设定。
- 角色名、设定不重复。
- 章节列表生成，并关联原文章节。
- 打开章节页能看到关联原文章节信息。

---

## 阶段 4：章节正文生成读取原文

### 目标

生成某个章节正文时，AI 精准读取对应原文章节，而不是只根据大纲生成。

### 后端改动

#### 1. 修改 `backend/app/services/context_assembly_service.py`

新增方法：

```python
def build_source_context_for_chapter(self, chapter_id: int) -> dict:
    ...
```

返回：

```json
{
  "source_title": "第1章 修仙可以，吃苦不行",
  "source_text": "原文",
  "previous_summary": "上一章摘要",
  "next_summary": "下一章摘要",
  "book_summary": "全书摘要"
}
```

#### 2. 修改 `generate_chapter_content`

文件：`backend/app/services/ai_service.py` 或调用处 `generation.py`

将 prompt 改为包含：

```text
【原文章节】
标题：...
原文：...

【相邻章节摘要】
上一章：...
下一章：...

【改编要求】
请基于原文生成漫画化章节正文，不要偏离原文事件顺序。
```

如果 `source_text` 太长，先裁剪或摘要：

- 小于约 20k 字：直接使用。
- 超过约 20k 字：取开头、中段、结尾 + 摘要。

### 前端改动

`ChapterTab.vue` 新增原文区域：

```text
关联原文章节：第1章 修仙可以，吃苦不行
[查看原文]
[基于本章原文生成正文]
```

### 阶段 4 验收

- 第 1 章生成正文时 prompt 包含第 1 章原文。
- 不包含整本全文。
- AI 生成内容与原文事件一致。

---

## 阶段 5：分镜生成读取原文

### 目标

生成章节分镜时，也读取对应原文章节和章节正文。

### 后端改动

修改：

```text
backend/app/routers/generation.py
```

`chapter-storyboard` 生成 prompt 加入：

- 当前原文章节
- 当前 AI 正文
- 章节目标
- 角色服饰
- 分镜要求

### 前端改动

`StoryboardTab.vue` 可选显示来源章节。

### 阶段 5 验收

- 分镜事件顺序贴合原文。
- 分镜角色和服饰遵循设定。

---

## 测试计划

### 后端测试

新增：

```text
backend/tests/test_source_import.py
```

覆盖：

1. `split_novel_chapters`：阿拉伯数字章节。
2. `split_novel_chapters`：中文数字章节。
3. `split_novel_chapters`：无章节标题降级全文。
4. 导入接口创建 `SourceImport`。
5. 导入接口批量创建 `SourceChapter`。
6. 原文章节列表分页。
7. 原文章节详情。
8. 原文章节更新。
9. 基于原文初始化时 `Chapter.source_chapter_id` 正确关联。
10. 章节生成上下文包含当前原文和相邻摘要。

继续运行现有：

```bash
python -m unittest discover -s backend/tests -v
```

### 前端验证

```bash
pnpm --dir frontend build
```

浏览器验收：

1. 打开 `http://127.0.0.1:8000`。
2. 新建项目。
3. 导入 `我真不想修仙啊！.txt`。
4. 确认不乱码。
5. 确认识别章节数。
6. 打开第 1 章原文预览。
7. 点击基于原文生成设定。
8. 任务完成后检查设定、角色、章节、关系、进度、记忆。
9. 打开第 1 章。
10. 确认关联原文。
11. 点击生成正文。
12. 确认生成内容贴合原文。

---

## 实施顺序

1. 阶段 1：模型、schema、切章服务、source router、前端导入列表。
2. 阶段 1 测试和浏览器验收。
3. 阶段 2：原文摘要任务。
4. 阶段 3：基于原文初始化项目。
5. 阶段 4：章节正文生成读取原文。
6. 阶段 5：章节分镜读取原文。
7. 最终完整测试、构建、MCP/浏览器验收。

---

## MVP 范围

第一轮必须完成：

- `SourceImport`
- `SourceChapter`
- TXT 导入保存原文
- 自动切章
- 前端显示原文章节列表
- 基于原文初始化项目
- `Chapter.source_chapter_id` 映射
- 章节正文生成读取当前章原文

第一轮暂不做：

- 多导入版本对比
- 多对多章节映射
- 自定义切章正则 UI
- 原文全文搜索
- 大规模向量检索
- 自动合并/拆分章节 UI

---

## 风险

1. 小说太长：必须分层摘要，不直接塞全文。
2. 切章规则误判：第一版先用通用规则，保留手工修正接口。
3. AI 摘要慢：可以先摘要前 20-50 章，后续按需补摘要。
4. SQLite 文件变大：本地项目可接受；未来可改为原文存文件、数据库存路径。
5. 初始化重复：沿用现有“已有内容拒绝初始化”机制，避免重复污染。
