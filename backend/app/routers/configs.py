import time
from typing import List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.core.database import get_session
from app.models.models import ModelConfig
from app.schemas.schemas import ModelConfigCreate, ModelConfigUpdate
from app.cruds import crud_config

router = APIRouter()

GOOGLE_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
FETCH_MODELS_TIMEOUT = 30
TEST_TIMEOUT = 60


class ProviderConnectionInput(BaseModel):
    provider: str
    api_key: str
    base_url: Optional[str] = None


class TestConfigInput(ProviderConnectionInput):
    model_name: str
    model_type: str = "text"


def _candidate_model_urls(base_url: str) -> List[str]:
    base = (base_url or "").rstrip("/")
    if not base:
        return []
    if base.endswith("/v1"):
        return [f"{base}/models"]
    return [f"{base}/v1/models", f"{base}/models"]


def _fetch_models_openai_compatible(base_url: str, api_key: str) -> List[dict]:
    errors = []
    for url in _candidate_model_urls(base_url):
        try:
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
                timeout=FETCH_MODELS_TIMEOUT,
            )
            if not response.ok:
                errors.append(f"{url}: HTTP {response.status_code}")
                continue
            data = response.json()
            items = data.get("data") if isinstance(data, dict) else None
            if not isinstance(items, list):
                errors.append(f"{url}: unexpected response shape")
                continue
            models = []
            for item in items:
                if isinstance(item, dict) and item.get("id"):
                    models.append({"id": str(item["id"]), "owned_by": item.get("owned_by")})
            return models
        except requests.RequestException as exc:
            errors.append(f"{url}: {exc}")
        except ValueError:
            errors.append(f"{url}: invalid JSON")
    raise HTTPException(status_code=502, detail="拉取模型失败: " + "; ".join(errors))


def _fetch_models_google(api_key: str) -> List[dict]:
    try:
        response = requests.get(
            f"{GOOGLE_API_BASE}/models",
            headers={"x-goog-api-key": api_key},
            params={"pageSize": 1000},
            timeout=FETCH_MODELS_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"拉取模型失败: {exc}")
    if not response.ok:
        detail = ""
        try:
            detail = response.json().get("error", {}).get("message", "")
        except ValueError:
            pass
        raise HTTPException(status_code=502, detail=f"拉取模型失败: HTTP {response.status_code} {detail}")
    models = []
    for item in response.json().get("models", []):
        name = item.get("name", "")
        model_id = name.removeprefix("models/")
        if model_id:
            models.append({
                "id": model_id,
                "display_name": item.get("displayName"),
                "methods": item.get("supportedGenerationMethods", []),
            })
    return models


@router.post("/fetch-models")
def fetch_models(payload: ProviderConnectionInput):
    """服务端代理拉取上游模型列表（绕过浏览器 CORS / 混合内容限制）。"""
    provider = payload.provider.lower().replace("-", "_")
    if provider == "google":
        models = _fetch_models_google(payload.api_key)
    elif provider == "openai_compatible":
        if not payload.base_url:
            raise HTTPException(status_code=400, detail="openai_compatible 需要填写 Base URL")
        models = _fetch_models_openai_compatible(payload.base_url, payload.api_key)
    else:
        raise HTTPException(status_code=400, detail=f"不支持的供应商: {payload.provider}")
    return {"models": models}


def _test_google(payload: TestConfigInput) -> str:
    if payload.model_type == "text":
        try:
            from google import genai

            client = genai.Client(api_key=payload.api_key)
            result = client.models.generate_content(model=payload.model_name, contents="ping")
            preview = (result.text or "").strip()[:50]
            return f"文本模型响应正常{f'：{preview}' if preview else ''}"
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"测试失败: {exc}")
    # 图片模型不真实生成（避免花费），验证 key 有效且模型存在
    models = _fetch_models_google(payload.api_key)
    if any(m["id"] == payload.model_name for m in models):
        return "API Key 有效，模型存在（图片模型不做真实生成测试）"
    raise HTTPException(status_code=502, detail=f"API Key 有效，但模型列表中未找到 {payload.model_name}")


