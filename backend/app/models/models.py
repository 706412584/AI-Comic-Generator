from typing import Optional, List, Dict, Any
from sqlmodel import SQLModel, Field, Relationship, Column, JSON
from datetime import datetime
import uuid

# --- Base Models ---

class ModelConfigBase(SQLModel):
    provider: str
    api_key: str
    base_url: Optional[str] = None
    model_name: str
    model_type: str
    is_active: bool = True

class ProjectBase(SQLModel):
    title: str
    description: Optional[str] = None
    story_input: Optional[str] = None
    # Generation Preferences
    theme: Optional[str] = None
    language: Optional[str] = "zh-CN"
    panel_count: Optional[int] = 16
    aspect_ratio: Optional[str] = "16:9"
    resolution: Optional[str] = "2K"
    # Creative Management
    current_chapter_id: Optional[int] = None
    workflow_mode: Optional[str] = "comic"
    memory_enabled: bool = True
    setting_mode: Optional[str] = "basic"
    outline_enabled: bool = True

class CharacterBase(SQLModel):
    name: str
    data: Dict = Field(default={}, sa_column=Column(JSON))
    image_url: Optional[str] = None
    summary: Optional[str] = None
    aliases: List[str] = Field(default=[], sa_column=Column(JSON))
    status: Optional[str] = "active"
    default_outfit_id: Optional[int] = None

class StoryboardItemBase(SQLModel):
    sequence: int
    data: Dict = Field(default={}, sa_column=Column(JSON))
    image_url: Optional[str] = None
    chapter_id: Optional[int] = Field(default=None, foreign_key="chapter.id")
    selected_outfits: Dict = Field(default={}, sa_column=Column(JSON))
    status: Optional[str] = "draft"
    prompt_cache: Optional[str] = None

class GlobalConfigBase(SQLModel):
    data: Dict = Field(default={}, sa_column=Column(JSON))

class TaskBase(SQLModel):
    type: str # 'storyboard', 'image_generation', 'export'
    status: str # 'pending', 'processing', 'completed', 'failed'
    progress: int = 0 # 0-100
    message: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    scope_type: Optional[str] = None
    scope_id: Optional[str] = None
    input_payload: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    retry_count: int = 0
    retry_of_task_id: Optional[str] = None
    result: Dict = Field(default={}, sa_column=Column(JSON))

class ImageHistoryBase(SQLModel):
    entity_type: str # 'character' or 'storyboard_item'
    entity_id: int
    image_url: str

class SettingCategoryBase(SQLModel):
    name: str
    description: Optional[str] = None
    sort_order: int = 0

class SettingEntryBase(SQLModel):
    category_id: Optional[int] = Field(default=None, foreign_key="settingcategory.id")
    title: str
    content: str
    tags: List[str] = Field(default=[], sa_column=Column(JSON))
    importance: int = 3
    is_active: bool = True

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
    source_chapter_id: Optional[int] = Field(default=None, foreign_key="sourcechapter.id")
    adaptation_mode: str = "adapt"
    source_context_note: Optional[str] = None
    chapter_metadata: Dict[str, Any] = Field(default_factory=dict, sa_column=Column("metadata", JSON))

class SourceImportBase(SQLModel):
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
    summary_layers: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

class SourceChapterBase(SQLModel):
    source_import_id: int = Field(foreign_key="sourceimport.id")
    sequence: int
    title: str
    raw_text: str
    raw_word_count: int = 0
    analysis_status: str = "pending"
    analysis_error: Optional[str] = None
    analysis_attempts: int = 0
    summary_short: Optional[str] = None
    summary_medium: Optional[str] = None
    key_characters: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    key_locations: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    key_events: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    time_markers: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    mapped_chapter_id: Optional[int] = Field(default=None, foreign_key="chapter.id")

class OutlineBase(SQLModel):
    scope: str = "project"
    title: str
    content: str
    chapter_id: Optional[int] = Field(default=None, foreign_key="chapter.id")
    sort_order: int = 0

class CharacterOutfitBase(SQLModel):
    name: str
    description: str
    scene: Optional[str] = None
    colors: Optional[str] = None
    materials: Optional[str] = None
    accessories: Optional[str] = None
    state: Optional[str] = None
    reference_image_url: Optional[str] = None
    is_default: bool = False

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

class ChapterTaskBase(SQLModel):
    chapter_id: Optional[int] = Field(default=None, foreign_key="chapter.id")
    title: str
    description: Optional[str] = None
    type: Optional[str] = None
    status: str = "todo"
    sort_order: int = 0
    result: Dict = Field(default={}, sa_column=Column(JSON))

