import json

from curl_cffi.requests.exceptions import Timeout

from astrbot.api import logger

from .base import BaseProvider
from .data import ProviderConfig


class OpenAIResponsesProvider(BaseProvider):
    """OpenAI 官方 Responses 图片生成提供商"""

    api_type: str = "OpenAI_Responses"

    async def _call_api(
        self,
        provider_config: ProviderConfig,
        api_key: str,
        image_b64_list: list[tuple[str, str]],
        params: dict,
    ) -> tuple[list[tuple[str, str]] | None, int | None, str | None]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        openai_context = self._build_openai_responses_context(
            provider_config.model, image_b64_list, params
        )
        try:
            response = await self.session.post(
                url=provider_config.api_url,
                headers=headers,
                json=openai_context,
                timeout=self.def_common_config.timeout,
                proxy=self.def_common_config.proxy,
            )
            result = response.json()
            if response.status_code == 200:
                b64_images, message = self._parse_openai_responses_output(result)
                if not b64_images:
                    logger.warning(
                        f"[BIG BANANA] OpenAI Responses 请求成功，但未返回图片数据, 响应内容: {response.text[:1024]}"
                    )
                    return None, 200, message or "响应中未包含图片数据"
                return b64_images, 200, None
            logger.error(
                f"[BIG BANANA] OpenAI Responses 图片生成失败，状态码: {response.status_code}, 响应内容: {response.text[:1024]}"
            )
            return (
                None,
                response.status_code,
                message_from_error(result) or f"图片生成失败: 状态码 {response.status_code}",
            )
        except Timeout as e:
            logger.error(f"[BIG BANANA] OpenAI Responses 网络请求超时: {e}")
            return None, 408, "图片生成失败：响应超时"
        except json.JSONDecodeError as e:
            logger.error(
                f"[BIG BANANA] OpenAI Responses JSON反序列化错误: {e}，状态码：{response.status_code}，响应内容：{response.text[:1024]}"
            )
            return None, response.status_code, "图片生成失败：响应内容格式错误"
        except Exception as e:
            logger.error(f"[BIG BANANA] OpenAI Responses 请求错误: {e}")
            return None, None, "图片生成失败：程序错误"

    async def _call_stream_api(
        self,
        provider_config: ProviderConfig,
        api_key: str,
        image_b64_list: list[tuple[str, str]],
        params: dict,
    ) -> tuple[list[tuple[str, str]] | None, int | None, str | None]:
        logger.warning(
            "[BIG BANANA] OpenAI_Responses 暂未实现流式图片输出，将自动回退为非流式请求"
        )
        return await self._call_api(
            provider_config=provider_config,
            api_key=api_key,
            image_b64_list=image_b64_list,
            params=params,
        )

    def _build_openai_responses_context(
        self,
        model: str,
        image_b64_list: list[tuple[str, str]],
        params: dict,
    ) -> dict:
        content = [{"type": "input_text", "text": params.get("prompt", "anything")}]
        for mime, b64 in image_b64_list:
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:{mime};base64,{b64}",
                }
            )
        return {
            "model": model,
            "input": [{"role": "user", "content": content}],
            "tools": [{"type": "image_generation"}],
            "tool_choice": {"type": "image_generation"},
        }

    @staticmethod
    def _parse_openai_responses_output(
        result: dict,
    ) -> tuple[list[tuple[str, str]], str | None]:
        b64_images: list[tuple[str, str]] = []
        text_parts: list[str] = []

        for item in result.get("output", []):
            if item.get("type") == "image_generation_call":
                image_b64 = item.get("result")
                if image_b64:
                    b64_images.append(("image/png", image_b64))
            elif item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text" and content.get("text"):
                        text_parts.append(content["text"])

        return b64_images, "\n".join(text_parts).strip() or None


def message_from_error(result: dict) -> str | None:
    error = result.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str):
            return message[:200]
    return None
