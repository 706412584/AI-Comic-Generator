from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, or_, select

from app.core.database import get_session
from app.models.models import Chapter, Project, SourceChapter, SourceImport
from app.schemas.schemas import (
    SourceChapterRead,
    SourceChapterUpdate,
    SourceImportCreate,
    SourceImportRead,
    SourceImportWithChapters,
    SourceResplitPreview,
    SourceResplitRequest,
)
from app.services.source_import_service import count_text_chars, split_novel_chapters

router = APIRouter()


def ensure_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def get_source_import(session: Session, project_id: str, source_import_id: int) -> SourceImport:
    source_import = session.get(SourceImport, source_import_id)
    if not source_import or source_import.project_id != project_id:
        raise HTTPException(status_code=404, detail="Source import not found")
    return source_import


def get_source_chapter(session: Session, project_id: str, source_chapter_id: int) -> SourceChapter:
    chapter = session.get(SourceChapter, source_chapter_id)
    if not chapter or chapter.project_id != project_id:
        raise HTTPException(status_code=404, detail="Source chapter not found")
    return chapter


def serialize_source_import_with_stats(session: Session, source_import: SourceImport) -> dict:
    chapters = session.exec(
        select(SourceChapter).where(SourceChapter.source_import_id == source_import.id)
    ).all()
    analyzed_count = sum(1 for chapter in chapters if chapter.analysis_status == "analyzed" or (chapter.summary_short or "").strip())
    data = source_import.model_dump()
    data["analyzed_chapter_count"] = analyzed_count
    data["unanalyzed_chapter_count"] = max(len(chapters) - analyzed_count, 0)
    return data


def replace_source_chapters(session: Session, source_import: SourceImport, split_pattern: str | None = None):
    existing = session.exec(
        select(SourceChapter).where(SourceChapter.source_import_id == source_import.id)
    ).all()
    sequence_by_old_id = {chapter.id: chapter.sequence for chapter in existing}
    bound_chapters = session.exec(
        select(Chapter).where(Chapter.source_chapter_id.in_(sequence_by_old_id.keys()))
    ).all() if sequence_by_old_id else []

    for chapter in existing:
        session.delete(chapter)
    session.flush()

    chapters = split_novel_chapters(source_import.raw_text, split_pattern)
    new_source_by_sequence = {}
    for chapter_data in chapters:
        source_chapter = SourceChapter(
            project_id=source_import.project_id,
            source_import_id=source_import.id,
            **chapter_data,
        )
        session.add(source_chapter)
        session.flush()
        new_source_by_sequence[source_chapter.sequence] = source_chapter

    for chapter in bound_chapters:
        old_sequence = sequence_by_old_id.get(chapter.source_chapter_id)
        new_source = new_source_by_sequence.get(old_sequence)
        chapter.source_chapter_id = new_source.id if new_source else None
        session.add(chapter)

    source_import.chapter_count = len(chapters)
    source_import.text_length = count_text_chars(source_import.raw_text)
    source_import.split_strategy = split_pattern or "auto"
    source_import.updated_at = datetime.utcnow()
    session.add(source_import)
    session.commit()
    session.refresh(source_import)
    return source_import


@router.post("/projects/{project_id}/source-imports", response_model=SourceImportRead)
def create_source_import(project_id: str, source_in: SourceImportCreate, session: Session = Depends(get_session)):
    ensure_project(session, project_id)
    raw_text = source_in.raw_text or ""
    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="Source text is required")

    source_import = SourceImport(
        project_id=project_id,
        file_name=source_in.file_name.strip() or "未命名.txt",
        raw_text=raw_text,
        text_length=count_text_chars(raw_text),
        import_status="imported",
        split_strategy=source_in.split_pattern or "auto",
    )
    session.add(source_import)
    session.commit()
    session.refresh(source_import)
    source_import = replace_source_chapters(session, source_import, source_in.split_pattern)
    return serialize_source_import_with_stats(session, source_import)


