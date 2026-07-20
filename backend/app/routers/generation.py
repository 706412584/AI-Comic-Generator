from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import text
from sqlmodel import Session, select
from app.core.database import get_session
from app.models.models import (
    Project,
    Character,
    StoryboardItem,
    Task,
    ImageHistory,
    Chapter,
    ChapterVersion,
    SettingCategory,
    SettingEntry,
    CharacterOutfit,
    CharacterRelationship,
    Outline,
    ChapterTask,
    MemoryEntry,
    ProjectProgress,
    SourceImport,
    SourceChapter,
    AgentRun,
)
from app.services.ai_service import AIService
from app.services.consistency_service import ConsistencyService
from app.services.context_assembly_service import ContextAssemblyService
from app.services.chapter_state_extraction_service import extract_chapter_state_safely
from app.services.chapter_continuity_review_service import ChapterContinuityReviewService
from app.utils.json_utils import extract_json_blocks
from app.cruds import crud_project
from app.schemas.schemas import ChapterRead
import os
import uuid
import json
import traceback

import logging
import sys
import time

# Configure logging
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

def log_task_event(session, task_id, message):
    logger.info(message)
    try:
        task = session.get(Task, task_id)
        if task:
            if task.logs is None:
                task.logs = []
            import datetime
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            # Create new list to ensure SQLModel detects change
            current_logs = list(task.logs) if task.logs else []
            current_logs.append(f"[{timestamp}] {message}")
            task.logs = current_logs
            session.add(task)
            session.commit()
    except Exception as e:
        logger.error(f"Failed to log task event: {e}")

def save_generated_image(session, project_id, entity_type, entity_id, image_bytes):
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    project_static_dir = os.path.join(base_dir, "static", project_id)

    sub_dir = "characters" if entity_type == "character" else "panels"
    target_dir = os.path.join(project_static_dir, sub_dir)

    if not os.path.exists(target_dir):
        os.makedirs(target_dir)

    filename = f"{entity_type}_{entity_id}_{uuid.uuid4().hex[:8]}.png"
    filepath = os.path.join(target_dir, filename)

    with open(filepath, "wb") as f:
        f.write(image_bytes)

    relative_url = f"/static/{project_id}/{sub_dir}/{filename}"
    
    # Save History
    history = ImageHistory(
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        image_url=relative_url
    )
    session.add(history)
    
    return relative_url

router = APIRouter()

from app.core.prompts import COMIC_GENERATION_SYSTEM_PROMPT

def get_system_prompt():
    return COMIC_GENERATION_SYSTEM_PROMPT


def extract_character_names(raw_characters):
    if isinstance(raw_characters, str):
        return [raw_characters]
    if not isinstance(raw_characters, list):
        return []

    names = []
    for character in raw_characters:
        if isinstance(character, dict):
            name = character.get("name")
            if name:
                names.append(name)
        elif isinstance(character, str):
            names.append(character)
    return names


def format_outfit_prompt_line(character, outfit):
    parts = [f"{character.name} 服饰：{outfit.name}"]
    for label, value in [
        ("描述", outfit.description),
        ("适用场景", outfit.scene),
        ("颜色", outfit.colors),
        ("材质", outfit.materials),
        ("配饰", outfit.accessories),
        ("状态", outfit.state),
    ]:
        if value:
            parts.append(f"{label}：{value}")
    return "；".join(parts)


def resolve_character_outfit(character, selected_value):
    outfits = character.outfits or []
    if selected_value:
        selected_text = str(selected_value)
        for outfit in outfits:
            if str(outfit.id) == selected_text or outfit.name == selected_text:
                return outfit

    if character.default_outfit_id:
        for outfit in outfits:
            if outfit.id == character.default_outfit_id:
                return outfit

    for outfit in outfits:
        if outfit.is_default:
            return outfit
    return None


def build_panel_outfit_prompt(project, item, char_names):
    selected_outfits = item.selected_outfits or item.data.get("selected_outfits") or {}
    if not isinstance(selected_outfits, dict):
        selected_outfits = {}

    lines = []
    for name in char_names:
        for character in project.characters:
            if character.name in name or name in character.name:
                selected_value = selected_outfits.get(character.name) or selected_outfits.get(name)
                outfit = resolve_character_outfit(character, selected_value)
                if outfit:
                    lines.append(format_outfit_prompt_line(character, outfit))
                break

    if not lines:
        return ""
    return "\n\nCharacter Outfit Requirements:\n" + "\n".join(f"- {line}" for line in lines)


def next_chapter_version_no(session: Session, project_id: str, chapter_id: int) -> int:
    statement = (
        select(ChapterVersion)
        .where(ChapterVersion.project_id == project_id, ChapterVersion.chapter_id == chapter_id)
        .order_by(ChapterVersion.version_no.desc(), ChapterVersion.id.desc())
    )
    latest = session.exec(statement).first()
    return 1 if latest is None else latest.version_no + 1


# --- Background Task Functions ---

def generate_storyboard_task(task_id: str, project_id: str, user_input: str):
    logger.info(f"Starting storyboard generation task: {task_id} for project: {project_id}")
    # We need a fresh session for the background task
    from app.core.database import engine
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task: 
            logger.error(f"Task {task_id} not found")
            return
        
        task.status = "processing"
        session.add(task)
        session.commit()
        
        try:
            project = crud_project.get_project(session, project_id)
            log_task_event(session, task_id, f"Project found: {project.title}")
            
            # Save User Input (Persist it)
            project.story_input = user_input
            session.add(project)
            session.commit()
            
            ai = AIService(session)
            system_prompt = get_system_prompt()
            
            # Construct Final Prompt with Preferences
            final_prompt = user_input
            
            # --- Replace Placeholders in System Prompt ---
            system_prompt = get_system_prompt()
            
            # Defaults
            style = "Standard"
            if project.theme: style = project.theme
            
            lang = "English"
            if project.language:
                lang_map = {"zh-CN": "Simplified Chinese", "en-US": "English", "ja-JP": "Japanese"}
                lang = lang_map.get(project.language, project.language)
                
            # Inject into System Prompt
            system_prompt = system_prompt.replace("{User Specified Style}", style)
            # We could also inject language if we had a placeholder, but style is the main one failing.
            # Let's add language instruction to system prompt dynamically if needed, 
            # or rely on the "Language & Format" section in prompt which says "Use user input language".
            
            # --- Construct User Prompt ---
            final_prompt = user_input
            
            # Append preferences as normal requirements
            prefs = []
            if project.theme: prefs.append(f"Theme: {project.theme}")
            if project.language: prefs.append(f"Language: {project.language}")
            if project.panel_count: prefs.append(f"Estimated Panel Count: {project.panel_count}")
            if project.aspect_ratio: prefs.append(f"Aspect Ratio: {project.aspect_ratio}")
            
            if prefs:
                final_prompt += "\n\nRequirements:\n" + "\n".join(prefs)

            log_task_event(session, task_id, "Calling AI service for storyboard generation... This may take a while.")
            generated_text = ai.generate_storyboard(system_prompt, final_prompt)
            
            # --- Save Generated Text to Temp File ---
            import time
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            temp_dir = os.path.join(base_dir, "static", project_id, "temp")
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir)
            
            timestamp = int(time.time())
            temp_file = os.path.join(temp_dir, f"ai_output_{timestamp}.txt")
            try:
                with open(temp_file, "w", encoding="utf-8") as f:
                    f.write(generated_text)
                log_task_event(session, task_id, f"Saved raw AI output to {temp_file}")
            except Exception as e:
                logger.error(f"Failed to save temp AI output: {e}")
            # ----------------------------------------

            log_task_event(session, task_id, "AI generation complete. Extracting JSON blocks...")
            json_blocks = extract_json_blocks(generated_text)
            
            char_blocks = [b for b in json_blocks if b.get("type") == "character_sheet"]
            story_blocks = [b for b in json_blocks if b.get("type") == "storyboard"] 
            
            if not story_blocks:
                 story_blocks = [b for b in json_blocks if b.get("type") not in ["character_sheet", "comic_config"]]

            # --- Missing Character Check & Fix ---
            session.refresh(task)
            if task.status == "cancelled":
                log_task_event(session, task_id, "Task execution cancelled by user.")
                return

            story_char_names = set()
            for block in story_blocks:
                chars = block.get("characters", [])
                if isinstance(chars, str):
                    story_char_names.add(chars)
                elif isinstance(chars, list):
                    for c in chars:
                        if isinstance(c, str): story_char_names.add(c)
                        elif isinstance(c, dict): story_char_names.add(c.get("name", ""))

            generated_char_names = set(b.get("name") for b in char_blocks if b.get("name"))
            
            # Simple fuzzy matching or direct check
            missing_chars = []
            for name in story_char_names:
                # Check if name is contained in any generated char name (e.g. "Xiao Ming" vs "Ming")
                found = False
                for g_name in generated_char_names:
                    if name in g_name or g_name in name:
                        found = True
                        break
                if not found and name and len(name) > 1: # Ignore single chars or empty
                    missing_chars.append(name)
            
            if missing_chars:
                log_task_event(session, task_id, f"Detected missing characters: {missing_chars}. Requesting AI to generate them...")
                fix_prompt = f"You missed generating character sheets for the following characters that appeared in the storyboard: {', '.join(missing_chars)}. Please generate 'character_sheet' JSON blocks for them now. Do not generate anything else."
                
                try:
                    fix_response = ai.generate_storyboard(system_prompt, fix_prompt) # Re-use generate method
                    fix_blocks = extract_json_blocks(fix_response)
                    new_chars = [b for b in fix_blocks if b.get("type") == "character_sheet"]
                    if new_chars:
                        log_task_event(session, task_id, f"Successfully generated {len(new_chars)} missing characters.")
                        char_blocks.extend(new_chars)
                except Exception as e:
                    logger.error(f"Failed to generate missing characters: {e}")

            config_block = next((b for b in json_blocks if b.get("type") == "comic_config"), None)
            
            # If AI didn't return config, create one from project prefs
            if not config_block and (project.aspect_ratio or project.language):
                config_block = {
                    "type": "comic_config",
                    "style": "Standard", # Default
                    "aspect_ratio": project.aspect_ratio or "16:9",
                    "language": project.language or "en-US"
                }
            
            if config_block:
                crud_project.create_global_config(session, project_id, config_block)
            
            # --- Enforce Consistency: Update meta_info for all blocks ---
            # Re-read global config if we just created/updated it
            # Or use the config_block we have
            
            if not config_block:
                 # Try to fetch existing
                 # But we just generated it. If None, we create a default one above.
                 # Let's use the one we have.
                 pass

            if config_block:
                global_style = config_block.get("style", "")
                global_aspect = config_block.get("aspect_ratio", "16:9")
                global_lang = config_block.get("language", "en-US")
                
                # Update Character Sheets
                for char in char_blocks:
                    char["meta_info"] = char.get("meta_info", {})
                    char["meta_info"]["language"] = global_lang
                    char["meta_info"]["style"] = global_style
                    
                    # Remove top-level redundant keys if they exist to avoid confusion
                    char.pop("language", None)
                    char.pop("style", None)
                    
                # Update Storyboard Items
                for block in story_blocks:
                    meta = block.get("meta_info", {})
                    meta["style"] = global_style
                    meta["language"] = global_lang
                    meta["aspect_ratio"] = global_aspect
                    
                    # Also inject specific style configs if present
                    for key in ["bubble_style", "narration_style", "border_style", "gutter_style", "layout_settings"]:
                        if key in config_block:
                            meta[key] = config_block[key]
                    
                    block["meta_info"] = meta
            
            # Save to DB
            crud_project.save_characters(session, project_id, char_blocks)
            crud_project.save_storyboard(session, project_id, story_blocks)
            
            # Consistency
            consistency = ConsistencyService(session)
            consistency.normalize_project(project_id)
            
            task.status = "completed"
            task.result = {"blocks_found": len(json_blocks)}
            task.progress = 100
            session.add(task)
            session.commit()
            logger.info(f"Storyboard task {task_id} completed successfully.")
            
        except Exception as e:
            logger.error(f"Storyboard task {task_id} failed: {e}")
            traceback.print_exc()
            task.status = "failed"
            task.message = str(e)
            session.add(task)
            session.commit()

