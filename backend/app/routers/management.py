from typing import List, Optional, Type

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import SQLModel, Session, select

from app.core.database import get_session
from app.models.models import (
    Character,
    CharacterOutfit,
    CharacterRelationship,
    CharacterState,
    Chapter,
    ChapterTask,
    ChapterVersion,
    MemoryEntry,
    Outline,
    Project,
    ProjectProgress,
    SettingCategory,
    SettingEntry,
    SourceChapter,
)
from app.schemas.schemas import (
    CharacterOutfitCreate,
    CharacterOutfitRead,
    CharacterOutfitUpdate,
    CharacterRelationshipCreate,
    CharacterRelationshipRead,
    CharacterRelationshipUpdate,
    CharacterStateCreate,
    CharacterStateRead,
    CharacterStateUpdate,
    ChapterContentUpdate,
    ChapterCreate,
    ChapterRead,
    ChapterTaskCreate,
    ChapterTaskRead,
    ChapterTaskUpdate,
    ChapterUpdate,
    ChapterVersionCreate,
    ChapterVersionRead,
    MemoryEntryCreate,
    MemoryEntryRead,
    MemoryEntryUpdate,
    OutlineCreate,
    OutlineRead,
    OutlineUpdate,
    ProjectProgressRead,
    ProjectProgressUpdate,
    SettingCategoryCreate,
    SettingCategoryRead,
    SettingCategoryUpdate,
    SettingEntryCreate,
    SettingEntryRead,
    SettingEntryUpdate,
)

router = APIRouter()

CHAPTER_STATUSES = {"draft", "planning", "storyboarding", "done"}
CHAPTER_TASK_STATUSES = {"todo", "doing", "done", "blocked", "cancelled"}


def ensure_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def get_project_item(session: Session, model: Type[SQLModel], project_id: str, item_id: int):
    item = session.get(model, item_id)
    if not item or item.project_id != project_id:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


def create_project_item(session: Session, model: Type[SQLModel], project_id: str, item_in: SQLModel):
    ensure_project(session, project_id)
    item = model(project_id=project_id, **item_in.model_dump())
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def update_item(session: Session, item, item_in: BaseModel):
    for key, value in item_in.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def delete_item(session: Session, item):
    session.delete(item)
    session.commit()
    return {"ok": True}


def validate_chapter_input(session: Session, project_id: str, chapter_in: ChapterCreate | ChapterUpdate, chapter_id: int | None = None):
    data = chapter_in.model_dump(exclude_unset=True)
    sequence = data.get("sequence")
    if sequence is not None:
        if sequence < 1:
            raise HTTPException(status_code=400, detail="Chapter sequence must be greater than 0")
        statement = select(Chapter).where(Chapter.project_id == project_id, Chapter.sequence == sequence)
        existing = session.exec(statement).first()
        if existing and existing.id != chapter_id:
            raise HTTPException(status_code=400, detail="Chapter sequence already exists")

    status = data.get("status")
    if status is not None and status not in CHAPTER_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid chapter status")

    source_chapter_id = data.get("source_chapter_id")
    if source_chapter_id is not None:
        source_chapter = session.get(SourceChapter, source_chapter_id)
        if not source_chapter or source_chapter.project_id != project_id:
            raise HTTPException(status_code=404, detail="Source chapter not found")



def validate_chapter_task_input(task_in: ChapterTaskCreate | ChapterTaskUpdate):
    data = task_in.model_dump(exclude_unset=True)
    status = data.get("status")
    if status is not None and status not in CHAPTER_TASK_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid chapter task status")



def validate_optional_project_refs(
    session: Session,
    project_id: str,
    *,
    chapter_id: Optional[int] = None,
    character_id: Optional[int] = None,
    outfit_id: Optional[int] = None,
):
    chapter = None
    character = None
    outfit = None

    if chapter_id is not None:
        chapter = get_project_item(session, Chapter, project_id, chapter_id)
    if character_id is not None:
        character = get_project_item(session, Character, project_id, character_id)
    if outfit_id is not None:
        outfit = get_project_item(session, CharacterOutfit, project_id, outfit_id)

    return chapter, character, outfit



