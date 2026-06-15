import base64
import binascii
import mimetypes
import random
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image

from astrbot.api import logger

_BASE64_DATA_URI_RE = re.compile(r"^data:[^,]*;base64,", re.IGNORECASE)
_BASE64_WHITESPACE_RE = re.compile(r"\s+")


def get_key_index(current_index: int, item_len: int) -> int:
    """获取key索引"""
    return (current_index + 1) % item_len


def normalize_base64_data(b64: str) -> str:
    """清理并补齐 base64 图片数据，返回可供下游复用的标准字符串。"""
    if not isinstance(b64, str):
        raise ValueError("base64 数据必须是字符串")

    normalized = b64.strip()
    normalized = _BASE64_DATA_URI_RE.sub("", normalized, count=1)
    normalized = _BASE64_WHITESPACE_RE.sub("", normalized)
    normalized = normalized.translate(str.maketrans("-_", "+/"))

    if not normalized:
        raise ValueError("base64 数据为空")
    if len(normalized) % 4 == 1:
        raise ValueError("base64 数据长度无效")

    return normalized + ("=" * (-len(normalized) % 4))


def decode_base64_data(b64: str) -> bytes:
    """解码图片 base64 数据，兼容缺少 padding 和 URL-safe 变体。"""
    normalized = normalize_base64_data(b64)
    try:
        return base64.b64decode(normalized, validate=True)
    except binascii.Error:
        try:
            return base64.b64decode(
                normalized.translate(str.maketrans("-_", "+/")),
                validate=True,
            )
        except binascii.Error as urlsafe_error:
            raise ValueError("base64 数据格式无效") from urlsafe_error


def validate_image_bytes(image_bytes: bytes) -> None:
    """校验字节内容确实是 Pillow 可识别的图片。"""
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            img.verify()
    except Exception as e:
        raise ValueError("图片数据格式无效") from e


def normalize_image_results(
    image_result: list[tuple[str, str]] | None,
) -> tuple[list[tuple[str, str]], int]:
    """规范化 provider 返回的图片结果，返回有效图片和无效图片数量。"""
    valid_results: list[tuple[str, str]] = []
    invalid_result_count = 0
    for mime, b64 in image_result or []:
        if not b64:
            continue
        try:
            normalized_b64 = normalize_base64_data(b64)
            image_bytes = decode_base64_data(normalized_b64)
            validate_image_bytes(image_bytes)
        except ValueError as e:
            invalid_result_count += 1
            logger.warning(
                f"[BIG BANANA] 跳过无效图片结果，mime={mime}，base64长度={len(b64)}，错误信息：{e}"
            )
            continue
        valid_results.append((mime, normalized_b64))
    return valid_results, invalid_result_count


def save_images(image_result: list[tuple[str, str]], path_dir: Path) -> list[tuple[str, Path]]:
    """保存图片到本地文件系统，返回 元组(文件名, 文件路径) 列表"""
    # 假设它支持返回多张图片
    saved_paths: list[tuple[str, Path]] = []
    for mime, b64 in image_result:
        if not b64:
            continue
        # 构建文件名
        now = datetime.now()
        current_time_str = (
            now.strftime("%Y%m%d%H%M%S") + f"{int(now.microsecond / 1000):03d}"
        )
        ext = mimetypes.guess_extension(mime) or ".jpg"
        file_name = f"banana_{current_time_str}{ext}"
        # 构建文件保存路径
        save_path = path_dir / file_name
        # 转换成bytes
        try:
            image_bytes = decode_base64_data(b64)
        except ValueError as e:
            logger.warning(
                f"[BIG BANANA] 跳过无效图片数据，mime={mime}，base64长度={len(b64)}，错误信息：{e}"
            )
            continue
        # 保存到文件系统
        with open(save_path, "wb") as f:
            f.write(image_bytes)
        saved_paths.append((file_name, save_path))
        logger.info(f"[BIG BANANA] 图片已保存到 {save_path}")
    return saved_paths


def read_file(path) -> tuple[str | None, str | None]:
    try:
        with open(path, "rb") as f:
            file_data = f.read()
            mime_type, _ = mimetypes.guess_type(path)
            b64_data = base64.b64encode(file_data).decode("utf-8")
            return mime_type, b64_data
    except Exception as e:
        logger.error(f"[BIG BANANA] 读取参考图片 {path} 失败: {e}")
        return None, None


def clear_cache(temp_dir: Path):
    """清理缓存文件，应当在图片发送完成后调用"""
    if not temp_dir.exists():
        logger.warning(f"[BIG BANANA] 缓存目录 {temp_dir} 不存在")
        return
    for file in temp_dir.iterdir():
        try:
            if file.is_file():
                file.unlink()
                logger.debug(f"[BIG BANANA] 已删除缓存文件: {file}")
        except Exception as e:
            logger.error(f"[BIG BANANA] 删除缓存文件 {file} 失败: {e}")


def random_string(length: int) -> str:
    return "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(length))
