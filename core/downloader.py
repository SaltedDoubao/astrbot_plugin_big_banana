import asyncio
import base64
from io import BytesIO

from curl_cffi import AsyncSession
from curl_cffi.requests.exceptions import (
    CertificateVerifyError,
    SSLError,
    Timeout,
)
from PIL import Image

from astrbot.api import logger

from .data import CommonConfig

DEFAULT_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "image/*,*/*;q=0.8",
    "Accept-Encoding": "identity",
}


class Downloader:
    def __init__(self, session: AsyncSession, common_config: CommonConfig):
        self.session = session
        self.def_common_config = common_config

    async def fetch_image(
        self,
        url: str,
        headers: dict | None = None,
        impersonate: str | None = None,
    ) -> tuple[str, str] | None:
        """下载单张图片并转换为 (mime, base64)"""
        # 重试逻辑
        for _ in range(3):
            content, success = await self._download_image(
                url, headers=headers, impersonate=impersonate
            )
            if content is not None:
                return content
            if content is None and success:
                return None

    async def fetch_images(
        self,
        image_urls: list[str],
        headers: dict | None = None,
        impersonate: str | None = None,
    ) -> list[tuple[str, str]]:
        """下载多张图片并转换为 (mime, base64) 列表"""
        image_b64_list = []
        for url in image_urls:
            # 重试逻辑
            for _ in range(3):
                content, success = await self._download_image(
                    url, headers=headers, impersonate=impersonate
                )
                if content is not None:
                    image_b64_list.append(content)
                    break  # 成功就跳出重试
                if content is None and success:
                    break  # 图片处理失败但下载成功，不再重试
        return image_b64_list

    @staticmethod
    def _handle_image(image_bytes: bytes) -> tuple[str, str] | None:
        """ 尝试把图片统一转换成 jpeg 格式, 返回 (mime, base64) """
        try:
            with Image.open(BytesIO(image_bytes)) as img:
                if getattr(img, "is_animated", False):
                    img.seek(0)
                img = img.convert("RGB")
                buf = BytesIO()
                img.save(buf, format="JPEG", quality=100)
                b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                return ("image/jpeg", b64)
        except Exception as e:
            logger.warning(f"[BIG BANANA] 图片处理失败: {e}")
            return None

    async def _download_image(
        self,
        url: str,
        headers: dict | None = None,
        impersonate: str | None = None,
    ) -> tuple[tuple[str, str] | None, bool]:
        """ 下载图片并返回 (mime, base64) 和是否下载成功的标志"""
        request_kwargs: dict = {
            "proxy": self.def_common_config.proxy,
            "timeout": 30,
        }
        if headers:
            request_kwargs["headers"] = headers
        if impersonate:
            request_kwargs["impersonate"] = impersonate
        try:
            response = await self.session.get(url, **request_kwargs)
            if response.status_code != 200:
                logger.warning(
                    f"[BIG BANANA] 图片下载失败，状态码: {response.status_code}，URL: {url}"
                )
                return None, False
            if not response.content or len(response.content) > 50 * 1024 * 1024:
                logger.warning("[BIG BANANA] 图片超过 50MB，跳过处理")
                return None, True
            content = await asyncio.to_thread(Downloader._handle_image, response.content)
            return content, True
        except (SSLError, CertificateVerifyError):
            # 关闭SSL验证
            ssl_kwargs = {**request_kwargs, "verify": False}
            response = await self.session.get(url, **ssl_kwargs)
            if response.status_code != 200:
                logger.warning(
                    f"[BIG BANANA] 图片下载失败，状态码: {response.status_code}，URL: {url}"
                )
                return None, False
            if not response.content or len(response.content) > 50 * 1024 * 1024:
                logger.warning("[BIG BANANA] 图片超过 50MB，跳过处理")
                return None, True
            content = await asyncio.to_thread(Downloader._handle_image, response.content)
            return content, True
        except Timeout as e:
            logger.error(f"[BIG BANANA] 网络请求超时: {url}，错误信息：{e}")
            return None, False
        except Exception as e:
            logger.error(f"[BIG BANANA] 下载图片失败: {url}，错误信息：{e}")
            return None, False