def validate_memory_input(session: Session, project_id: str, memory_in: MemoryEntryCreate | MemoryEntryUpdate):
    data = memory_in.model_dump(exclude_unset=True)
    validate_optional_project_refs(
        session,
        project_id,
        chapter_id=data.get("chapter_id"),
        character_id=data.get("character_id"),
    )



def validate_relationship_input(
    session: Session,
    project_id: str,
    relationship_in: CharacterRelationshipCreate | CharacterRelationshipUpdate,
    existing: Optional[CharacterRelationship] = None,
):
    data = relationship_in.model_dump(exclude_unset=True)
    source_character_id = data.get("source_character_id", existing.source_character_id if existing else None)
    target_character_id = data.get("target_character_id", existing.target_character_id if existing else None)
    chapter_id = data.get("chapter_id", existing.chapter_id if existing else None)
    intensity = data.get("intensity", existing.intensity if existing else None)

    if source_character_id is None or target_character_id is None:
        raise HTTPException(status_code=400, detail="Both source_character_id and target_character_id are required")
    if source_character_id == target_character_id:
        raise HTTPException(status_code=400, detail="source_character_id and target_character_id must be different")

    validate_optional_project_refs(
        session,
        project_id,
        chapter_id=chapter_id,
        character_id=source_character_id,
    )
    validate_optional_project_refs(session, project_id, character_id=target_character_id)

    if intensity is not None and not 1 <= intensity <= 5:
        raise HTTPException(status_code=400, detail="Relationship intensity must be between 1 and 5")



def validate_character_state_input(
    session: Session,
    project_id: str,
    state_in: CharacterStateCreate | CharacterStateUpdate,
    existing: Optional[CharacterState] = None,
):
    data = state_in.model_dump(exclude_unset=True)
    character_id = data.get("character_id", existing.character_id if existing else None)
    chapter_id = data.get("chapter_id", existing.chapter_id if existing else None)
    outfit_id = data.get("outfit_id", existing.outfit_id if existing else None)

    if character_id is None:
        raise HTTPException(status_code=400, detail="character_id is required")

    _, character, outfit = validate_optional_project_refs(
        session,
        project_id,
        chapter_id=chapter_id,
        character_id=character_id,
        outfit_id=outfit_id,
    )

    if outfit and outfit.character_id != character.id:
        raise HTTPException(status_code=400, detail="Outfit does not belong to character")



def validate_progress_input(session: Session, project_id: str, progress_in: ProjectProgressUpdate):
    data = progress_in.model_dump(exclude_unset=True)
    current_chapter_id = data.get("current_chapter_id")
    if current_chapter_id is not None:
        get_project_item(session, Chapter, project_id, current_chapter_id)



def next_chapter_version_no(session: Session, project_id: str, chapter_id: int) -> int:
    statement = (
        select(ChapterVersion)
        .where(ChapterVersion.project_id == project_id, ChapterVersion.chapter_id == chapter_id)
        .order_by(ChapterVersion.version_no.desc(), ChapterVersion.id.desc())
    )
    latest = session.exec(statement).first()
    return 1 if latest is None else latest.version_no + 1


@router.get("/{project_id}/setting-categories", response_model=List[SettingCategoryRead])
def list_setting_categories(project_id: str, session: Session = Depends(get_session)):
    ensure_project(session, project_id)
    statement = select(SettingCategory).where(SettingCategory.project_id == project_id).order_by(SettingCategory.sort_order, SettingCategory.id)
    return session.exec(statement).all()


@router.post("/{project_id}/setting-categories", response_model=SettingCategoryRead)
def create_setting_category(project_id: str, category_in: SettingCategoryCreate, session: Session = Depends(get_session)):
    return create_project_item(session, SettingCategory, project_id, category_in)