def generate_all_images_task(task_id: str, project_id: str):
    logger.info(f"Starting batch image generation task: {task_id} for project: {project_id}")
    from app.core.database import engine
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task: 
            logger.error(f"Task {task_id} not found")
            return
        
        task.status = "processing"
        session.add(task)
        session.commit()
        
        try:
            project = session.get(Project, project_id)
            ai = AIService(session)
            
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            static_root = os.path.join(base_dir, "static")
            if not os.path.exists(static_root): os.makedirs(static_root)

            # 1. Generate Characters
            total_chars = len(project.characters)
            log_task_event(session, task_id, f"Generating {total_chars} characters...")
            for i, char in enumerate(project.characters):
                # Check for cancellation
                session.refresh(task)
                if task.status == "cancelled":
                    log_task_event(session, task_id, "Task execution cancelled by user.")
                    return

                if char.image_url: 
                    log_task_event(session, task_id, f"Character {char.name} already has image, skipping.")
                    continue 
                
                log_task_event(session, task_id, f"Generating image for character: {char.name}")
                json_prompt = json.dumps(char.data, ensure_ascii=False, indent=2)
                json_prompt += "\n\n generate a character design sheet with 4 panels: front view, side view, clothing details, accessories."
                
                try:
                    image_bytes = ai.generate_image(
                        json_prompt, 
                        aspect_ratio=project.aspect_ratio or "16:9",
                        resolution=project.resolution or "2K"
                    )
                    relative_url = save_generated_image(session, project_id, "character", char.id, image_bytes)
                    char.image_url = relative_url
                    session.add(char)
                    session.commit()
                    log_task_event(session, task_id, f"Character {char.name} generated successfully.")
                    
                    # Update task progress
                    progress = int(((i + 1) / total_chars) * 100)
                    task.progress = progress
                    session.add(task)
                    session.commit()
                    
                except Exception as e:
                    logger.error(f"Failed to generate char {char.id}: {e}")
                    log_task_event(session, task_id, f"Failed to generate char {char.id}: {e}")
                
                # Update task progress
                # progress = int(((i + 1) / total_chars) * 100)
                # task.progress = progress
                # session.add(task)
                # session.commit()
                
            # 2. Generate Storyboard Items (Sequential)
            # Re-fetch items to ensure order
            items = sorted(project.storyboard_items, key=lambda x: x.sequence)
            total_items = len(items)
            log_task_event(session, task_id, f"Generating {total_items} storyboard panels...")
            
            generated_history = [] # Keep track of generated images for context
            
            # Populate history with existing images
            # Actually comic_generator logic builds history as it goes.
            # We should probably load existing images into history if we are resuming?
            # For "one click", let's assume we scan all items.
            
            for i, item in enumerate(items):
                # Check for cancellation
                session.refresh(task)
                if task.status == "cancelled":
                    log_task_event(session, task_id, "Task execution cancelled by user.")
                    return

                # Update progress at start of loop
                # task.progress = int((i / total_items) * 100)
                # session.add(task)
                # session.commit()
                
                # if item.image_url:
                #    # Add to history
                #    filename = os.path.basename(item.image_url)
                #    # We need to find where it is stored.
                #    # Assuming standard structure
                #    # We need absolute path for history
                #    # item.image_url is like /static/{project_id}/panels/{filename}
                #    rel_path = item.image_url.lstrip("/")
                #    abs_path = os.path.join(base_dir, rel_path.replace("/", os.sep))
                #    
                #    if os.path.exists(abs_path):
                #        generated_history.append(abs_path)
                #    continue
                
                log_task_event(session, task_id, f"Generating panel {item.sequence}...")
                
                # Prepare Context
                context_images = []
                
                # a) Character Sheets
                char_names = extract_character_names(item.data.get("characters", []))
                
                for name in char_names:
                    for p_char in project.characters:
                        if p_char.image_url and (p_char.name in name or name in p_char.name):
                            # Resolve absolute path for char image
                            rel_path = p_char.image_url.lstrip("/")
                            abs_path = os.path.join(base_dir, rel_path.replace("/", os.sep))
                            if os.path.exists(abs_path) and abs_path not in context_images:
                                context_images.append(abs_path)
                
                # b) Previous History (Last 3 logic) - RE-ENABLED for Batch Generation
                # For batch generation, we build history as we go.
                # This ensures panel N is consistent with panel N-1.
                
                if len(generated_history) >= 3:
                    selected = [generated_history[0]] + generated_history[-2:]
                else:
                    selected = generated_history
                
                for path in selected:
                    if path not in context_images:
                        context_images.append(path)
                
                # Generate
                json_prompt = json.dumps(item.data, ensure_ascii=False, indent=2)
                json_prompt += build_panel_outfit_prompt(project, item, char_names)
                json_prompt += "\n\n use json block as user input prompt to generate 2*2 grid comic image."
                
                try:
                    image_bytes = ai.generate_image(
                        json_prompt, 
                        context_images=context_images,
                        aspect_ratio=project.aspect_ratio or "16:9",
                        resolution=project.resolution or "2K"
                    )
                    relative_url = save_generated_image(session, project_id, "panel", item.id, image_bytes)
                    
                    item.image_url = relative_url
                    session.add(item)
                    session.commit()
                    
                    # Update progress
                    task.progress = int(((i + 1) / total_items) * 100)
                    session.add(task)
                    session.commit()
                    
                    # Add to history (absolute path for context usage)
                    # We need absolute path for next context
                    # save_generated_image returns relative /static/...
                    # Reconstruct absolute path
                    # strip leading /
                    abs_path = os.path.join(base_dir, relative_url.lstrip("/").replace("/", os.sep))
                    generated_history.append(abs_path)
                    log_task_event(session, task_id, f"Panel {item.sequence} generated successfully.")
                    
                except Exception as e:
                    logger.error(f"Failed to generate panel {item.id}: {e}")
                    log_task_event(session, task_id, f"Failed to generate panel {item.id}: {e}")
            
            task.status = "completed"
            task.progress = 100
            session.add(task)
            session.commit()
            log_task_event(session, task_id, f"Batch generation task {task_id} completed successfully.")
            
        except Exception as e:
            logger.error(f"Batch generation task {task_id} failed: {e}")
            traceback.print_exc()
            task.status = "failed"
            task.message = str(e)
            session.add(task)
            session.commit()