@router.get("/projects/{project_id}/source-imports", response_model=list[SourceImportRead])
def list_source_imports(project_id: str, session: Session = Depends(get_session)):
    ensure_project(session, project_id)
    statement = (
        select(SourceImport)
        .where(SourceImport.project_id == project_id)
        .order_by(SourceImport.created_at.desc())
    )
    return [serialize_source_import_with_stats(session, source_import) for source_import in session.exec(statement).all()]


@router.get("/projects/{project_id}/source-imports/{source_import_id}", response_model=SourceImportWithChapters)
def read_source_import(project_id: str, source_import_id: int, session: Session = Depends(get_session)):
    source_import = get_source_import(session, project_id, source_import_id)
    chapters = session.exec(
        select(SourceChapter)
        .where(SourceChapter.source_import_id == source_import_id)
        .order_by(SourceChapter.sequence)
    ).all()
    data = serialize_source_import_with_stats(session, source_import)
    data["chapters"] = chapters
    return data


@router.get("/projects/{project_id}/source-chapters", response_model=list[SourceChapterRead])
def list_source_chapters(
    project_id: str,
    source_import_id: int | None = None,
    offset: int = 0,
    limit: int = 50,
    q: str | None = None,
    only_unanalyzed: bool = False,
    session: Session = Depends(get_session),
):
    ensure_project(session, project_id)
    statement = select(SourceChapter).where(SourceChapter.project_id == project_id)
    if source_import_id is not None:
        statement = statement.where(SourceChapter.source_import_id == source_import_id)
    if q:
        keyword = f"%{q}%"
        statement = statement.where(or_(SourceChapter.title.like(keyword), SourceChapter.raw_text.like(keyword), SourceChapter.summary_short.like(keyword)))
    if only_unanalyzed:
        statement = statement.where(or_(SourceChapter.analysis_status != "analyzed", SourceChapter.summary_short.is_(None), SourceChapter.summary_short == ""))
    statement = statement.order_by(SourceChapter.sequence).offset(offset).limit(min(limit, 500))
    return session.exec(statement).all()


@router.get("/projects/{project_id}/source-chapters/{source_chapter_id}", response_model=SourceChapterRead)
def read_source_chapter(project_id: str, source_chapter_id: int, session: Session = Depends(get_session)):
    return get_source_chapter(session, project_id, source_chapter_id)


@router.put("/projects/{project_id}/source-chapters/{source_chapter_id}", response_model=SourceChapterRead)
def update_source_chapter(
    project_id: str,
    source_chapter_id: int,
    chapter_in: SourceChapterUpdate,
    session: Session = Depends(get_session),
):
    chapter = get_source_chapter(session, project_id, source_chapter_id)
    data = chapter_in.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(chapter, key, value)
    if "raw_text" in data:
        chapter.raw_word_count = count_text_chars(chapter.raw_text)
    chapter.updated_at = datetime.utcnow()
    session.add(chapter)
    session.commit()
    session.refresh(chapter)
    return chapter


@router.post("/projects/{project_id}/source-imports/{source_import_id}/resplit-preview", response_model=SourceResplitPreview)
def preview_resplit_source_import(
    project_id: str,
    source_import_id: int,
    request: SourceResplitRequest,
    session: Session = Depends(get_session),
):
    source_import = get_source_import(session, project_id, source_import_id)
    try:
        chapters = split_novel_chapters(source_import.raw_text, request.split_pattern)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"切章规则无效：{exc}") from exc
    preview = [
        {
            "sequence": chapter["sequence"],
            "title": chapter["title"],
            "raw_word_count": chapter["raw_word_count"],
        }
        for chapter in chapters[:200]
    ]
    return {"chapter_count": len(chapters), "chapters": preview}


@router.post("/projects/{project_id}/source-imports/{source_import_id}/resplit", response_model=SourceImportRead)
def resplit_source_import(
    project_id: str,
    source_import_id: int,
    request: SourceResplitRequest | None = None,
    session: Session = Depends(get_session),
):
    source_import = get_source_import(session, project_id, source_import_id)
    split_pattern = request.split_pattern if request else None
    try:
        source_import = replace_source_chapters(session, source_import, split_pattern)
        return serialize_source_import_with_stats(session, source_import)
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=f"切章失败：{exc}") from exc