@router.put("/{project_id}/setting-categories/{category_id}", response_model=SettingCategoryRead)
def update_setting_category(project_id: str, category_id: int, category_in: SettingCategoryUpdate, session: Session = Depends(get_session)):
    category = get_project_item(session, SettingCategory, project_id, category_id)
    return update_item(session, category, category_in)


@router.delete("/{project_id}/setting-categories/{category_id}")
def delete_setting_category(project_id: str, category_id: int, session: Session = Depends(get_session)):
    category = get_project_item(session, SettingCategory, project_id, category_id)
    return delete_item(session, category)


@router.get("/{project_id}/settings", response_model=List[SettingEntryRead])
def list_settings(project_id: str, session: Session = Depends(get_session)):
    ensure_project(session, project_id)
    statement = select(SettingEntry).where(SettingEntry.project_id == project_id).order_by(SettingEntry.importance.desc(), SettingEntry.id)
    return session.exec(statement).all()


@router.post("/{project_id}/settings", response_model=SettingEntryRead)
def create_setting(project_id: str, setting_in: SettingEntryCreate, session: Session = Depends(get_session)):
    if setting_in.category_id:
        get_project_item(session, SettingCategory, project_id, setting_in.category_id)
    return create_project_item(session, SettingEntry, project_id, setting_in)


@router.put("/{project_id}/settings/{setting_id}", response_model=SettingEntryRead)
def update_setting(project_id: str, setting_id: int, setting_in: SettingEntryUpdate, session: Session = Depends(get_session)):
    setting = get_project_item(session, SettingEntry, project_id, setting_id)
    if setting_in.category_id:
        get_project_item(session, SettingCategory, project_id, setting_in.category_id)
    return update_item(session, setting, setting_in)


@router.delete("/{project_id}/settings/{setting_id}")
def delete_setting(project_id: str, setting_id: int, session: Session = Depends(get_session)):
    setting = get_project_item(session, SettingEntry, project_id, setting_id)
    return delete_item(session, setting)


@router.get("/{project_id}/chapters", response_model=List[ChapterRead])
def list_chapters(project_id: str, session: Session = Depends(get_session)):
    ensure_project(session, project_id)
    statement = select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.sequence, Chapter.id)
    return session.exec(statement).all()


@router.post("/{project_id}/chapters", response_model=ChapterRead)
def create_chapter(project_id: str, chapter_in: ChapterCreate, session: Session = Depends(get_session)):
    validate_chapter_input(session, project_id, chapter_in)
    return create_project_item(session, Chapter, project_id, chapter_in)


@router.get("/{project_id}/chapters/{chapter_id}", response_model=ChapterRead)
def get_chapter(project_id: str, chapter_id: int, session: Session = Depends(get_session)):
    return get_project_item(session, Chapter, project_id, chapter_id)


@router.put("/{project_id}/chapters/{chapter_id}", response_model=ChapterRead)
def update_chapter(project_id: str, chapter_id: int, chapter_in: ChapterUpdate, session: Session = Depends(get_session)):
    chapter = get_project_item(session, Chapter, project_id, chapter_id)
    validate_chapter_input(session, project_id, chapter_in, chapter_id=chapter.id)
    return update_item(session, chapter, chapter_in)


@router.put("/{project_id}/chapters/{chapter_id}/content", response_model=ChapterRead)
def update_chapter_content(project_id: str, chapter_id: int, content_in: ChapterContentUpdate, session: Session = Depends(get_session)):
    chapter = get_project_item(session, Chapter, project_id, chapter_id)
    chapter.content = content_in.content
    if content_in.title is not None:
        chapter.title = content_in.title
    chapter.preview_text = content_in.preview_text if content_in.preview_text is not None else content_in.content[:500]
    chapter.word_count = len(content_in.content.split()) if content_in.content else 0
    session.add(chapter)
    session.commit()
    session.refresh(chapter)

    version = ChapterVersion(
        project_id=project_id,
        chapter_id=chapter.id,
        title=chapter.title,
        content=chapter.content or "",
        preview_text=chapter.preview_text,
        word_count=chapter.word_count,
        change_note=content_in.change_note,
        version_no=next_chapter_version_no(session, project_id, chapter.id),
    )
    session.add(version)
    session.commit()
    session.refresh(chapter)
    return chapter