def generate_all_characters_task(task_id: str, project_id: str):
    logger.info(f"Starting batch character generation task: {task_id} for project: {project_id}")
    from app.core.database import engine
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task: 
            logger.error(f"Task {task_id} not found")
            return
        
        task.status = "processing"
        session.add(task)
        session.commit()
        
        try:
            project = session.get(Project, project_id)
            ai = AIService(session)
            
            total_chars = len(project.characters)
            log_task_event(session, task_id, f"Generating {total_chars} characters...")
            
            for i, char in enumerate(project.characters):
                # Check for cancellation
                session.refresh(task)
                if task.status == "cancelled":
                    log_task_event(session, task_id, "Task execution cancelled by user.")
                    return

                # if char.image_url: 
                #    logger.info(f"Character {char.name} already has image, skipping.")
                #    continue 
                
                log_task_event(session, task_id, f"Generating image for character: {char.name}")
                
                # Construct Natural Language Prompt from JSON
                data = char.data
                meta = data.get("meta_info", {})
                name = data.get("name", "Unknown")
                role = meta.get("role", "")
                age = meta.get("age", "")
                personality = data.get("personality", "") or meta.get("personality", "")
                style = meta.get("style", "")
                
                # Build Description from panels
                description = ""
                panels = data.get("design_panels", [])
                for p in panels:
                    view = p.get("view", "")
                    desc = p.get("description", "")
                    description += f"- {view}: {desc}\n"
                
                prompt = f"""Character Design Request:
Name: {name}
Role: {role}
Age: {age}
Personality: {personality}
Style: {style}

Visual Description:
{description}

Task: Generate a high-quality character reference sheet (Character Design) based on the above description. 
Include Front View, Side View, and detailed clothing/accessories. 
Ensure the character's expression and pose reflect their personality: {personality}.
"""
                
                try:
                    image_bytes = ai.generate_image(
                        prompt,
                        aspect_ratio=project.aspect_ratio or "16:9",
                        resolution=project.resolution or "2K"
                    )
                    relative_url = save_generated_image(session, project_id, "character", char.id, image_bytes)
                    char.image_url = relative_url
                    session.add(char)
                    session.commit()
                    log_task_event(session, task_id, f"Character {char.name} generated successfully.")
                    
                    # Update progress
                    progress = int(((i + 1) / total_chars) * 100)
                    task.progress = progress
                    session.add(task)
                    session.commit()
                    
                except Exception as e:
                    logger.error(f"Failed to generate char {char.id}: {e}")
                    log_task_event(session, task_id, f"Failed to generate char {char.id}: {e}")
                
                # Update progress
                # progress = int(((i + 1) / total_chars) * 100)
                # task.progress = progress
                # session.add(task)
                # session.commit()

            task.status = "completed"
            task.progress = 100
            session.add(task)
            session.commit()
            log_task_event(session, task_id, f"Batch character generation task {task_id} completed successfully.")
            
        except Exception as e:
            logger.error(f"Batch character generation task {task_id} failed: {e}")
            traceback.print_exc()
            task.status = "failed"
            task.message = str(e)
            session.add(task)
            session.commit()

def generate_character_task(task_id: str, character_id: int):
    logger.info(f"Starting character generation task: {task_id} for char: {character_id}")
    from app.core.database import engine
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task: 
            logger.error(f"Task {task_id} not found")
            return
        
        task.status = "processing"
        session.add(task)
        session.commit()
        
        try:
            char = session.get(Character, character_id)
            if not char:
                raise ValueError("Character not found")
                
            ai = AIService(session)
            
            # Construct Natural Language Prompt from JSON
            data = char.data
            meta = data.get("meta_info", {})
            name = data.get("name", "Unknown")
            role = meta.get("role", "")
            age = meta.get("age", "")
            personality = data.get("personality", "") or meta.get("personality", "")
            style = meta.get("style", "")
            
            # Build Description from panels
            description = ""
            panels = data.get("design_panels", [])
            for p in panels:
                view = p.get("view", "")
                desc = p.get("description", "")
                description += f"- {view}: {desc}\n"
            
            prompt = f"""Character Design Request:
Name: {name}
Role: {role}
Age: {age}
Personality: {personality}
Style: {style}

Visual Description:
{description}

Task: Generate a high-quality character reference sheet (Character Design) based on the above description. 
Include Front View, Side View, and detailed clothing/accessories. 
Ensure the character's expression and pose reflect their personality: {personality}.
"""
            
            log_task_event(session, task_id, f"Calling AI service for character {char.name}...")
            start_time = time.time()
            try:
                image_bytes = ai.generate_image(
                    prompt,
                    aspect_ratio=char.project.aspect_ratio or "16:9",
                    resolution=char.project.resolution or "2K"
                )
                elapsed = time.time() - start_time
                log_task_event(session, task_id, f"AI generation finished in {elapsed:.2f}s. Image size: {len(image_bytes)} bytes.")
            except Exception as e:
                elapsed = time.time() - start_time
                log_task_event(session, task_id, f"AI generation failed after {elapsed:.2f}s: {str(e)}")
                raise e
            
            relative_url = save_generated_image(session, char.project_id, "character", char.id, image_bytes)
            
            char.image_url = relative_url
            session.add(char)
            
            task.status = "completed"
            task.progress = 100
            session.add(task)
            session.commit()
            log_task_event(session, task_id, f"Character task {task_id} completed successfully.")
            
        except Exception as e:
            logger.error(f"Character task {task_id} failed: {e}")
            log_task_event(session, task_id, f"Character task {task_id} failed: {e}")
            traceback.print_exc()
            task.status = "failed"
            task.message = str(e)
            session.add(task)
            session.commit()

def set_task_progress(session: Session, task_id: str, progress: int, message: str):
    from app.core.database import engine

    with Session(engine) as progress_session:
        task = progress_session.get(Task, task_id)
        if task:
            task.progress = progress
            task.message = message
            task.updated_at = datetime.utcnow()
            current_logs = list(task.logs) if task.logs else []
            current_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
            task.logs = current_logs
            progress_session.add(task)
            progress_session.commit()
    logger.info(message)


def finish_task(task_id: str, status: str, message: str, result: dict | None = None):
    from app.core.database import engine

    with Session(engine) as task_session:
        task = task_session.get(Task, task_id)
        if task:
            # 已被用户取消的任务不允许被后续的 completed/failed 覆盖
            if task.status == "cancelled" and status != "cancelled":
                logs = list(task.logs) if task.logs else []
                logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 任务已取消，忽略结果：{message}")
                task.logs = logs
                task.updated_at = datetime.utcnow()
                task_session.add(task)
                task_session.commit()
                return
            task.status = status
            task.progress = 100 if status == "completed" else task.progress
            task.message = message
            task.updated_at = datetime.utcnow()
            if result is not None:
                task.result = result
            current_logs = list(task.logs) if task.logs else []
            current_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
            task.logs = current_logs
            task_session.add(task)
            task_session.commit()
    logger.info(message)


def normalize_list(value):
    return value if isinstance(value, list) else []


def normalize_dict(value):
    return value if isinstance(value, dict) else {}


def safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def has_initialized_content(session: Session, project_id: str) -> bool:
    checks = [
        select(SettingEntry).where(SettingEntry.project_id == project_id),
        select(Character).where(Character.project_id == project_id),
        select(Chapter).where(Chapter.project_id == project_id),
        select(Outline).where(Outline.project_id == project_id),
        select(MemoryEntry).where(MemoryEntry.project_id == project_id),
    ]
    return any(session.exec(statement).first() is not None for statement in checks)


def has_running_project_initialization(session: Session, project_id: str) -> bool:
    statement = select(Task).where(
        Task.project_id == project_id,
        Task.type == "project_initialization",
        Task.status.in_(["pending", "processing"]),
    )
    return session.exec(statement).first() is not None


def summarize_text_for_prompt(text: str, limit: int = 12000) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n\n……【中间内容已截断】……\n\n{text[-half:]}"


def build_source_chapter_summary_prompt(source_chapter: SourceChapter) -> tuple[str, str]:
    system_prompt = "你是小说原文分析助手。只输出 JSON，不要 Markdown。"
    user_prompt = f"""
请分析以下小说章节，输出 JSON：
{{
  "summary_short": "200-400字章节摘要",
  "summary_medium": "更详细的剧情摘要",
  "key_characters": ["角色名"],
  "key_locations": ["地点"],
  "key_events": ["关键事件"],
  "time_markers": ["时间线索"]
}}

章节标题：{source_chapter.title}
章节原文：
{summarize_text_for_prompt(source_chapter.raw_text, 16000)}
""".strip()
    return system_prompt, user_prompt


def build_source_import_summary_prompt(source_import: SourceImport, source_chapters: list[SourceChapter]) -> tuple[str, str]:
    system_prompt = "你是长篇小说总纲分析助手。只输出 JSON，不要 Markdown。"
    chapter_lines = []
    for chapter in source_chapters[:120]:
        summary = chapter.summary_short or summarize_text_for_prompt(chapter.raw_text, 500)
        chapter_lines.append(f"{chapter.sequence}. {chapter.title}：{summary}")
    user_prompt = f"""
请根据小说目录和章节摘要，输出 JSON：
{{
  "book_summary": "全书剧情总览",
  "world_summary": "世界观/力量体系/社会结构摘要",
  "character_summary": "主要角色与关系摘要",
  "outline_summary": "主线大纲和阶段性篇章摘要"
}}

小说文件：{source_import.file_name}
总章节数：{source_import.chapter_count}

章节摘要：
{chr(10).join(chapter_lines)}
""".strip()
    return system_prompt, user_prompt


def build_source_chunk_summary_prompt(source_import: SourceImport, chapters_chunk: list[SourceChapter]) -> tuple[str, str]:
    system_prompt = "你是长篇小说分段摘要助手。只输出 JSON，不要 Markdown。"
    chapter_lines = []
    for chapter in chapters_chunk:
        summary = chapter.summary_short or chapter.summary_medium or summarize_text_for_prompt(chapter.raw_text, 400)
        chapter_lines.append(f"{chapter.sequence}. {chapter.title}：{summarize_text_for_prompt(summary, 500)}")
    start_sequence = chapters_chunk[0].sequence if chapters_chunk else None
    end_sequence = chapters_chunk[-1].sequence if chapters_chunk else None
    user_prompt = f"""
请根据这一组连续章节摘要，输出 JSON：
{{
  "title": "本分组标题，概括这一段剧情阶段",
  "summary": "800-1200字分组剧情摘要，覆盖关键转折",
  "key_characters": ["角色名"],
  "key_events": ["关键事件"],
  "key_locations": ["关键地点"]
}}

小说文件：{source_import.file_name}
总章节数：{source_import.chapter_count}
分组范围：第 {start_sequence} 章 至 第 {end_sequence} 章

章节摘要：
{chr(10).join(chapter_lines)}
""".strip()
    return system_prompt, user_prompt