class CharacterRelationshipBase(SQLModel):
    source_character_id: int = Field(foreign_key="character.id")
    target_character_id: int = Field(foreign_key="character.id")
    relationship_type: str
    description: Optional[str] = None
    status: str = "active"
    intensity: int = 3
    chapter_id: Optional[int] = Field(default=None, foreign_key="chapter.id")
    tags: List[str] = Field(default=[], sa_column=Column(JSON))

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

class ChapterVersionBase(SQLModel):
    chapter_id: int = Field(foreign_key="chapter.id")
    title: str
    content: str
    preview_text: Optional[str] = None
    word_count: int = 0
    change_note: Optional[str] = None
    version_no: int = 1

class AgentRunBase(SQLModel):
    agent_name: str
    agent_version: str = "1.0"
    status: str = "pending"
    current_step: Optional[str] = None
    step_index: int = 0
    total_steps: int = 0
    input_payload: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    state_payload: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    result_payload: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    error_payload: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

class AgentConversationBase(SQLModel):
    title: str = "创作助手"
    status: str = "active"

class AgentMessageBase(SQLModel):
    role: str  # user | assistant | system
    content: str
    intent: Optional[str] = None
    task_id: Optional[str] = Field(default=None, foreign_key="task.id")
    payload: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

# --- Table Models ---

