import base64
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ai_service import AIService


class DummyResponse:
    def __init__(self, data, ok=True, status_code=200, text="", content=b"", headers=None):
        self._data = data
        self.ok = ok
        self.status_code = status_code
        self.text = text
        self.content = content
        self.headers = headers or {}

    def json(self):
        return self._data


class OpenAICompatibleAIServiceTest(unittest.TestCase):
    def make_config(self, model_type="text"):
        return SimpleNamespace(
            provider="openai_compatible",
            api_key="sk-test",
            base_url="https://example.com/v1",
            model_name="test-model",
            model_type=model_type,
        )

    def make_service(self, config):
        service = AIService(session=None)
        service._get_config = Mock(return_value=config)
        return service

    def test_generate_storyboard_openai_compatible_uses_chat_completions(self):
        config = self.make_config("text")
        service = self.make_service(config)
        calls = []

        def fake_post(url, headers, json, timeout):
            calls.append((url, headers, json, timeout))
            return DummyResponse({"choices": [{"message": {"content": "{\"type\": \"storyboard\"}"}}]})

        with patch("app.services.ai_service.requests.post", fake_post):
            result = service.generate_storyboard("system prompt", "user story")

        self.assertEqual(result, '{"type": "storyboard"}')
        self.assertEqual(calls[0][0], "https://example.com/v1/chat/completions")
        self.assertEqual(calls[0][1]["Authorization"], "Bearer sk-test")
        self.assertEqual(calls[0][2]["model"], "test-model")
        self.assertEqual(calls[0][2]["messages"][0], {"role": "system", "content": "system prompt"})
        self.assertIn("user story", calls[0][2]["messages"][1]["content"])

    def test_generate_text_openai_compatible_does_not_add_storyboard_instruction(self):
        config = self.make_config("text")
        service = self.make_service(config)
        calls = []

        def fake_post(url, headers, json, timeout):
            calls.append((url, headers, json, timeout))
            return DummyResponse({"choices": [{"message": {"content": "通用文本结果"}}]})

        with patch("app.services.ai_service.requests.post", fake_post):
            result = service.generate_text("system prompt", "用户输入")

        self.assertEqual(result, "通用文本结果")
        self.assertEqual(calls[0][2]["messages"][1]["content"], "用户输入")
        self.assertNotIn("storyboard", calls[0][2]["messages"][1]["content"])

    def test_generate_chapter_content_uses_shared_text_generation(self):
        config = self.make_config("text")
        service = self.make_service(config)
        calls = []

        def fake_post(url, headers, json, timeout):
            calls.append((url, headers, json, timeout))
            return DummyResponse({"choices": [{"message": {"content": "章节正文内容"}}]})

        with patch("app.services.ai_service.requests.post", fake_post):
            result = service.generate_chapter_content("上下文提示", "补充要求")

        self.assertEqual(result, "章节正文内容")
        self.assertEqual(calls[0][0], "https://example.com/v1/chat/completions")
        self.assertIn("专业长篇小说与漫画脚本创作助手", calls[0][2]["messages"][0]["content"])
        self.assertIn("上下文提示", calls[0][2]["messages"][1]["content"])
        self.assertIn("补充要求", calls[0][2]["messages"][1]["content"])
        self.assertNotIn("storyboard", calls[0][2]["messages"][1]["content"])

    def test_generate_text_stream_accumulates_deltas_and_calls_on_delta(self):
        config = self.make_config("text")
        service = self.make_service(config)
        deltas = []

        class DummyStreamResponse:
            ok = True
            status_code = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def iter_lines(self, decode_unicode=True):
                return iter([
                    'data: {"choices": [{"delta": {"content": "第一"}}]}',
                    '',
                    'data: {"choices": [{"delta": {"content": "段"}}]}',
                    'data: {"choices": [{"delta": {}}]}',
                    'data: [DONE]',
                ])

        def fake_post(url, headers, json, timeout, stream=False):
            self.assertTrue(stream)
            self.assertTrue(json["stream"])
            return DummyStreamResponse()

        with patch("app.services.ai_service.requests.post", fake_post):
            result = service.generate_text_stream("system", "input", on_delta=deltas.append)

        self.assertEqual(result, "第一段")
        self.assertEqual(deltas, ["第一", "第一段"])

    def test_generate_text_stream_falls_back_to_non_streaming_on_failure(self):
        config = self.make_config("text")
        service = self.make_service(config)

        def fake_post(url, headers, json, timeout, stream=False):
            if stream or json.get("stream"):
                raise __import__("requests").RequestException("stream broken")
            return DummyResponse({"choices": [{"message": {"content": "非流式结果"}}]})

        deltas = []
        with patch("app.services.ai_service.requests.post", fake_post):
            result = service.generate_text_stream("system", "input", on_delta=deltas.append)

        self.assertEqual(result, "非流式结果")
        self.assertEqual(deltas, ["非流式结果"])

    def test_generate_text_stream_callback_exception_propagates(self):
        config = self.make_config("text")
        service = self.make_service(config)

        class CancelSignal(Exception):
            pass

        class DummyStreamResponse:
            ok = True
            status_code = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def iter_lines(self, decode_unicode=True):
                return iter(['data: {"choices": [{"delta": {"content": "开始"}}]}'])

        def fake_post(url, headers, json, timeout, stream=False):
            return DummyStreamResponse()

        def raise_cancel(text):
            raise CancelSignal("cancelled")

        with patch("app.services.ai_service.requests.post", fake_post):
            with self.assertRaises(CancelSignal):
                service.generate_text_stream("system", "input", on_delta=raise_cancel)

    def test_generate_image_openai_compatible_decodes_b64_json(self):
        config = self.make_config("image")
        service = self.make_service(config)
        image_bytes = b"fake png bytes"

        def fake_post(url, headers, json, timeout):
            self.assertEqual(url, "https://example.com/v1/images/generations")
            self.assertEqual(json["size"], "1536x1024")
            return DummyResponse({"data": [{"b64_json": base64.b64encode(image_bytes).decode()}]})

        with patch("app.services.ai_service.requests.post", fake_post):
            result = service.generate_image("draw cat", aspect_ratio="16:9", resolution="2K")

        self.assertEqual(result, image_bytes)

    def test_generate_image_openai_compatible_downloads_url(self):
        config = self.make_config("image")
        service = self.make_service(config)
        image_bytes = b"downloaded png"

        def fake_post(url, headers, json, timeout):
            return DummyResponse({"data": [{"url": "https://cdn.example.com/image.png"}]})

        def fake_get(url, timeout):
            self.assertEqual(url, "https://cdn.example.com/image.png")
            return DummyResponse({}, content=image_bytes, headers={"content-type": "image/png"})

        with patch("app.services.ai_service.requests.post", fake_post), patch("app.services.ai_service.requests.get", fake_get):
            result = service.generate_image("draw cat", aspect_ratio="1:1", resolution="2K")

        self.assertEqual(result, image_bytes)

    def test_openai_compatible_retries_with_v1_when_base_url_has_no_v1(self):
        config = self.make_config("image")
        config.base_url = "https://example.com"
        service = self.make_service(config)
        calls = []
        image_bytes = b"fake image"

        def fake_post(url, headers, json, timeout):
            calls.append(url)
            if url == "https://example.com/images/generations":
                return DummyResponse({"error": {"message": "not found"}}, ok=False, status_code=404)
            return DummyResponse({"data": [{"b64_json": base64.b64encode(image_bytes).decode()}]})

        with patch("app.services.ai_service.requests.post", fake_post):
            result = service.generate_image("draw cat")

        self.assertEqual(result, image_bytes)
        self.assertEqual(calls, ["https://example.com/images/generations", "https://example.com/v1/images/generations"])

    def test_openai_compatible_image_error_is_readable(self):
        config = self.make_config("image")
        service = self.make_service(config)

        def fake_post(url, headers, json, timeout):
            return DummyResponse({"error": {"message": "bad api key"}}, ok=False, status_code=401)

        with patch("app.services.ai_service.requests.post", fake_post):
            with self.assertRaisesRegex(ValueError, "bad api key"):
                service.generate_image("draw cat")


if __name__ == "__main__":
    unittest.main()