def build_source_layered_book_summary_prompt(source_import: SourceImport, chunk_summaries: list[dict]) -> tuple[str, str]:
    system_prompt = "你是长篇小说分层总纲分析助手。只输出 JSON，不要 Markdown。"
    chunk_lines = []
    for index, chunk in enumerate(chunk_summaries, start=1):
        chunk_lines.append(
            f"{index}. {chunk.get('title') or f'分组{index}'} "
            f"（章节 {chunk.get('start_sequence')}-{chunk.get('end_sequence')}）："
            f"{summarize_text_for_prompt(str(chunk.get('summary') or ''), 1000)}"
        )
    user_prompt = f"""
请根据全书各分组摘要，输出 JSON：
{{
  "book_summary": "全书剧情总览，覆盖开端、中段、后段与结局/最新进展",
  "world_summary": "世界观/力量体系/社会结构摘要",
  "character_summary": "主要角色、关系变化与阵营摘要",
  "outline_summary": "主线大纲和阶段性篇章摘要"
}}

小说文件：{source_import.file_name}
总章节数：{source_import.chapter_count}
分组数量：{len(chunk_summaries)}

分组摘要：
{chr(10).join(chunk_lines)}
""".strip()
    return system_prompt, user_prompt


def build_project_initialization_prompt(user_input: str) -> tuple[str, str]:
    system_prompt = (
        "你是小说级漫画项目初始化助手。请紧扣用户创意进行原创设定，"
        "只输出 JSON，不要输出任何解释或 Markdown。"
    )
    user_prompt = f"""
请根据一句话创意生成一个可直接落库的漫画/小说项目骨架。
用户创意：{user_input}

必须输出 JSON 对象，字段如下：
{{
  "project": {{"title": "项目名", "description": "简介", "theme": "题材/风格", "language": "zh-CN"}},
  "settings": [{{"category": "世界观", "title": "设定标题", "content": "设定内容", "tags": ["标签"], "importance": 1-5}}],
  "characters": [{{"name": "角色名", "summary": "角色简介", "status": "active", "aliases": ["别名"], "data": {{"role": "主角/配角/反派", "personality": "性格", "goal": "目标"}}, "outfits": [{{"name": "默认服饰", "description": "服饰描述", "scene": "适用场景", "colors": "主色", "materials": "材质", "accessories": "配饰", "state": "状态", "is_default": true}}]}}],
  "relationships": [{{"source": "角色名", "target": "角色名", "relationship_type": "关系类型", "description": "关系说明", "intensity": 1-5, "tags": ["标签"]}}],
  "outlines": [{{"scope": "project|arc", "title": "大纲标题", "content": "大纲内容", "sort_order": 0}}],
  "chapters": [{{"sequence": 1, "title": "章节名", "summary": "章节摘要", "goal": "章节目标", "conflict": "冲突", "current_location": "地点", "current_time": "时间", "pov_character": "视角角色", "tasks": [{{"title": "任务名", "description": "任务说明", "type": "writing|review|storyboard", "sort_order": 0}}]}}],
  "memories": [{{"scope": "project", "content": "初始记忆", "memory_type": "event|setting|character", "tags": ["标签"], "importance": 1-5}}],
  "progress": {{"current_arc": "当前篇章", "current_location": "初始地点", "current_time": "初始时间", "main_conflict": "主线冲突", "active_threads": ["伏笔"], "pending_hooks": ["悬念"], "notes": "进度备注"}}
}}

要求：
- 中文输出。
- 生成 4-6 条设定、3-5 个角色、3-5 段关系、1 条全书大纲、3-6 个章节规划。
- 所有内容必须紧扣用户创意，做原创设计，不要套用通用模板。
- 角色姓名要根据创意的世界观和文化背景专门设计，彼此不能重名，禁止使用“张三/李四/主角/无名”这类占位名或与创意无关的默认名。
- 每个角色的 data.role 要区分（至少包含一个主角、一个反派），summary 各不相同。
- 各条设定的 title 和主题必须互不重复，分别覆盖不同方面（如世界观、力量体系、地理、组织、历史等），不要多条讲同一件事。
- 关系的 source/target 必须来自上面 characters 的 name。
- 不要生成正文和图片。
""".strip()
    return system_prompt, user_prompt


def build_source_initialization_context(source_import: SourceImport, source_chapters: list[SourceChapter]) -> str:
    summary_layers = source_import.summary_layers if isinstance(source_import.summary_layers, dict) else {}
    layered_chunks = summary_layers.get("chunks") if isinstance(summary_layers.get("chunks"), list) else []
    if layered_chunks:
        chunk_lines = []
        for index, chunk in enumerate(layered_chunks, start=1):
            if not isinstance(chunk, dict):
                continue
            title = chunk.get("title") or f"分组 {index}"
            start_sequence = chunk.get("start_sequence") or "?"
            end_sequence = chunk.get("end_sequence") or "?"
            summary = summarize_text_for_prompt(str(chunk.get("summary") or ""), 900)
            events = "、".join(normalize_list(chunk.get("key_events"))[:8])
            characters = "、".join(normalize_list(chunk.get("key_characters"))[:8])
            locations = "、".join(normalize_list(chunk.get("key_locations"))[:8])
            chunk_lines.append(
                f"{index}. {title}（章节 {start_sequence}-{end_sequence}）：{summary}\n"
                f"   关键角色：{characters or '暂无'}\n"
                f"   关键事件：{events or '暂无'}\n"
                f"   关键地点：{locations or '暂无'}"
            )
        return f"""
小说文件：{source_import.file_name}
原文章节总数：{source_import.chapter_count}
上下文类型：分层摘要
分层摘要分组数：{len(layered_chunks)}
已分析章节数：{summary_layers.get('analyzed_chapter_count') or '未知'}
全书摘要：{summarize_text_for_prompt(source_import.book_summary or summary_layers.get('book', {}).get('book_summary') or '暂无', 1800)}
世界观摘要：{summarize_text_for_prompt(source_import.world_summary or summary_layers.get('book', {}).get('world_summary') or '暂无', 1200)}
角色摘要：{summarize_text_for_prompt(source_import.character_summary or summary_layers.get('book', {}).get('character_summary') or '暂无', 1200)}
大纲摘要：{summarize_text_for_prompt(source_import.outline_summary or summary_layers.get('book', {}).get('outline_summary') or '暂无', 1200)}

分层分组摘要（覆盖全书已分析章节，优先用于理解全局剧情）：
{chr(10).join(chunk_lines)}
""".strip()

    analyzed_chapters = [chapter for chapter in source_chapters if (chapter.summary_short or "").strip()]
    prompt_chapters = (analyzed_chapters or source_chapters)[:30]
    chapter_lines = []
    for chapter in prompt_chapters:
        summary = chapter.summary_short or summarize_text_for_prompt(chapter.raw_text, 240)
        summary = summarize_text_for_prompt(summary, 240)
        chapter_lines.append(f"{chapter.sequence}. {chapter.title}：{summary}")
    return f"""
小说文件：{source_import.file_name}
原文章节总数：{source_import.chapter_count}
本次可用摘要章节数：{len(prompt_chapters)}
全书摘要：{summarize_text_for_prompt(source_import.book_summary or '暂无', 1200)}
世界观摘要：{summarize_text_for_prompt(source_import.world_summary or '暂无', 800)}
角色摘要：{summarize_text_for_prompt(source_import.character_summary or '暂无', 800)}
大纲摘要：{summarize_text_for_prompt(source_import.outline_summary or '暂无', 800)}

可用章节摘要（只覆盖开篇，不代表全书所有章节）：
{chr(10).join(chapter_lines)}
""".strip()


def build_source_initialization_step_prompt(context: str, step: str, known_payload: dict | None = None) -> tuple[str, str]:
    system_prompt = "你是小说级漫画项目初始化助手。只输出 JSON，不要 Markdown 或解释。"
    known_json = json.dumps(known_payload or {}, ensure_ascii=False)
    specs = {
        "project_settings": """
输出 JSON：
{
  "project": {"title": "项目名", "description": "80-160字简介", "theme": "题材/风格", "language": "zh-CN"},
  "settings": [{"category": "世界观", "title": "设定标题", "content": "80-160字设定内容", "tags": ["标签"], "importance": 1-5}]
}
限制：settings 只生成 4 条，覆盖世界观、力量体系、主要地域/组织、主线矛盾。不要生成角色、章节、正文、图片。
""",
        "characters_relationships": """
输出 JSON：
{
  "characters": [{"name": "角色名", "summary": "60-120字角色简介", "status": "active", "aliases": ["别名"], "data": {"role": "主角/配角/反派", "personality": "性格", "goal": "目标"}, "outfits": [{"name": "默认服饰", "description": "服饰描述", "scene": "适用场景", "colors": "主色", "materials": "材质", "accessories": "配饰", "state": "状态", "is_default": true}]}],
  "relationships": [{"source": "角色名", "target": "角色名", "relationship_type": "关系类型", "description": "关系说明", "intensity": 1-5, "tags": ["标签"]}]
}
限制：characters 只生成 4 个，必须包含主角和关键配角/反派；relationships 只生成 4 条，source/target 必须来自 characters.name。不要生成设定、章节、正文、图片。
""",
        "outlines_chapters": """
输出 JSON：
{
  "outlines": [{"scope": "project|arc", "title": "大纲标题", "content": "120-240字大纲内容", "sort_order": 0}],
  "chapters": [{"sequence": 1, "source_sequence": 1, "title": "章节名", "summary": "60-120字章节摘要", "goal": "章节目标", "conflict": "冲突", "current_location": "地点", "current_time": "时间", "pov_character": "视角角色", "tasks": [{"title": "任务名", "description": "任务说明", "type": "writing|review|storyboard", "sort_order": 0}]}]
}
限制：outlines 只生成 2 条：全书总纲、开篇篇章；chapters 只生成 6 个；source_sequence 必须来自可用章节摘要中的 sequence。不要生成正文和图片。
""",
        "memories_progress": """
输出 JSON：
{
  "memories": [{"scope": "project", "content": "初始记忆", "memory_type": "event|setting|character", "tags": ["标签"], "importance": 1-5}],
  "progress": {"current_arc": "当前篇章", "current_location": "初始地点", "current_time": "初始时间", "main_conflict": "主线冲突", "active_threads": ["伏笔"], "pending_hooks": ["悬念"], "notes": "进度备注"}
}
限制：memories 只生成 4 条。不要生成设定、角色、章节、正文、图片。
""",
    }
    user_prompt = f"""
请严格基于以下小说原文分析上下文生成项目初始化的一部分。

【上下文】
{context}

【已生成内容，供保持一致】
{known_json}

【本步骤要求】
{specs[step]}

通用要求：中文输出；严格贴合原文；内容精简；不要套默认玄幻模板；不要输出 JSON 以外的任何文本。
""".strip()
    return system_prompt, user_prompt


