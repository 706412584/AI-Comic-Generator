from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.core.database import get_session, init_db
from app.models.models import Chapter, ChapterVersion
from app.services.ai_service import AIService
from app.services.context_assembly_service import ContextAssemblyService
from app.services.chapter_state_extraction_service import extract_chapter_state_safely

AI_BRIDGE_NAME = "ai-comic-ai-bridge"
AI_BRIDGE_HOST = "127.0.0.1"
AI_BRIDGE_PORT = 48721

app = FastAPI(title=AI_BRIDGE_NAME)


class TextGenerateRequest(BaseModel):
    system_prompt: str
    user_input: str


class ChapterContentRequest(BaseModel):
    chapter_id: int
    user_input: Optional[str] = None
    save_version: bool = True


class ChapterContextRequest(BaseModel):
    project_id: str
    chapter_id: int


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/health")
def health():
    return {"name": AI_BRIDGE_NAME, "status": "online", "host": AI_BRIDGE_HOST, "port": AI_BRIDGE_PORT}


@app.post("/text/generate")
def generate_text(request: TextGenerateRequest, session: Session = Depends(get_session)):
    try:
        text = AIService(session).generate_text(request.system_prompt, request.user_input)
        return {"text": text}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/chapter/context")
def chapter_context(request: ChapterContextRequest, session: Session = Depends(get_session)):
    try:
        service = ContextAssemblyService(session)
        context = service.build_chapter_context(request.project_id, request.chapter_id)
        return {"prompt": service.render_context_prompt(context)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/chapter/generate")
def generate_chapter(request: ChapterContentRequest, session: Session = Depends(get_session)):
    chapter = session.get(Chapter, request.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    try:
        context_service = ContextAssemblyService(session)
        context = context_service.build_chapter_context(chapter.project_id, chapter.id)
        context_prompt = context_service.render_context_prompt(context)
        content = AIService(session).generate_chapter_content(context_prompt, request.user_input or "")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    chapter.content = content
    chapter.preview_text = content[:500]
    chapter.word_count = len(content.split()) if content else 0
    session.add(chapter)
    session.commit()
    session.refresh(chapter)

    version_id = None
    if request.save_version:
        latest_versions = sorted(chapter.versions, key=lambda item: item.version_no, reverse=True)
        version_no = 1 if not latest_versions else latest_versions[0].version_no + 1
        version = ChapterVersion(
            project_id=chapter.project_id,
            chapter_id=chapter.id,
            title=chapter.title,
            content=content,
            preview_text=chapter.preview_text,
            word_count=chapter.word_count,
            change_note="AI Bridge 生成",
            version_no=version_no,
        )
        session.add(version)
        session.commit()
        session.refresh(version)
        version_id = version.id

    extraction = extract_chapter_state_safely(session, chapter, content, context_prompt)

    return {"chapter_id": chapter.id, "project_id": chapter.project_id, "content": chapter.content, "version_id": version_id, "state_extraction": extraction}