def _test_openai_compatible(payload: TestConfigInput) -> str:
    if not payload.base_url:
        raise HTTPException(status_code=400, detail="openai_compatible 需要填写 Base URL")
    if payload.model_type == "text":
        base = payload.base_url.rstrip("/")
        urls = [f"{base}/chat/completions"] if base.endswith("/v1") else [f"{base}/v1/chat/completions", f"{base}/chat/completions"]
        errors = []
        for url in urls:
            try:
                response = requests.post(
                    url,
                    headers={"Authorization": f"Bearer {payload.api_key}", "Content-Type": "application/json"},
                    json={
                        "model": payload.model_name,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 8,
                    },
                    timeout=TEST_TIMEOUT,
                )
                data = {}
                try:
                    data = response.json()
                except ValueError:
                    pass
                if response.ok:
                    return "文本模型响应正常"
                message = ""
                if isinstance(data, dict):
                    error = data.get("error")
                    if isinstance(error, dict):
                        message = error.get("message", "")
                    elif isinstance(error, str):
                        message = error
                errors.append(f"{url}: HTTP {response.status_code} {message}".strip())
            except requests.RequestException as exc:
                errors.append(f"{url}: {exc}")
        raise HTTPException(status_code=502, detail="测试失败: " + "; ".join(errors))
    # 图片 / 图片编辑：验证 key 与模型存在即可，不做真实生成
    models = _fetch_models_openai_compatible(payload.base_url, payload.api_key)
    kind = "图片编辑" if payload.model_type == "image_edit" else "图片"
    if any(m["id"] == payload.model_name for m in models):
        return f"API Key 有效，模型存在（{kind}模型不做真实生成测试）"
    return "API Key 有效（上游模型列表未包含该模型，可能仍可用）"


@router.post("/test")
def test_config(payload: TestConfigInput):
    """保存前测试连通性：文本模型发送最小 ping 请求，图片/图片编辑校验 key 与模型存在。"""
    provider = payload.provider.lower().replace("-", "_")
    start = time.monotonic()
    if provider == "google":
        message = _test_google(payload)
    elif provider == "openai_compatible":
        message = _test_openai_compatible(payload)
    else:
        raise HTTPException(status_code=400, detail=f"不支持的供应商: {payload.provider}")
    latency_ms = int((time.monotonic() - start) * 1000)
    return {"ok": True, "latency_ms": latency_ms, "message": message}

@router.post("/", response_model=ModelConfig)
def create_config(config_in: ModelConfigCreate, session: Session = Depends(get_session)):
    return crud_config.create_model_config(session, config_in)

@router.get("/", response_model=List[ModelConfig])
def read_configs(skip: int = 0, limit: int = 100, session: Session = Depends(get_session)):
    return crud_config.get_model_configs(session, skip, limit)

@router.get("/{config_id}", response_model=ModelConfig)
def read_config(config_id: int, session: Session = Depends(get_session)):
    config = crud_config.get_model_config(session, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    return config

@router.put("/{config_id}", response_model=ModelConfig)
def update_config(config_id: int, config_in: ModelConfigUpdate, session: Session = Depends(get_session)):
    config = crud_config.get_model_config(session, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    return crud_config.update_model_config(session, config, config_in)

@router.post("/{config_id}/set-default", response_model=ModelConfig)
def set_default_config(config_id: int, session: Session = Depends(get_session)):
    """将指定配置设为同类型默认（自动启用，并取消同类型其它默认）。"""
    try:
        return crud_config.set_default_config(session, config_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{config_id}")
def delete_config(config_id: int, session: Session = Depends(get_session)):
    config = crud_config.get_model_config(session, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    crud_config.delete_model_config(session, config)
    return {"ok": True}