def persist_project_initialization_payload(
    session: Session,
    project_id: str,
    payload: dict,
    *,
    story_input: str | None = None,
    task_id: str | None = None,
    source_chapters: list[SourceChapter] | None = None,
):
    project = crud_project.get_project(session, project_id)
    if not project:
        raise ValueError("Project not found")
    if story_input is not None:
        project.story_input = story_input
    project_data = normalize_dict(payload.get("project"))
    project.title = str(project_data.get("title") or project.title)
    project.description = str(project_data.get("description") or project.description or "")
    project.theme = str(project_data.get("theme") or project.theme or "")
    project.language = str(project_data.get("language") or project.language or "zh-CN")
    project.workflow_mode = "novel_comic"
    project.memory_enabled = True
    project.outline_enabled = True
    project.setting_mode = "advanced"
    project.updated_at = datetime.utcnow()
    session.add(project)

    category_map = {}
    seen_setting_titles = set()
    for index, item in enumerate(normalize_list(payload.get("settings"))):
        item = normalize_dict(item)
        setting_title = str(item.get("title") or f"设定 {index + 1}").strip()
        dedupe_key = setting_title.lower()
        if dedupe_key in seen_setting_titles:
            continue
        seen_setting_titles.add(dedupe_key)
        category_name = str(item.get("category") or "通用设定")
        category = category_map.get(category_name)
        if not category:
            category = SettingCategory(project_id=project_id, name=category_name, description=f"AI 初始化生成的{category_name}", sort_order=len(category_map))
            session.add(category)
            session.flush()
            category_map[category_name] = category
        session.add(SettingEntry(
            project_id=project_id,
            category_id=category.id,
            title=setting_title,
            content=str(item.get("content") or ""),
            tags=normalize_list(item.get("tags")),
            importance=safe_int(item.get("importance"), 3),
        ))

    character_map = {}
    for item in normalize_list(payload.get("characters")):
        item = normalize_dict(item)
        name = str(item.get("name") or "").strip()
        if not name or name in character_map:
            continue
        character = Character(
            project_id=project_id,
            name=name,
            summary=str(item.get("summary") or ""),
            status=str(item.get("status") or "active"),
            aliases=normalize_list(item.get("aliases")),
            data=normalize_dict(item.get("data")),
        )
        session.add(character)
        session.flush()
        character_map[name] = character
        default_outfit_id = None
        for outfit_data in normalize_list(item.get("outfits")):
            outfit_data = normalize_dict(outfit_data)
            outfit = CharacterOutfit(
                project_id=project_id,
                character_id=character.id,
                name=str(outfit_data.get("name") or "默认服饰"),
                description=str(outfit_data.get("description") or "AI 初始化生成的默认服饰"),
                scene=outfit_data.get("scene"),
                colors=outfit_data.get("colors"),
                materials=outfit_data.get("materials"),
                accessories=outfit_data.get("accessories"),
                state=outfit_data.get("state"),
                is_default=bool(outfit_data.get("is_default", default_outfit_id is None)),
            )
            session.add(outfit)
            session.flush()
            if outfit.is_default and default_outfit_id is None:
                default_outfit_id = outfit.id
        if default_outfit_id:
            character.default_outfit_id = default_outfit_id
            session.add(character)

    for item in normalize_list(payload.get("relationships")):
        item = normalize_dict(item)
        source = character_map.get(str(item.get("source") or ""))
        target = character_map.get(str(item.get("target") or ""))
        if not source or not target or source.id == target.id:
            continue
        session.add(CharacterRelationship(
            project_id=project_id,
            source_character_id=source.id,
            target_character_id=target.id,
            relationship_type=str(item.get("relationship_type") or "关联"),
            description=item.get("description"),
            intensity=safe_int(item.get("intensity"), 3),
            tags=normalize_list(item.get("tags")),
        ))

    for index, item in enumerate(normalize_list(payload.get("outlines"))):
        item = normalize_dict(item)
        session.add(Outline(
            project_id=project_id,
            scope=str(item.get("scope") or "project"),
            title=str(item.get("title") or f"大纲 {index + 1}"),
            content=str(item.get("content") or ""),
            sort_order=safe_int(item.get("sort_order"), index),
        ))

    source_by_sequence = {chapter.sequence: chapter for chapter in (source_chapters or [])}
    first_chapter_id = None
    for item in normalize_list(payload.get("chapters")):
        item = normalize_dict(item)
        source_sequence = safe_int(item.get("source_sequence"), safe_int(item.get("sequence"), 0))
        source_chapter = source_by_sequence.get(source_sequence)
        chapter = Chapter(
            project_id=project_id,
            sequence=safe_int(item.get("sequence"), 1),
            title=str(item.get("title") or "未命名章节"),
            summary=item.get("summary"),
            goal=item.get("goal"),
            conflict=item.get("conflict"),
            current_location=item.get("current_location"),
            current_time=item.get("current_time"),
            pov_character=item.get("pov_character"),
            source_chapter_id=source_chapter.id if source_chapter else None,
            status="draft",
        )
        session.add(chapter)
        session.flush()
        if source_chapter:
            source_chapter.mapped_chapter_id = chapter.id
            session.add(source_chapter)
        if first_chapter_id is None:
            first_chapter_id = chapter.id
        for task_index, chapter_task in enumerate(normalize_list(item.get("tasks"))):
            chapter_task = normalize_dict(chapter_task)
            session.add(ChapterTask(
                project_id=project_id,
                chapter_id=chapter.id,
                title=str(chapter_task.get("title") or f"章节任务 {task_index + 1}"),
                description=chapter_task.get("description"),
                type=chapter_task.get("type"),
                sort_order=safe_int(chapter_task.get("sort_order"), task_index),
            ))

    for item in normalize_list(payload.get("memories")):
        item = normalize_dict(item)
        content = str(item.get("content") or "").strip()
        if content:
            session.add(MemoryEntry(
                project_id=project_id,
                scope=str(item.get("scope") or "project"),
                content=content,
                memory_type=str(item.get("memory_type") or "event"),
                tags=normalize_list(item.get("tags")),
                importance=safe_int(item.get("importance"), 3),
                source_type="project_initialization",
                source_id=task_id,
            ))

    progress_data = normalize_dict(payload.get("progress"))
    progress = session.exec(select(ProjectProgress).where(ProjectProgress.project_id == project_id)).first()
    if not progress:
        progress = ProjectProgress(project_id=project_id)
    progress.current_chapter_id = first_chapter_id or progress.current_chapter_id
    progress.current_arc = progress_data.get("current_arc")
    progress.current_location = progress_data.get("current_location")
    progress.current_time = progress_data.get("current_time")
    progress.main_conflict = progress_data.get("main_conflict")
    progress.active_threads = normalize_list(progress_data.get("active_threads"))
    progress.pending_hooks = normalize_list(progress_data.get("pending_hooks"))
    progress.notes = progress_data.get("notes")
    progress.updated_at = datetime.utcnow()
    session.add(progress)

    if first_chapter_id:
        project.current_chapter_id = first_chapter_id
        session.add(project)

    return {
        "settings": len(seen_setting_titles),
        "characters": len(character_map),
        "chapters": len(normalize_list(payload.get("chapters"))),
        "outlines": len(normalize_list(payload.get("outlines"))),
    }


def parse_ai_json_object(generated: str, required_key: str | None = None) -> dict:
    try:
        payload = json.loads(generated)
    except json.JSONDecodeError:
        blocks = extract_json_blocks(generated)
        payload = next((block for block in blocks if isinstance(block, dict) and (required_key is None or required_key in block)), None)
    if not isinstance(payload, dict):
        raise ValueError("AI 未返回可解析的 JSON")
    return payload


