import base64
import json
import logging
import os
import time
from typing import TYPE_CHECKING, Callable, List, Optional
from urllib.parse import urlparse

import requests

if TYPE_CHECKING:
    from sqlmodel import Session

logger = logging.getLogger(__name__)


class _StreamCallbackError(Exception):
    """包装 on_delta 回调抛出的异常（如任务取消），避免被回退逻辑吞掉。"""

    def __init__(self, original: Exception):
        super().__init__(str(original))
        self.original = original


class AIService:
    def __init__(self, session: "Session"):
        self.session = session

    def generate_text(self, system_prompt: str, user_input: str) -> str:
        config = self._get_config("text")
        provider = self._provider_name(config)

        if provider == "openai_compatible":
            return self._generate_text_openai_compatible(config, system_prompt, user_input)
        if provider == "google":
            return self._generate_text_google(system_prompt, user_input)

        raise NotImplementedError(f"Provider {config.provider} not supported yet.")

    def chat_completion(
        self,
        messages: list[dict],
        *,
        tools: Optional[List[dict]] = None,
        tool_choice: str | dict | None = "auto",
        temperature: float = 0.7,
    ) -> dict:
        """OpenAI-compatible chat completions with optional tools.

        Returns a normalized message dict:
        {"role": "assistant", "content": str|None, "tool_calls": list|None}
        """
        config = self._get_config("text")
        provider = self._provider_name(config)
        if provider != "openai_compatible":
            # Fallback: collapse messages into single-shot text without tools.
            system_parts = [m.get("content") or "" for m in messages if m.get("role") == "system"]
            user_parts = []
            for m in messages:
                if m.get("role") == "system":
                    continue
                role = m.get("role") or "user"
                content = m.get("content") or ""
                if content:
                    user_parts.append(f"[{role}] {content}")
            text = self.generate_text("\n\n".join(system_parts) or "You are a helpful assistant.", "\n".join(user_parts))
            return {"role": "assistant", "content": text, "tool_calls": None}

        payload: dict = {
            "model": config.model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice

        data = self._post_openai_compatible(config, "/chat/completions", payload, timeout=300)
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("OpenAI-compatible chat response missing choices[0].message") from exc

        content = message.get("content")
        tool_calls = message.get("tool_calls") or None
        if isinstance(content, list):
            # Some gateways return content parts
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part) for part in content
            )
        return {
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls if tool_calls else None,
        }

    def generate_text_stream(
        self,
        system_prompt: str,
        user_input: str,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> str:
        """流式生成文本。on_delta 每次收到新 token 时以累计全文回调。

        仅 openai_compatible 支持真流式；其他 provider 或流式请求失败（且未收到任何内容）
        时自动回退到非流式请求。on_delta 抛出的异常（如任务取消）会向上传播并中断请求。
        """
        config = self._get_config("text")
        provider = self._provider_name(config)

        if provider != "openai_compatible":
            content = self.generate_text(system_prompt, user_input)
            if on_delta and content:
                on_delta(content)
            return content

        try:
            return self._generate_text_stream_openai_compatible(config, system_prompt, user_input, on_delta)
        except _StreamCallbackError as exc:
            raise exc.original
        except Exception as exc:
            logger.warning(f"Streaming request failed, falling back to non-streaming: {exc}")
            content = self._generate_text_openai_compatible(config, system_prompt, user_input)
            if on_delta and content:
                on_delta(content)
            return content

    def _generate_text_stream_openai_compatible(
        self,
        config,
        system_prompt: str,
        user_input: str,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> str:
        payload = {
            "model": config.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            "temperature": 0.7,
            "stream": True,
        }

        errors = []
        for url in self._openai_compatible_urls(config.base_url, "/chat/completions"):
            chunks: list[str] = []
            try:
                with requests.post(
                    url,
                    headers=self._headers(config.api_key),
                    json=payload,
                    timeout=(30, 300),
                    stream=True,
                ) as response:
                    if not response.ok:
                        try:
                            data = response.json()
                        except ValueError:
                            data = {"raw": response.text}
                        errors.append(f"{url}: {self._pick_error(data, f'HTTP {response.status_code}')}")
                        continue

                    # SSE 规范强制 UTF-8；若上游未声明 charset，requests 会按
                    # Latin-1 解码导致中文乱码，这里显式指定。
                    response.encoding = "utf-8"

                    for raw_line in response.iter_lines(decode_unicode=True):
                        if not raw_line or not raw_line.startswith("data:"):
                            continue
                        data_str = raw_line[len("data:"):].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        try:
                            delta = chunk["choices"][0].get("delta") or {}
                        except (KeyError, IndexError, TypeError):
                            continue
                        piece = delta.get("content")
                        if piece:
                            chunks.append(piece)
                            if on_delta:
                                try:
                                    on_delta("".join(chunks))
                                except Exception as callback_exc:
                                    raise _StreamCallbackError(callback_exc) from callback_exc

                content = "".join(chunks)
                if content:
                    return content
                errors.append(f"{url}: stream returned no content")
            except _StreamCallbackError:
                raise
            except requests.RequestException as exc:
                if chunks:
                    # 已收到部分内容但连接中断，视为失败让上层回退非流式，避免存半截正文
                    logger.warning(f"Stream interrupted after {len(chunks)} chunks: {exc}")
                errors.append(f"{url}: {exc}")

        raise ValueError("OpenAI-compatible stream request failed: " + "; ".join(errors))

    def _get_config(self, model_type: str):
        from app.cruds.crud_config import get_active_config

        config = get_active_config(self.session, model_type)
        if not config:
            raise ValueError(f"No active configuration found for {model_type} model.")
        return config

    def _get_google_client(self, model_type: str):
        from google import genai

        config = self._get_config(model_type)
        if config.provider.lower() != "google":
            raise NotImplementedError(f"Provider {config.provider} not supported by Google client.")
        return genai.Client(api_key=config.api_key), config.model_name

    def _provider_name(self, config) -> str:
        return config.provider.lower().replace("-", "_")

    def _openai_compatible_urls(self, base_url: str, path: str) -> List[str]:
        if not base_url:
            raise ValueError("Base URL is required for openai_compatible provider.")

        base = base_url.rstrip("/")
        urls = [f"{base}{path}"]
        if not base.endswith("/v1"):
            urls.append(f"{base}/v1{path}")
        return urls

    def _headers(self, api_key: str) -> dict:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _pick_error(self, data, fallback: str) -> str:
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, str):
                return error
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                return error["message"]
            if isinstance(data.get("message"), str):
                return data["message"]
        return fallback

    def _post_openai_compatible(self, config, path: str, payload: dict, timeout: int = 300):
        errors = []
        for url in self._openai_compatible_urls(config.base_url, path):
            try:
                response = requests.post(
                    url,
                    headers=self._headers(config.api_key),
                    json=payload,
                    timeout=timeout,
                )
                try:
                    data = response.json()
                except ValueError:
                    data = {"raw": response.text}

                if response.ok:
                    return data

                message = self._pick_error(data, f"HTTP {response.status_code}")
                errors.append(f"{url}: {message}")
            except requests.RequestException as exc:
                errors.append(f"{url}: {exc}")

        raise ValueError("OpenAI-compatible request failed: " + "; ".join(errors))

    def _post_openai_compatible_with_fallbacks(self, config, path: str, payloads: List[dict], timeout: int = 300):
        errors = []
        for payload in payloads:
            try:
                return self._post_openai_compatible(config, path, payload, timeout)
            except ValueError as exc:
                errors.append(str(exc))
        raise ValueError("OpenAI-compatible request failed: " + "; ".join(errors))

    def _size_from_ratio(self, aspect_ratio: str, resolution: str) -> str:
        ratio = (aspect_ratio or "").strip()
        if ratio in ["1:1", "1/1"]:
            return "1024x1024"
        if ratio in ["9:16", "9/16"]:
            return "1024x1536"
        if ratio in ["16:9", "16/9"]:
            return "1536x1024"
        if ratio in ["4:3", "4/3"]:
            return "1024x768"
        if ratio in ["3:4", "3/4"]:
            return "768x1024"
        return "1024x1024"

    def _is_private_hostname(self, hostname: str) -> bool:
        host = hostname.strip("[]").lower()
        if host in ["localhost", "127.0.0.1", "0.0.0.0", "::1"]:
            return True
        if host.startswith(("10.", "192.168.", "169.254.", "fe80:", "fc00:", "fd")):
            return True
        if host.startswith("172."):
            parts = host.split(".")
            if len(parts) > 1 and parts[1].isdigit() and 16 <= int(parts[1]) <= 31:
                return True
        return False

    def _download_image(self, image_url: str) -> bytes:
        parsed = urlparse(image_url)
        if parsed.scheme not in ["http", "https"]:
            raise ValueError(f"Unsupported image URL protocol: {parsed.scheme}")
        if self._is_private_hostname(parsed.hostname or ""):
            raise ValueError("Refusing to download image from private address.")

        response = requests.get(image_url, timeout=60)
        if not response.ok:
            raise ValueError(f"Failed to download generated image: HTTP {response.status_code}")
        content_type = response.headers.get("content-type", "")
        if content_type and not content_type.startswith("image/"):
            raise ValueError(f"Generated image URL did not return an image: {content_type}")
        return response.content

    def generate_storyboard(self, system_prompt: str, user_input: str) -> str:
        return self.generate_text(
            system_prompt,
            f"{user_input}\n\nPlease generate the full storyboard in JSON format as requested.",
        )

    def generate_chapter_content(
        self,
        context_prompt: str,
        user_input: str = "",
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> str:
        system_prompt = "你是专业长篇小说与漫画脚本创作助手。请生成结构清晰、可用于漫画改编的章节正文。"
        full_input = f"""
{context_prompt}

【用户补充要求】
{user_input or '无'}

请输出当前章节正文，要求：
1. 如果上下文包含【原文章节上下文】，必须以原文章节正文为主要依据，不要偏离原文事件顺序。
2. 保持人物关系一致。
3. 保持当前状态一致。
4. 不违反世界设定。
5. 章节结尾留下可继续推进的钩子。
""".strip()
        if on_delta is not None:
            return self.generate_text_stream(system_prompt, full_input, on_delta)
        return self.generate_text(system_prompt, full_input)

    def _generate_text_google(self, system_prompt: str, user_input: str) -> str:
        client, model_name = self._get_google_client("text")
        full_prompt = f"{system_prompt}\n\nUser Input: {user_input}"

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=full_prompt,
                )
                return response.text
            except Exception as e:
                logger.error(f"Error generating text (Attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise e

    def _generate_text_openai_compatible(self, config, system_prompt: str, user_input: str) -> str:
        payload = {
            "model": config.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": user_input,
                },
            ],
            "temperature": 0.7,
        }

        data = self._post_openai_compatible(config, "/chat/completions", payload, timeout=300)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ValueError("OpenAI-compatible chat response missing choices[0].message.content")

        if not content:
            raise ValueError("OpenAI-compatible chat response was empty.")
        return content

    def generate_image(self, prompt: str, context_images: List[str] = None, aspect_ratio: str = "16:9", resolution: str = "2K") -> bytes:
        config = self._get_config("image")
        provider = self._provider_name(config)

        if provider == "openai_compatible":
            return self._generate_image_openai_compatible(config, prompt, aspect_ratio, resolution)
        if provider == "google":
            return self._generate_image_google(prompt, context_images, aspect_ratio, resolution)

        raise NotImplementedError(f"Provider {config.provider} not supported yet.")

    def _generate_image_openai_compatible(self, config, prompt: str, aspect_ratio: str, resolution: str) -> bytes:
        size = self._size_from_ratio(aspect_ratio, resolution)
        full_payload = {
            "model": config.model_name,
            "prompt": prompt,
            "n": 1,
            "size": size,
            "response_format": "b64_json",
        }
        minimal_payload = {
            "model": config.model_name,
            "prompt": prompt,
            "n": 1,
            "size": size,
        }

        data = self._post_openai_compatible_with_fallbacks(config, "/images/generations", [minimal_payload, full_payload], timeout=600)
        try:
            first_image = data["data"][0]
        except (KeyError, IndexError, TypeError):
            raise ValueError("OpenAI-compatible image response missing data[0].")

        b64_json = first_image.get("b64_json")
        if b64_json:
            return base64.b64decode(b64_json)

        image_url = first_image.get("url")
        if image_url:
            return self._download_image(image_url)

        raise ValueError("OpenAI-compatible image response missing b64_json or url.")

    def _generate_image_google(self, prompt: str, context_images: List[str] = None, aspect_ratio: str = "16:9", resolution: str = "2K") -> bytes:
        from google.genai import types
        from PIL import Image

        client, model_name = self._get_google_client("image")

        contents = [prompt]
        if context_images:
            for img_path in context_images:
                if os.path.exists(img_path):
                    try:
                        prev_img = Image.open(img_path)
                        contents.append(prev_img)
                    except Exception as e:
                        logger.warning(f"Failed to load context image {img_path}: {e}")
                else:
                    logger.warning(f"Warning: Context image not found at {img_path}, skipping.")

        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.info(f"Starting image generation attempt {attempt + 1}/{max_retries} with model {model_name}.")
                logger.info(f"Prompt length: {len(prompt)}")
                if context_images:
                    logger.info(f"Context images count: {len(context_images)}")

                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        image_config=types.ImageConfig(
                            aspect_ratio=aspect_ratio,
                            image_size=resolution,
                        ),
                    ),
                )

                if response.parts:
                    for part in response.parts:
                        if part.inline_data is not None:
                            image_data = part.inline_data.data
                            if len(image_data) > 0:
                                logger.info(f"Successfully received image data ({len(image_data)} bytes)")
                                return image_data
                            logger.warning(f"Warning: Received empty image data on attempt {attempt + 1}")

                if response.text:
                    logger.warning(f"Model response text (no image): {response.text}")

                logger.warning(f"Attempt {attempt + 1} failed: No valid image data found in response.")
                if attempt == max_retries - 1:
                    raise ValueError(f"No image found in response after {max_retries} retries. Last response: {response.text if response.text else 'Empty'}")

                time.sleep(2 ** attempt)

            except Exception as e:
                logger.error(f"Error generating image (Attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise e
        return b""
