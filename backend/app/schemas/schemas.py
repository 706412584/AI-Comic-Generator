from pydantic import BaseModel
from typing import Optional, Dict, List, Any
from datetime import datetime
from app.models.models import (
    ModelConfigBase, ProjectBase, CharacterBase, StoryboardItemBase, GlobalConfigBase, TaskBase,
    SettingCategoryBase, SettingEntryBase, ChapterBase, SourceImportBase, SourceChapterBase,
    OutlineBase, CharacterOutfitBase, MemoryEntryBase, ChapterTaskBase, CharacterRelationshipBase,
    CharacterStateBase, ProjectProgressBase, ChapterVersionBase,
    ModelConfig, Project, Character, StoryboardItem, GlobalConfig, Task
)

# ModelConfig
class ModelConfigCreate(ModelConfigBase):
    pass

class ModelConfigUpdate(BaseModel):
    provider: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model_name: Optional[str] = None
    model_type: Optional[str] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None

# Read Models for nested response
class CharacterOutfitCreate(CharacterOutfitBase):
    pass

class CharacterOutfitUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    scene: Optional[str] = None
    colors: Optional[str] = None
    materials: Optional[str] = None
    accessories: Optional[str] = None
    state: Optional[str] = None
    reference_image_url: Optional[str] = None
    is_default: Optional[bool] = None

class CharacterOutfitRead(CharacterOutfitBase):
    id: int
    project_id: str
    character_id: int
    created_at: datetime
    updated_at: datetime

class CharacterRead(CharacterBase):
    id: int
    project_id: str
    outfits: List[CharacterOutfitRead] = []

class StoryboardItemRead(StoryboardItemBase):
    id: int
    project_id: str

class GlobalConfigRead(GlobalConfigBase):
    id: int
    project_id: str

class TaskRead(TaskBase):
    id: str
    project_id: str
    created_at: datetime
    updated_at: datetime
    logs: List[str] = []

class AgentRunRead(BaseModel):
    id: int
    task_id: str
    project_id: str
    chapter_id: Optional[int] = None
    agent_name: str
    agent_version: str
    status: str
    current_step: Optional[str] = None
    step_index: int
    total_steps: int
    input_payload: Dict[str, Any] = {}
    state_payload: Dict[str, Any] = {}
    result_payload: Dict[str, Any] = {}
    error_payload: Dict[str, Any] = {}
    created_at: datetime
    started_at: Optional[datetime] = None
    updated_at: datetime
    finished_at: Optional[datetime] = None

# Project
class ProjectCreate(ProjectBase):
    pass

class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    story_input: Optional[str] = None
    theme: Optional[str] = None
    language: Optional[str] = None
    panel_count: Optional[int] = None
    aspect_ratio: Optional[str] = None
    resolution: Optional[str] = None
    current_chapter_id: Optional[int] = None
    workflow_mode: Optional[str] = None
    memory_enabled: Optional[bool] = None
    setting_mode: Optional[str] = None
    outline_enabled: Optional[bool] = None

class SettingCategoryCreate(SettingCategoryBase):
    pass

class SettingCategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None

class SettingCategoryRead(SettingCategoryBase):
    id: int
    project_id: str
    created_at: datetime
    updated_at: datetime

class SettingEntryCreate(SettingEntryBase):
    pass

class SettingEntryUpdate(BaseModel):
    category_id: Optional[int] = None
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[List[str]] = None
    importance: Optional[int] = None
    is_active: Optional[bool] = None

class SettingEntryRead(SettingEntryBase):
    id: int
    project_id: str
    created_at: datetime
    updated_at: datetime

class ChapterCreate(ChapterBase):
    pass

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
    word_count: Optional[int] = None
    source_chapter_id: Optional[int] = None
    adaptation_mode: Optional[str] = None
    source_context_note: Optional[str] = None
    chapter_metadata: Optional[Dict[str, Any]] = None

class ChapterRead(ChapterBase):
    id: int
    project_id: str
    created_at: datetime
    updated_at: datetime

class SourceImportCreate(BaseModel):
    file_name: str
    raw_text: str
    split_pattern: Optional[str] = None