@router.get("/{project_id}/chapters/{chapter_id}/preview")
def get_chapter_preview(project_id: str, chapter_id: int, session: Session = Depends(get_session)):
    chapter = get_project_item(session, Chapter, project_id, chapter_id)
    return {
        "chapter_id": chapter.id,
        "title": chapter.title,
        "preview_text": chapter.preview_text,
        "content": chapter.content,
    }


@router.get("/{project_id}/chapters/{chapter_id}/versions", response_model=List[ChapterVersionRead])
def list_chapter_versions(project_id: str, chapter_id: int, session: Session = Depends(get_session)):
    get_project_item(session, Chapter, project_id, chapter_id)
    statement = (
        select(ChapterVersion)
        .where(ChapterVersion.project_id == project_id, ChapterVersion.chapter_id == chapter_id)
        .order_by(ChapterVersion.version_no.desc(), ChapterVersion.id.desc())
    )
    return session.exec(statement).all()


@router.post("/{project_id}/chapters/{chapter_id}/versions", response_model=ChapterVersionRead)
def create_chapter_version(project_id: str, chapter_id: int, version_in: ChapterVersionCreate, session: Session = Depends(get_session)):
    chapter = get_project_item(session, Chapter, project_id, chapter_id)
    content = version_in.content if version_in.content is not None else (chapter.content or "")
    preview_text = version_in.preview_text if version_in.preview_text is not None else (chapter.preview_text if version_in.content is None else content[:500])
    word_count = version_in.word_count if version_in.word_count is not None else (chapter.word_count if version_in.content is None else len(content.split()))
    version = ChapterVersion(
        project_id=project_id,
        chapter_id=chapter.id,
        title=version_in.title if version_in.title is not None else chapter.title,
        content=content,
        preview_text=preview_text,
        word_count=word_count,
        change_note=version_in.change_note,
        version_no=next_chapter_version_no(session, project_id, chapter.id),
    )
    session.add(version)
    session.commit()
    session.refresh(version)
    return version


@router.post("/{project_id}/chapters/{chapter_id}/versions/{version_id}/rollback", response_model=ChapterRead)
def rollback_chapter_version(project_id: str, chapter_id: int, version_id: int, session: Session = Depends(get_session)):
    chapter = get_project_item(session, Chapter, project_id, chapter_id)
    version = get_project_item(session, ChapterVersion, project_id, version_id)
    if version.chapter_id != chapter.id:
        raise HTTPException(status_code=404, detail="Chapter version not found")

    snapshot = ChapterVersion(
        project_id=project_id,
        chapter_id=chapter.id,
        title=chapter.title,
        content=chapter.content or "",
        preview_text=chapter.preview_text,
        word_count=chapter.word_count,
        change_note=f"回滚到版本 {version.version_no} 前快照",
        version_no=next_chapter_version_no(session, project_id, chapter.id),
    )
    session.add(snapshot)

    chapter.title = version.title
    chapter.content = version.content
    chapter.preview_text = version.preview_text
    chapter.word_count = version.word_count
    session.add(chapter)
    session.commit()
    session.refresh(chapter)
    return chapter


@router.delete("/{project_id}/chapters/{chapter_id}")
def delete_chapter(project_id: str, chapter_id: int, session: Session = Depends(get_session)):
    chapter = get_project_item(session, Chapter, project_id, chapter_id)
    return delete_item(session, chapter)