class ModelConfig(ModelConfigBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

class Project(ProjectBase, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    characters: List["Character"] = Relationship(back_populates="project", sa_relationship_kwargs={"cascade": "all, delete"})
    storyboard_items: List["StoryboardItem"] = Relationship(back_populates="project", sa_relationship_kwargs={"cascade": "all, delete"})
    global_config: Optional["GlobalConfig"] = Relationship(back_populates="project", sa_relationship_kwargs={"cascade": "all, delete"})
    tasks: List["Task"] = Relationship(back_populates="project", sa_relationship_kwargs={"cascade": "all, delete"})
    image_history: List["ImageHistory"] = Relationship(back_populates="project", sa_relationship_kwargs={"cascade": "all, delete"})
    setting_categories: List["SettingCategory"] = Relationship(back_populates="project", sa_relationship_kwargs={"cascade": "all, delete"})
    setting_entries: List["SettingEntry"] = Relationship(back_populates="project", sa_relationship_kwargs={"cascade": "all, delete"})
    chapters: List["Chapter"] = Relationship(back_populates="project", sa_relationship_kwargs={"cascade": "all, delete"})
    outlines: List["Outline"] = Relationship(back_populates="project", sa_relationship_kwargs={"cascade": "all, delete"})
    memories: List["MemoryEntry"] = Relationship(back_populates="project", sa_relationship_kwargs={"cascade": "all, delete"})
    chapter_tasks: List["ChapterTask"] = Relationship(back_populates="project", sa_relationship_kwargs={"cascade": "all, delete"})
    relationships: List["CharacterRelationship"] = Relationship(back_populates="project", sa_relationship_kwargs={"cascade": "all, delete"})
    character_states: List["CharacterState"] = Relationship(back_populates="project", sa_relationship_kwargs={"cascade": "all, delete"})
    progress: Optional["ProjectProgress"] = Relationship(back_populates="project", sa_relationship_kwargs={"cascade": "all, delete"})
    chapter_versions: List["ChapterVersion"] = Relationship(back_populates="project", sa_relationship_kwargs={"cascade": "all, delete"})
    source_imports: List["SourceImport"] = Relationship(back_populates="project", sa_relationship_kwargs={"cascade": "all, delete"})
    source_chapters: List["SourceChapter"] = Relationship(back_populates="project", sa_relationship_kwargs={"cascade": "all, delete"})
    agent_runs: List["AgentRun"] = Relationship(back_populates="project", sa_relationship_kwargs={"cascade": "all, delete"})
    agent_conversations: List["AgentConversation"] = Relationship(back_populates="project", sa_relationship_kwargs={"cascade": "all, delete"})

class Character(CharacterBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    project: Project = Relationship(back_populates="characters")
    outfits: List["CharacterOutfit"] = Relationship(back_populates="character", sa_relationship_kwargs={"cascade": "all, delete"})
    source_relationships: List["CharacterRelationship"] = Relationship(
        back_populates="source_character",
        sa_relationship_kwargs={"foreign_keys": "[CharacterRelationship.source_character_id]", "cascade": "all, delete"},
    )
    target_relationships: List["CharacterRelationship"] = Relationship(
        back_populates="target_character",
        sa_relationship_kwargs={"foreign_keys": "[CharacterRelationship.target_character_id]", "cascade": "all, delete"},
    )
    states: List["CharacterState"] = Relationship(back_populates="character", sa_relationship_kwargs={"cascade": "all, delete"})

class StoryboardItem(StoryboardItemBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    project: Project = Relationship(back_populates="storyboard_items")
    chapter: Optional["Chapter"] = Relationship(back_populates="storyboard_items")

class GlobalConfig(GlobalConfigBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    project: Project = Relationship(back_populates="global_config")

class Task(TaskBase, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    logs: List[str] = Field(default=[], sa_column=Column(JSON))

    project: Project = Relationship(back_populates="tasks")
    agent_runs: List["AgentRun"] = Relationship(back_populates="task", sa_relationship_kwargs={"cascade": "all, delete"})

class AgentRun(AgentRunBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: str = Field(foreign_key="task.id")
    project_id: str = Field(foreign_key="project.id")
    chapter_id: Optional[int] = Field(default=None, foreign_key="chapter.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None

    task: Task = Relationship(back_populates="agent_runs")
    project: Project = Relationship(back_populates="agent_runs")

class ImageHistory(ImageHistoryBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    project: Project = Relationship(back_populates="image_history")

class SettingCategory(SettingCategoryBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    project: Project = Relationship(back_populates="setting_categories")
    entries: List["SettingEntry"] = Relationship(back_populates="category")

class SettingEntry(SettingEntryBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    project: Project = Relationship(back_populates="setting_entries")
    category: Optional[SettingCategory] = Relationship(back_populates="entries")

class SourceImport(SourceImportBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    project: Project = Relationship(back_populates="source_imports")
    chapters: List["SourceChapter"] = Relationship(back_populates="source_import", sa_relationship_kwargs={"cascade": "all, delete"})

class SourceChapter(SourceChapterBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    project: Project = Relationship(back_populates="source_chapters")
    source_import: SourceImport = Relationship(back_populates="chapters")

class Chapter(ChapterBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    project: Project = Relationship(back_populates="chapters")
    storyboard_items: List[StoryboardItem] = Relationship(back_populates="chapter")
    outlines: List["Outline"] = Relationship(back_populates="chapter")
    tasks: List["ChapterTask"] = Relationship(back_populates="chapter")
    memories: List["MemoryEntry"] = Relationship(back_populates="chapter")
    relationships: List["CharacterRelationship"] = Relationship(back_populates="chapter")
    character_states: List["CharacterState"] = Relationship(back_populates="chapter")
    progress_entries: List["ProjectProgress"] = Relationship(back_populates="current_chapter")
    versions: List["ChapterVersion"] = Relationship(back_populates="chapter")

class Outline(OutlineBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    project: Project = Relationship(back_populates="outlines")
    chapter: Optional[Chapter] = Relationship(back_populates="outlines")

class CharacterOutfit(CharacterOutfitBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    character_id: int = Field(foreign_key="character.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    character: Character = Relationship(back_populates="outfits")
    states: List["CharacterState"] = Relationship(back_populates="outfit")

class MemoryEntry(MemoryEntryBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    project: Project = Relationship(back_populates="memories")
    chapter: Optional[Chapter] = Relationship(back_populates="memories")
    character: Optional[Character] = Relationship()

class CharacterRelationship(CharacterRelationshipBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    project: Project = Relationship(back_populates="relationships")
    source_character: Character = Relationship(
        back_populates="source_relationships",
        sa_relationship_kwargs={"foreign_keys": "[CharacterRelationship.source_character_id]"},
    )
    target_character: Character = Relationship(
        back_populates="target_relationships",
        sa_relationship_kwargs={"foreign_keys": "[CharacterRelationship.target_character_id]"},
    )
    chapter: Optional[Chapter] = Relationship(back_populates="relationships")

class CharacterState(CharacterStateBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    project: Project = Relationship(back_populates="character_states")
    character: Character = Relationship(back_populates="states")
    chapter: Optional[Chapter] = Relationship(back_populates="character_states")
    outfit: Optional[CharacterOutfit] = Relationship(back_populates="states")

class ProjectProgress(ProjectProgressBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id", unique=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    project: Project = Relationship(back_populates="progress")
    current_chapter: Optional[Chapter] = Relationship(back_populates="progress_entries")

class ChapterVersion(ChapterVersionBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    project: Project = Relationship(back_populates="chapter_versions")
    chapter: Chapter = Relationship(back_populates="versions")

class ChapterTask(ChapterTaskBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    project: Project = Relationship(back_populates="chapter_tasks")
    chapter: Optional[Chapter] = Relationship(back_populates="tasks")

class AgentConversation(AgentConversationBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    project: Project = Relationship(back_populates="agent_conversations")
    messages: List["AgentMessage"] = Relationship(back_populates="conversation", sa_relationship_kwargs={"cascade": "all, delete"})

class AgentMessage(AgentMessageBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="agentconversation.id")
    project_id: str = Field(foreign_key="project.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    conversation: AgentConversation = Relationship(back_populates="messages")