class SourceResplitRequest(BaseModel):
    split_pattern: Optional[str] = None

class SourceResplitPreview(BaseModel):
    chapter_count: int
    chapters: List[Dict[str, Any]] = []

class SourceImportRead(SourceImportBase):
    id: int
    project_id: str
    created_at: datetime
    updated_at: datetime
    analyzed_chapter_count: int = 0
    unanalyzed_chapter_count: int = 0

class SourceChapterRead(SourceChapterBase):
    id: int
    project_id: str
    created_at: datetime
    updated_at: datetime

class SourceChapterUpdate(BaseModel):
    title: Optional[str] = None
    raw_text: Optional[str] = None
    analysis_status: Optional[str] = None
    analysis_error: Optional[str] = None
    analysis_attempts: Optional[int] = None
    summary_short: Optional[str] = None
    summary_medium: Optional[str] = None
    key_characters: Optional[List[str]] = None
    key_locations: Optional[List[str]] = None
    key_events: Optional[List[str]] = None
    time_markers: Optional[List[str]] = None
    mapped_chapter_id: Optional[int] = None

class SourceImportWithChapters(SourceImportRead):
    chapters: List[SourceChapterRead] = []

class ChapterContentUpdate(BaseModel):
    title: Optional[str] = None
    content: str
    preview_text: Optional[str] = None
    change_note: Optional[str] = None

class OutlineCreate(OutlineBase):
    pass

class OutlineUpdate(BaseModel):
    scope: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    chapter_id: Optional[int] = None
    sort_order: Optional[int] = None

class OutlineRead(OutlineBase):
    id: int
    project_id: str
    created_at: datetime
    updated_at: datetime

class MemoryEntryCreate(MemoryEntryBase):
    pass

class MemoryEntryUpdate(BaseModel):
    scope: Optional[str] = None
    content: Optional[str] = None
    memory_type: Optional[str] = None
    chapter_id: Optional[int] = None
    character_id: Optional[int] = None
    tags: Optional[List[str]] = None
    importance: Optional[int] = None
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    is_active: Optional[bool] = None

class MemoryEntryRead(MemoryEntryBase):
    id: int
    project_id: str
    created_at: datetime
    updated_at: datetime

class ChapterTaskCreate(ChapterTaskBase):
    pass

class ChapterTaskUpdate(BaseModel):
    chapter_id: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    sort_order: Optional[int] = None
    result: Optional[Dict] = None

class ChapterTaskRead(ChapterTaskBase):
    id: int
    project_id: str
    created_at: datetime
    updated_at: datetime

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

class ChapterVersionCreate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    preview_text: Optional[str] = None
    word_count: Optional[int] = None
    change_note: Optional[str] = None

class ChapterVersionRead(ChapterVersionBase):
    id: int
    project_id: str
    created_at: datetime

class ProjectRead(ProjectBase):
    id: str
    created_at: datetime
    updated_at: datetime
    characters: List[CharacterRead] = []
    storyboard_items: List[StoryboardItemRead] = []
    global_config: Optional[GlobalConfigRead] = None
    setting_categories: List[SettingCategoryRead] = []
    setting_entries: List[SettingEntryRead] = []
    chapters: List[ChapterRead] = []
    outlines: List[OutlineRead] = []
    memories: List[MemoryEntryRead] = []
    chapter_tasks: List[ChapterTaskRead] = []


# Assistant workbench chat
class AgentMessageCreate(BaseModel):
    content: str
    conversation_id: Optional[int] = None
    allow_writes: Optional[bool] = True


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
    tools_enabled: Optional[bool] = None
    text_provider: Optional[str] = None
    active_task_id: Optional[str] = None
    message_count: Optional[int] = None


class AgentConversationCreate(BaseModel):
    title: Optional[str] = None


class AgentConversationUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None


class AssistantChatResponse(BaseModel):
    conversation_id: int
    user_message: AgentMessageRead
    task_id: str


class AssistantRegenerateRequest(BaseModel):
    allow_writes: Optional[bool] = True