@router.get("/{project_id}/outlines", response_model=List[OutlineRead])
def list_outlines(project_id: str, session: Session = Depends(get_session)):
    ensure_project(session, project_id)
    statement = select(Outline).where(Outline.project_id == project_id).order_by(Outline.sort_order, Outline.id)
    return session.exec(statement).all()


@router.post("/{project_id}/outlines", response_model=OutlineRead)
def create_outline(project_id: str, outline_in: OutlineCreate, session: Session = Depends(get_session)):
    if outline_in.chapter_id:
        get_project_item(session, Chapter, project_id, outline_in.chapter_id)
    return create_project_item(session, Outline, project_id, outline_in)


@router.put("/{project_id}/outlines/{outline_id}", response_model=OutlineRead)
def update_outline(project_id: str, outline_id: int, outline_in: OutlineUpdate, session: Session = Depends(get_session)):
    outline = get_project_item(session, Outline, project_id, outline_id)
    if outline_in.chapter_id:
        get_project_item(session, Chapter, project_id, outline_in.chapter_id)
    return update_item(session, outline, outline_in)


@router.delete("/{project_id}/outlines/{outline_id}")
def delete_outline(project_id: str, outline_id: int, session: Session = Depends(get_session)):
    outline = get_project_item(session, Outline, project_id, outline_id)
    return delete_item(session, outline)


@router.get("/{project_id}/memories", response_model=List[MemoryEntryRead])
def list_memories(
    project_id: str,
    memory_type: Optional[str] = None,
    chapter_id: Optional[int] = None,
    character_id: Optional[int] = None,
    session: Session = Depends(get_session),
):
    ensure_project(session, project_id)
    validate_optional_project_refs(session, project_id, chapter_id=chapter_id, character_id=character_id)
    statement = select(MemoryEntry).where(MemoryEntry.project_id == project_id)
    if memory_type is not None:
        statement = statement.where(MemoryEntry.memory_type == memory_type)
    if chapter_id is not None:
        statement = statement.where(MemoryEntry.chapter_id == chapter_id)
    if character_id is not None:
        statement = statement.where(MemoryEntry.character_id == character_id)
    statement = statement.order_by(MemoryEntry.importance.desc(), MemoryEntry.id)
    return session.exec(statement).all()


@router.post("/{project_id}/memories", response_model=MemoryEntryRead)
def create_memory(project_id: str, memory_in: MemoryEntryCreate, session: Session = Depends(get_session)):
    validate_memory_input(session, project_id, memory_in)
    return create_project_item(session, MemoryEntry, project_id, memory_in)


@router.put("/{project_id}/memories/{memory_id}", response_model=MemoryEntryRead)
def update_memory(project_id: str, memory_id: int, memory_in: MemoryEntryUpdate, session: Session = Depends(get_session)):
    memory = get_project_item(session, MemoryEntry, project_id, memory_id)
    validate_memory_input(session, project_id, memory_in)
    return update_item(session, memory, memory_in)


@router.delete("/{project_id}/memories/{memory_id}")
def delete_memory(project_id: str, memory_id: int, session: Session = Depends(get_session)):
    memory = get_project_item(session, MemoryEntry, project_id, memory_id)
    return delete_item(session, memory)


@router.get("/{project_id}/relationships", response_model=List[CharacterRelationshipRead])
def list_relationships(project_id: str, session: Session = Depends(get_session)):
    ensure_project(session, project_id)
    statement = (
        select(CharacterRelationship)
        .where(CharacterRelationship.project_id == project_id)
        .order_by(CharacterRelationship.id)
    )
    return session.exec(statement).all()


@router.post("/{project_id}/relationships", response_model=CharacterRelationshipRead)
def create_relationship(project_id: str, relationship_in: CharacterRelationshipCreate, session: Session = Depends(get_session)):
    validate_relationship_input(session, project_id, relationship_in)
    return create_project_item(session, CharacterRelationship, project_id, relationship_in)