def generate_project_initialization_task(task_id: str, project_id: str, user_input: str):
    from app.core.database import engine

    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task:
            logger.error(f"Task {task_id} not found")
            return

        task.status = "processing"
        task.progress = 5
        task.message = "准备初始化项目..."
        session.add(task)
        session.commit()

        try:
            project = crud_project.get_project(session, project_id)
            if not project:
                raise ValueError("Project not found")

            set_task_progress(session, task_id, 10, "AI 正在理解一句话创意...")
            system_prompt, prompt = build_project_initialization_prompt(user_input)
            generated = AIService(session).generate_text(system_prompt, prompt)
            try:
                payload = json.loads(generated)
            except json.JSONDecodeError:
                blocks = extract_json_blocks(generated)
                payload = next((block for block in blocks if isinstance(block, dict) and "project" in block), None)
            if not isinstance(payload, dict):
                raise ValueError("AI 未返回可解析的项目初始化 JSON")
            if has_initialized_content(session, project_id):
                raise ValueError("项目已完成初始化，取消重复写入")

            set_task_progress(session, task_id, 25, "正在写入项目基础信息...")
            project.story_input = user_input
            session.add(project)
            project_data = normalize_dict(payload.get("project"))
            project.title = str(project_data.get("title") or project.title)
            project.description = str(project_data.get("description") or project.description or "")
            project.theme = str(project_data.get("theme") or project.theme or "")
            project.language = str(project_data.get("language") or project.language or "zh-CN")
            project.workflow_mode = "novel_comic"
            project.memory_enabled = True
            project.outline_enabled = True
            project.setting_mode = "advanced"
            project.updated_at = datetime.utcnow()
            session.add(project)
            logger.info("正在生成世界观、境界和组织设定...")
            category_map = {}
            seen_setting_titles = set()
            for index, item in enumerate(normalize_list(payload.get("settings"))):
                item = normalize_dict(item)
                setting_title = str(item.get("title") or f"设定 {index + 1}").strip()
                dedupe_key = setting_title.lower()
                if dedupe_key in seen_setting_titles:
                    continue
                seen_setting_titles.add(dedupe_key)
                category_name = str(item.get("category") or "通用设定")
                category = category_map.get(category_name)
                if not category:
                    category = SettingCategory(project_id=project_id, name=category_name, description=f"AI 初始化生成的{category_name}", sort_order=len(category_map))
                    session.add(category)
                    session.flush()
                    category_map[category_name] = category
                session.add(SettingEntry(
                    project_id=project_id,
                    category_id=category.id,
                    title=setting_title,
                    content=str(item.get("content") or ""),
                    tags=normalize_list(item.get("tags")),
                    importance=safe_int(item.get("importance"), 3),
                ))
            logger.info("正在生成角色和默认服饰...")
            character_map = {}
            for item in normalize_list(payload.get("characters")):
                item = normalize_dict(item)
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                if name in character_map:
                    continue
                character = Character(
                    project_id=project_id,
                    name=name,
                    summary=str(item.get("summary") or ""),
                    status=str(item.get("status") or "active"),
                    aliases=normalize_list(item.get("aliases")),
                    data=normalize_dict(item.get("data")),
                )
                session.add(character)
                session.flush()
                character_map[name] = character

                default_outfit_id = None
                for outfit_data in normalize_list(item.get("outfits")):
                    outfit_data = normalize_dict(outfit_data)
                    outfit = CharacterOutfit(
                        project_id=project_id,
                        character_id=character.id,
                        name=str(outfit_data.get("name") or "默认服饰"),
                        description=str(outfit_data.get("description") or "AI 初始化生成的默认服饰"),
                        scene=outfit_data.get("scene"),
                        colors=outfit_data.get("colors"),
                        materials=outfit_data.get("materials"),
                        accessories=outfit_data.get("accessories"),
                        state=outfit_data.get("state"),
                        is_default=bool(outfit_data.get("is_default", default_outfit_id is None)),
                    )
                    session.add(outfit)
                    session.flush()
                    if outfit.is_default and default_outfit_id is None:
                        default_outfit_id = outfit.id
                if default_outfit_id:
                    character.default_outfit_id = default_outfit_id
                    session.add(character)
            logger.info("正在生成角色关系...")
            for item in normalize_list(payload.get("relationships")):
                item = normalize_dict(item)
                source = character_map.get(str(item.get("source") or ""))
                target = character_map.get(str(item.get("target") or ""))
                if not source or not target or source.id == target.id:
                    continue
                session.add(CharacterRelationship(
                    project_id=project_id,
                    source_character_id=source.id,
                    target_character_id=target.id,
                    relationship_type=str(item.get("relationship_type") or "关联"),
                    description=item.get("description"),
                    intensity=safe_int(item.get("intensity"), 3),
                    tags=normalize_list(item.get("tags")),
                ))
            logger.info("正在生成大纲和章节规划...")
            for index, item in enumerate(normalize_list(payload.get("outlines"))):
                item = normalize_dict(item)
                session.add(Outline(
                    project_id=project_id,
                    scope=str(item.get("scope") or "project"),
                    title=str(item.get("title") or f"大纲 {index + 1}"),
                    content=str(item.get("content") or ""),
                    sort_order=safe_int(item.get("sort_order"), index),
                ))

            first_chapter_id = None
            for item in normalize_list(payload.get("chapters")):
                item = normalize_dict(item)
                chapter = Chapter(
                    project_id=project_id,
                    sequence=safe_int(item.get("sequence"), 1),
                    title=str(item.get("title") or "未命名章节"),
                    summary=item.get("summary"),
                    goal=item.get("goal"),
                    conflict=item.get("conflict"),
                    current_location=item.get("current_location"),
                    current_time=item.get("current_time"),
                    pov_character=item.get("pov_character"),
                    status="draft",
                )
                session.add(chapter)
                session.flush()
                if first_chapter_id is None:
                    first_chapter_id = chapter.id
                for task_index, chapter_task in enumerate(normalize_list(item.get("tasks"))):
                    chapter_task = normalize_dict(chapter_task)
                    session.add(ChapterTask(
                        project_id=project_id,
                        chapter_id=chapter.id,
                        title=str(chapter_task.get("title") or f"章节任务 {task_index + 1}"),
                        description=chapter_task.get("description"),
                        type=chapter_task.get("type"),
                        sort_order=safe_int(chapter_task.get("sort_order"), task_index),
                    ))
            logger.info("正在写入初始记忆和项目进度...")
            for item in normalize_list(payload.get("memories")):
                item = normalize_dict(item)
                content = str(item.get("content") or "").strip()
                if content:
                    session.add(MemoryEntry(
                        project_id=project_id,
                        scope=str(item.get("scope") or "project"),
                        content=content,
                        memory_type=str(item.get("memory_type") or "event"),
                        tags=normalize_list(item.get("tags")),
                        importance=safe_int(item.get("importance"), 3),
                        source_type="project_initialization",
                        source_id=task_id,
                    ))

            progress_data = normalize_dict(payload.get("progress"))
            progress = session.exec(select(ProjectProgress).where(ProjectProgress.project_id == project_id)).first()
            if not progress:
                progress = ProjectProgress(project_id=project_id)
            progress.current_chapter_id = first_chapter_id or progress.current_chapter_id
            progress.current_arc = progress_data.get("current_arc")
            progress.current_location = progress_data.get("current_location")
            progress.current_time = progress_data.get("current_time")
            progress.main_conflict = progress_data.get("main_conflict")
            progress.active_threads = normalize_list(progress_data.get("active_threads"))
            progress.pending_hooks = normalize_list(progress_data.get("pending_hooks"))
            progress.notes = progress_data.get("notes")
            progress.updated_at = datetime.utcnow()
            session.add(progress)

            if first_chapter_id:
                project.current_chapter_id = first_chapter_id
                session.add(project)
            session.commit()
            finish_task(task_id, "completed", "项目初始化完成", {
                "settings": len(normalize_list(payload.get("settings"))),
                "characters": len(character_map),
                "chapters": len(normalize_list(payload.get("chapters"))),
                "outlines": len(normalize_list(payload.get("outlines"))),
            })
        except Exception as e:
            session.rollback()
            logger.error(f"Project initialization task {task_id} failed: {e}")
            traceback.print_exc()
            finish_task(task_id, "failed", f"项目初始化失败：{e}")


def latest_source_import(session: Session, project_id: str) -> SourceImport:
    source_import = session.exec(
        select(SourceImport)
        .where(SourceImport.project_id == project_id)
        .order_by(SourceImport.created_at.desc())
    ).first()
    if not source_import:
        raise ValueError("请先导入小说原文")
    return source_import


def get_source_chapters_for_import(session: Session, source_import_id: int, limit: int | None = None) -> list[SourceChapter]:
    statement = (
        select(SourceChapter)
        .where(SourceChapter.source_import_id == source_import_id)
        .order_by(SourceChapter.sequence)
    )
    if limit:
        statement = statement.limit(limit)
    return session.exec(statement).all()


def generate_source_analysis_task(task_id: str, project_id: str, max_chapters: int | None = 50, mode: str = "continue"):
    from app.agents.runtime import AgentRuntime
    from app.agents.source_analysis_agent import SourceAnalysisAgent
    from app.core.database import engine

    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task:
            logger.error(f"Task {task_id} not found")
            return

        try:
            agent = SourceAnalysisAgent(session)
            runtime_result = AgentRuntime(session, task_id, agent, {
                "project_id": project_id,
                "max_chapters": max_chapters,
                "mode": mode,
            }).run()
            if runtime_result.get("status") == "cancelled":
                return
            result = runtime_result.get("summary") or {}
            analyzed_count = result.get("analyzed_chapters", 0)
            total_count = result.get("total_chapters", 0)
            failed_count = result.get("failed_count", 0)
            analyzed_this_run = result.get("analyzed_this_run", 0)
            is_partial = bool(result.get("partial"))
            if failed_count:
                message = f"原文分析部分完成：本轮成功 {analyzed_this_run} 章，失败 {failed_count} 章（累计已分析 {analyzed_count}/{total_count} 章）"
            elif is_partial:
                message = f"原文分析完成（已分析 {analyzed_count}/{total_count} 章）"
            else:
                agent_run = session.get(AgentRun, runtime_result.get("agent_run_id"))
                selected_chapters = ((agent_run.state_payload or {}).get("select_chapters") or {}).get("selected_chapters") if agent_run else None
                message = "原文分析已完成，无需继续分析" if selected_chapters == 0 else f"原文分析完成：本轮成功 {analyzed_this_run} 章"
            finish_task(task_id, "completed", message, result)
        except Exception as e:
            session.rollback()
            logger.error(f"Source analysis task {task_id} failed: {e}")
            traceback.print_exc()
            finish_task(task_id, "failed", f"原文分析失败：{e}")