@router.put("/{project_id}/relationships/{relationship_id}", response_model=CharacterRelationshipRead)
def update_relationship(project_id: str, relationship_id: int, relationship_in: CharacterRelationshipUpdate, session: Session = Depends(get_session)):
    relationship = get_project_item(session, CharacterRelationship, project_id, relationship_id)
    validate_relationship_input(session, project_id, relationship_in, existing=relationship)
    return update_item(session, relationship, relationship_in)


@router.delete("/{project_id}/relationships/{relationship_id}")
def delete_relationship(project_id: str, relationship_id: int, session: Session = Depends(get_session)):
    relationship = get_project_item(session, CharacterRelationship, project_id, relationship_id)
    return delete_item(session, relationship)


@router.get("/{project_id}/character-states", response_model=List[CharacterStateRead])
def list_character_states(
    project_id: str,
    chapter_id: Optional[int] = None,
    character_id: Optional[int] = None,
    session: Session = Depends(get_session),
):
    ensure_project(session, project_id)
    validate_optional_project_refs(session, project_id, chapter_id=chapter_id, character_id=character_id)
    statement = select(CharacterState).where(CharacterState.project_id == project_id)
    if chapter_id is not None:
        statement = statement.where(CharacterState.chapter_id == chapter_id)
    if character_id is not None:
        statement = statement.where(CharacterState.character_id == character_id)
    statement = statement.order_by(CharacterState.id)
    return session.exec(statement).all()


@router.post("/{project_id}/character-states", response_model=CharacterStateRead)
def create_character_state(project_id: str, state_in: CharacterStateCreate, session: Session = Depends(get_session)):
    validate_character_state_input(session, project_id, state_in)
    return create_project_item(session, CharacterState, project_id, state_in)


@router.put("/{project_id}/character-states/{state_id}", response_model=CharacterStateRead)
def update_character_state(project_id: str, state_id: int, state_in: CharacterStateUpdate, session: Session = Depends(get_session)):
    state = get_project_item(session, CharacterState, project_id, state_id)
    validate_character_state_input(session, project_id, state_in, existing=state)
    return update_item(session, state, state_in)


@router.delete("/{project_id}/character-states/{state_id}")
def delete_character_state(project_id: str, state_id: int, session: Session = Depends(get_session)):
    state = get_project_item(session, CharacterState, project_id, state_id)
    return delete_item(session, state)


@router.get("/{project_id}/progress", response_model=ProjectProgressRead)
def get_project_progress(project_id: str, session: Session = Depends(get_session)):
    ensure_project(session, project_id)
    statement = select(ProjectProgress).where(ProjectProgress.project_id == project_id)
    progress = session.exec(statement).first()
    if progress is None:
        progress = ProjectProgress(project_id=project_id)
        session.add(progress)
        session.commit()
        session.refresh(progress)
    return progress


@router.put("/{project_id}/progress", response_model=ProjectProgressRead)
def update_project_progress(project_id: str, progress_in: ProjectProgressUpdate, session: Session = Depends(get_session)):
    ensure_project(session, project_id)
    validate_progress_input(session, project_id, progress_in)
    statement = select(ProjectProgress).where(ProjectProgress.project_id == project_id)
    progress = session.exec(statement).first()
    if progress is None:
        progress = ProjectProgress(project_id=project_id)
        session.add(progress)
        session.commit()
        session.refresh(progress)
    return update_item(session, progress, progress_in)


@router.get("/{project_id}/chapter-tasks", response_model=List[ChapterTaskRead])
def list_chapter_tasks(project_id: str, session: Session = Depends(get_session)):
    ensure_project(session, project_id)
    statement = select(ChapterTask).where(ChapterTask.project_id == project_id).order_by(ChapterTask.sort_order, ChapterTask.id)
    return session.exec(statement).all()


@router.post("/{project_id}/chapter-tasks", response_model=ChapterTaskRead)
def create_chapter_task(project_id: str, task_in: ChapterTaskCreate, session: Session = Depends(get_session)):
    validate_chapter_task_input(task_in)
    if task_in.chapter_id:
        get_project_item(session, Chapter, project_id, task_in.chapter_id)
    return create_project_item(session, ChapterTask, project_id, task_in)


@router.put("/{project_id}/chapter-tasks/{task_id}", response_model=ChapterTaskRead)
def update_chapter_task(project_id: str, task_id: int, task_in: ChapterTaskUpdate, session: Session = Depends(get_session)):
    validate_chapter_task_input(task_in)
    task = get_project_item(session, ChapterTask, project_id, task_id)
    if task_in.chapter_id:
        get_project_item(session, Chapter, project_id, task_in.chapter_id)
    return update_item(session, task, task_in)


@router.delete("/{project_id}/chapter-tasks/{task_id}")
def delete_chapter_task(project_id: str, task_id: int, session: Session = Depends(get_session)):
    task = get_project_item(session, ChapterTask, project_id, task_id)
    return delete_item(session, task)


@router.get("/{project_id}/characters/{character_id}/outfits", response_model=List[CharacterOutfitRead])
def list_character_outfits(project_id: str, character_id: int, session: Session = Depends(get_session)):
    character = get_project_item(session, Character, project_id, character_id)
    statement = select(CharacterOutfit).where(CharacterOutfit.character_id == character.id).order_by(CharacterOutfit.is_default.desc(), CharacterOutfit.id)
    return session.exec(statement).all()


@router.post("/{project_id}/characters/{character_id}/outfits", response_model=CharacterOutfitRead)
def create_character_outfit(project_id: str, character_id: int, outfit_in: CharacterOutfitCreate, session: Session = Depends(get_session)):
    character = get_project_item(session, Character, project_id, character_id)
    if outfit_in.is_default:
        clear_default_outfits(session, character.id)
    outfit = CharacterOutfit(project_id=project_id, character_id=character.id, **outfit_in.model_dump())
    session.add(outfit)
    session.commit()
    session.refresh(outfit)
    if outfit.is_default:
        character.default_outfit_id = outfit.id
        session.add(character)
        session.commit()
        session.refresh(outfit)
    return outfit


@router.put("/{project_id}/characters/{character_id}/outfits/{outfit_id}", response_model=CharacterOutfitRead)
def update_character_outfit(project_id: str, character_id: int, outfit_id: int, outfit_in: CharacterOutfitUpdate, session: Session = Depends(get_session)):
    character = get_project_item(session, Character, project_id, character_id)
    outfit = get_project_item(session, CharacterOutfit, project_id, outfit_id)
    if outfit.character_id != character.id:
        raise HTTPException(status_code=404, detail="Item not found")
    if outfit_in.is_default:
        clear_default_outfits(session, character.id)
        character.default_outfit_id = outfit.id
        session.add(character)
    updated = update_item(session, outfit, outfit_in)
    if outfit_in.is_default is False and character.default_outfit_id == outfit.id:
        character.default_outfit_id = None
        session.add(character)
        session.commit()
    return updated


@router.delete("/{project_id}/characters/{character_id}/outfits/{outfit_id}")
def delete_character_outfit(project_id: str, character_id: int, outfit_id: int, session: Session = Depends(get_session)):
    character = get_project_item(session, Character, project_id, character_id)
    outfit = get_project_item(session, CharacterOutfit, project_id, outfit_id)
    if outfit.character_id != character.id:
        raise HTTPException(status_code=404, detail="Item not found")
    if character.default_outfit_id == outfit.id:
        character.default_outfit_id = None
        session.add(character)
    return delete_item(session, outfit)



def clear_default_outfits(session: Session, character_id: int):
    statement = select(CharacterOutfit).where(CharacterOutfit.character_id == character_id, CharacterOutfit.is_default == True)
    for outfit in session.exec(statement).all():
        outfit.is_default = False
        session.add(outfit)