def generate_source_project_initialization_task(task_id: str, project_id: str):
    from app.agents.runtime import AgentRuntime
    from app.agents.source_project_init_agent import SourceProjectInitAgent
    from app.core.database import engine

    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task:
            logger.error(f"Task {task_id} not found")
            return

        try:
            agent = SourceProjectInitAgent(session)
            result = AgentRuntime(session, task_id, agent, {"project_id": project_id}).run()
            if result.get("status") == "cancelled":
                return
            finish_task(task_id, "completed", "基于原文的项目初始化完成", result)
        except Exception as e:
            session.rollback()
            logger.error(f"Source project initialization task {task_id} failed: {e}")
            traceback.print_exc()
            finish_task(task_id, "failed", f"基于原文初始化失败：{e}")


def generate_chapter_content_task(task_id: str, chapter_id: int, user_input: str = "", save_version: bool = True):
    from app.agents.chapter_adaptation_agent import ChapterAdaptationAgent
    from app.agents.runtime import AgentRuntime
    from app.core.database import engine

    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task:
            logger.error(f"Task {task_id} not found")
            return

        try:
            agent = ChapterAdaptationAgent(session)
            result = AgentRuntime(session, task_id, agent, {
                "chapter_id": chapter_id,
                "user_input": user_input or "",
                "save_version": save_version,
            }).run()
            if result.get("status") == "cancelled":
                return
            finish_task(task_id, "completed", "章节正文生成完成", result)
        except Exception as e:
            session.rollback()
            logger.error(f"Chapter content generation task {task_id} failed: {e}")
            traceback.print_exc()
            finish_task(task_id, "failed", f"章节正文生成失败：{e}")


# --- Endpoints ---

from pydantic import BaseModel

class StoryboardRequest(BaseModel):
    user_input: str


class ChapterGenerateRequest(BaseModel):
    user_input: str | None = None
    save_version: bool = True


class ProjectInitializeRequest(BaseModel):
    user_input: str


class SourceAnalyzeRequest(BaseModel):
    mode: str = "continue"
    max_chapters: int | None = 50


@router.post("/project-initialize/{project_id}")
def initialize_project_from_prompt(
    project_id: str,
    request: ProjectInitializeRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    user_input = request.user_input.strip()
    if not user_input:
        raise HTTPException(status_code=400, detail="请输入一句话创意")

    try:
        session.exec(text("BEGIN IMMEDIATE"))
        project = crud_project.get_project(session, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        if has_initialized_content(session, project_id):
            raise HTTPException(status_code=400, detail="项目已有设定、角色、章节或大纲，请在空项目中使用一句话初始化")
        if has_running_project_initialization(session, project_id):
            raise HTTPException(status_code=400, detail="项目初始化任务已在运行中")

        project.story_input = user_input
        session.add(project)
        task = Task(
            type="project_initialization",
            status="pending",
            project_id=project_id,
            name="一句话初始化项目",
            description="AI 正在生成设定、角色、关系、大纲和章节规划",
            progress=0,
            message="等待 AI 初始化...",
        )
        session.add(task)
        session.commit()
        session.refresh(task)
    except HTTPException:
        session.rollback()
        raise

    background_tasks.add_task(generate_project_initialization_task, task.id, project_id, user_input)
    return {"task_id": task.id}


@router.post("/source-analyze/{project_id}")
def analyze_source_import(
    project_id: str,
    background_tasks: BackgroundTasks,
    request: SourceAnalyzeRequest | None = None,
    session: Session = Depends(get_session),
):
    project = crud_project.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    source_import = session.exec(
        select(SourceImport).where(SourceImport.project_id == project_id).order_by(SourceImport.created_at.desc())
    ).first()
    if not source_import:
        raise HTTPException(status_code=400, detail="请先导入小说原文")

    request = request or SourceAnalyzeRequest()
    if request.mode not in {"continue", "restart", "all"}:
        raise HTTPException(status_code=400, detail="Invalid source analysis mode")
    max_chapters = None if request.mode == "all" else request.max_chapters
    task = Task(
        type="source_analysis",
        status="pending",
        project_id=project_id,
        name="原文分析",
        description="AI 正在分析原文章节并生成全书摘要",
        progress=0,
        message="等待原文分析...",
        input_payload={
            "project_id": project_id,
            "max_chapters": max_chapters,
            "mode": request.mode,
        },
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    background_tasks.add_task(generate_source_analysis_task, task.id, project_id, max_chapters, request.mode)
    return {"task_id": task.id}


@router.post("/project-initialize-from-source/{project_id}")
def initialize_project_from_source(
    project_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    try:
        session.exec(text("BEGIN IMMEDIATE"))
        project = crud_project.get_project(session, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        if has_initialized_content(session, project_id):
            raise HTTPException(status_code=400, detail="项目已有设定、角色、章节或大纲，请在空项目中使用原文初始化")
        source_import = session.exec(
            select(SourceImport).where(SourceImport.project_id == project_id).order_by(SourceImport.created_at.desc())
        ).first()
        if not source_import:
            raise HTTPException(status_code=400, detail="请先导入小说原文")
        running = session.exec(select(Task).where(
            Task.project_id == project_id,
            Task.type.in_(["project_initialization", "source_project_initialization"]),
            Task.status.in_(["pending", "processing"]),
        )).first()
        if running:
            raise HTTPException(status_code=400, detail="项目初始化任务已在运行中")

        task = Task(
            type="source_project_initialization",
            status="pending",
            project_id=project_id,
            name="原文初始化项目",
            description="AI 正在基于导入小说生成设定、角色、关系、大纲和章节规划",
            progress=0,
            message="等待原文初始化...",
        )
        session.add(task)
        session.commit()
        session.refresh(task)
    except HTTPException:
        session.rollback()
        raise

    background_tasks.add_task(generate_source_project_initialization_task, task.id, project_id)
    return {"task_id": task.id}


@router.post("/chapter-content/{chapter_id}", response_model=ChapterRead)
def generate_chapter_content(
    chapter_id: int,
    request: ChapterGenerateRequest,
    session: Session = Depends(get_session),
):
    chapter = session.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    from app.agents.chapter_adaptation_agent import ChapterAdaptationAgent

    try:
        return ChapterAdaptationAgent(session).generate_content(chapter_id, request.user_input or "", request.save_version)
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


@router.post("/chapter-content-task/{chapter_id}")
def generate_chapter_content_background(
    chapter_id: int,
    request: ChapterGenerateRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    chapter = session.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    running = session.exec(select(Task).where(
        Task.project_id == chapter.project_id,
        Task.type == "chapter_content_generation",
        Task.scope_type == "chapter",
        Task.scope_id == str(chapter.id),
        Task.status.in_(["pending", "processing"]),
    )).first()
    if running:
        raise HTTPException(status_code=400, detail="当前章节正文生成任务已在运行中")

    task = Task(
        type="chapter_content_generation",
        status="pending",
        project_id=chapter.project_id,
        name=f"生成章节正文：{chapter.title}",
        description="AI 正在基于章节上下文生成正文",
        progress=0,
        message="等待章节正文生成...",
        scope_type="chapter",
        scope_id=str(chapter.id),
        input_payload={
            "chapter_id": chapter.id,
            "user_input": request.user_input or "",
            "save_version": request.save_version,
        },
    )
    session.add(task)
    session.commit()
    session.refresh(task)

    background_tasks.add_task(
        generate_chapter_content_task,
        task.id,
        chapter.id,
        request.user_input or "",
        request.save_version,
    )
    return {"task_id": task.id}


@router.post("/chapter-continuity/{chapter_id}")
def review_chapter_continuity(chapter_id: int, session: Session = Depends(get_session)):
    from app.agents.chapter_review_agent import ChapterReviewAgent

    try:
        return ChapterReviewAgent(session).review_continuity(chapter_id)
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc


def generate_chapter_storyboard_task(task_id: str, chapter_id: int, user_input: str = ""):
    logger.info(f"Starting chapter storyboard generation task: {task_id} for chapter: {chapter_id}")
    from app.core.database import engine
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task:
            logger.error(f"Task {task_id} not found")
            return

        task.status = "processing"
        session.add(task)
        session.commit()

        try:
            chapter = session.get(Chapter, chapter_id)
            if not chapter:
                raise ValueError("Chapter not found")

            context_service = ContextAssemblyService(session)
            context = context_service.build_chapter_context(chapter.project_id, chapter.id)
            context_prompt = context_service.render_context_prompt(context)

            chapter_text = chapter.content or "暂无章节正文，请根据章节目标和小纲生成分镜。"
            final_prompt = f"""
{context_prompt}

【当前章节正文】
{chapter_text}

【用户补充要求】
{user_input or '无'}

请把当前章节改写为漫画分镜 JSON。如果上下文包含原文章节正文，必须优先遵循原文事件顺序和场景信息。每个分镜应包含 scene、action、dialogue、characters、prompt、negative_prompt；如能判断角色服饰，请提供 selected_outfits。
""".strip()

            log_task_event(session, task_id, "Calling AI service for chapter storyboard generation...")
            generated_text = AIService(session).generate_storyboard(get_system_prompt(), final_prompt)
            json_blocks = extract_json_blocks(generated_text)
            story_blocks = [block for block in json_blocks if block.get("type") == "storyboard"]
            if not story_blocks:
                story_blocks = [block for block in json_blocks if block.get("type") not in ["character_sheet", "comic_config"]]
            if not story_blocks:
                raise ValueError("AI response did not contain storyboard JSON blocks")

            for block in story_blocks:
                if "selected_outfits" in block:
                    block["selected_outfits"] = block.get("selected_outfits") or {}

            items = crud_project.save_storyboard(session, chapter.project_id, story_blocks, chapter_id=chapter.id)
            ConsistencyService(session).normalize_project(chapter.project_id)

            task.status = "completed"
            task.progress = 100
            task.result = {"chapter_id": chapter.id, "storyboard_items": len(items), "blocks_found": len(json_blocks)}
            session.add(task)
            session.commit()
            log_task_event(session, task_id, f"Chapter storyboard task {task_id} completed successfully.")
        except Exception as e:
            logger.error(f"Chapter storyboard task {task_id} failed: {e}")
            traceback.print_exc()
            log_task_event(session, task_id, f"Chapter storyboard task failed: {e}")
            task.status = "failed"
            task.message = str(e)
            session.add(task)
            session.commit()


@router.post("/chapter-storyboard/{chapter_id}")
def generate_chapter_storyboard(
    chapter_id: int,
    request: ChapterGenerateRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    chapter = session.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    running = session.exec(select(Task).where(
        Task.project_id == chapter.project_id,
        Task.type == "chapter_storyboard",
        Task.scope_type == "chapter",
        Task.scope_id == str(chapter.id),
        Task.status.in_(["pending", "processing"]),
    )).first()
    if running:
        raise HTTPException(status_code=400, detail="当前章节分镜生成任务已在运行中")

    task = Task(
        type="chapter_storyboard",
        status="pending",
        project_id=chapter.project_id,
        name="生成章节分镜",
        description=f"为章节《{chapter.title}》生成分镜",
        scope_type="chapter",
        scope_id=str(chapter.id),
        input_payload={
            "chapter_id": chapter.id,
            "user_input": request.user_input or "",
        },
    )
    session.add(task)
    session.commit()
    session.refresh(task)

    background_tasks.add_task(generate_chapter_storyboard_task, task.id, chapter.id, request.user_input or "")
    return {"task_id": task.id}


@router.post("/storyboard/{project_id}")
def generate_storyboard(
    project_id: str, 
    request: StoryboardRequest, 
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session)
):
    user_input = request.user_input
    logger.info(f"Received request to generate storyboard for project {project_id}")
    project = crud_project.get_project(session, project_id)
    if not project:
        logger.error(f"Project {project_id} not found")
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Save User Input Immediately
    project.story_input = user_input
    session.add(project)
    session.commit()
    
    # Create Task
    task = Task(
        type="storyboard", 
        status="pending", 
        project_id=project_id,
        name="Generate Storyboard",
        description=f"Generating storyboard based on user input..."
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    logger.info(f"Task created: {task.id}")
    
    background_tasks.add_task(generate_storyboard_task, task.id, project_id, user_input)
    
    return {"task_id": task.id}

@router.post("/all-images/{project_id}")
def generate_all_images(
    project_id: str, 
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session)
):
    logger.info(f"Received request to generate all images for project {project_id}")
    project = crud_project.get_project(session, project_id)
    if not project:
        logger.error(f"Project {project_id} not found")
        raise HTTPException(status_code=404, detail="Project not found")
        
    task = Task(
        type="image_generation", 
        status="pending", 
        project_id=project_id,
        name="Batch Generate Images",
        description="Generating all storyboard images"
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    logger.info(f"Task created: {task.id}")
    
    background_tasks.add_task(generate_all_images_task, task.id, project_id)
    
    return {"task_id": task.id}

# Keep individual endpoints for manual control, but maybe make them async too?
# User asked for "Back task" for "generation". Usually implies the bulk actions.
# Single panel generation is usually fast enough (5-10s), but can be async if desired.
# For now, let's keep single endpoints sync for immediate feedback, or make them async if user insists "All generation".
# The prompt says "Generate text/image takes long time". 
# Let's keep single endpoints sync for simplicity of interaction (user waits 5s is ok), 
# but "One Click" and "Storyboard" are definitely async.

@router.post("/all-characters/{project_id}")
def generate_all_characters(
    project_id: str, 
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session)
):
    logger.info(f"Received request to generate all characters for project {project_id}")
    project = crud_project.get_project(session, project_id)
    if not project:
        logger.error(f"Project {project_id} not found")
        raise HTTPException(status_code=404, detail="Project not found")
        
    task = Task(
        type="character_generation", 
        status="pending", 
        project_id=project_id,
        name="Batch Generate Characters",
        description="Generating all character design sheets"
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    logger.info(f"Task created: {task.id}")
    
    background_tasks.add_task(generate_all_characters_task, task.id, project_id)
    
    return {"task_id": task.id}

@router.post("/character/{character_id}")
def generate_character(
    character_id: int, 
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session)
):
    char = session.get(Character, character_id)
    if not char:
        raise HTTPException(status_code=404, detail="Character not found")
        
    task = Task(
        type="character_generation", 
        status="pending", 
        project_id=char.project_id,
        name=f"Draw Character: {char.name}",
        description=f"Drawing design sheet for character {char.name}"
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    
    background_tasks.add_task(generate_character_task, task.id, character_id)
    
    return {"task_id": task.id}

def generate_panel_task(task_id: str, item_id: int):
    logger.info(f"Starting panel generation task: {task_id} for item: {item_id}")
    from app.core.database import engine
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task:
            logger.error(f"Task {task_id} not found")
            return
            
        task.status = "processing"
        session.add(task)
        session.commit()
        
        try:
            item = session.get(StoryboardItem, item_id)
            if not item:
                 raise ValueError("Storyboard item not found")
            
            project = item.project
            ai = AIService(session)
            char_names = extract_character_names(item.data.get("characters", []))
            json_prompt = json.dumps(item.data, ensure_ascii=False, indent=2)
            json_prompt += build_panel_outfit_prompt(project, item, char_names)
            json_prompt += "\n\n use json block as user input prompt to generate 2*2 grid comic image."

            context_images = []
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

            # 1. Find Character Images
            # STRICT POLICY: Only use the currently active character image (p_char.image_url).
            # Do NOT search ImageHistory or other versions. This ensures consistency with the user's current selection.
        
            if project.characters:
                for name in char_names:
                    for p_char in project.characters:
                        if p_char.image_url and (p_char.name in name or name in p_char.name):
                            rel_path = p_char.image_url.lstrip("/")
                            abs_path = os.path.join(base_dir, rel_path.replace("/", os.sep))
                            if os.path.exists(abs_path) and abs_path not in context_images:
                                context_images.append(abs_path)
            
            # 2. Previous Panels - RE-ENABLED but with strict filtering
            # We want to use PREVIOUSLY CONFIRMED panels as reference to maintain consistency,
            # but NOT the current panel's old version (which we are regenerating).
            # STRICT POLICY: Only use currently active panel images (i.image_url) from the database.
            
            # Filter logic:
            # - Use panels with sequence number LESS than current item.sequence
            # - Ensure they have an image_url (meaning they are generated/confirmed)
            # - Limit to last 3 to keep context fresh but manageable
            
            prev_items = sorted([i for i in project.storyboard_items if i.sequence < item.sequence and i.image_url], key=lambda x: x.sequence)
            if prev_items:
                selected = []
                if len(prev_items) >= 3:
                    selected = [prev_items[0]] + prev_items[-2:] # First one + last two
                else:
                    selected = prev_items
                    
                for prev in selected:
                    rel_path = prev.image_url.lstrip("/")
                    abs_path = os.path.join(base_dir, rel_path.replace("/", os.sep))
                    if os.path.exists(abs_path) and abs_path not in context_images:
                        context_images.append(abs_path)
            
            # Style Consistency
            meta_style = item.data.get("meta_info", {}).get("style", "")
            if not meta_style and project.global_config:
                meta_style = project.global_config.data.get("style", "")
                
            if meta_style:
                 json_prompt += f"\n\nStyle Consistency Requirement: {meta_style}. Ensure the visual style matches the provided context images."
        
            log_task_event(session, task_id, f"Calling AI service for panel {item.sequence}...")
            image_bytes = ai.generate_image(
                json_prompt,  
                context_images=context_images,
                aspect_ratio=project.aspect_ratio or "16:9",
                resolution=project.resolution or "2K"
            )
            
            relative_url = save_generated_image(session, project.id, "panel", item.id, image_bytes)
            item.image_url = relative_url
            session.add(item)
            
            task.status = "completed"
            task.progress = 100
            session.add(task)
            session.commit()
            log_task_event(session, task_id, f"Panel task {task_id} completed successfully.")
            
        except Exception as e:
            logger.error(f"Panel task {task_id} failed: {e}")
            log_task_event(session, task_id, f"Panel task {task_id} failed: {e}")
            traceback.print_exc()
            task.status = "failed"
            task.message = str(e)
            session.add(task)
            session.commit()

@router.post("/panel/{item_id}")
def generate_panel(
    item_id: int, 
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session)
):
    item = session.get(StoryboardItem, item_id)
    if not item:
         raise HTTPException(status_code=404, detail="Storyboard item not found")
         
    task = Task(
        type="image_generation", 
        status="pending", 
        project_id=item.project_id,
        name=f"Draw Panel: #{item.sequence}",
        description=f"Drawing panel {item.sequence}"
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    
    background_tasks.add_task(generate_panel_task, task.id, item_id)
    
    return {"task_id": task.id}
