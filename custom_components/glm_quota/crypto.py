"""API Key 的 Fernet 加解密与主密钥管理。

存储形态：
- 主密钥：独立 .storage 文件 ``glm_quota_master_key``，首次使用时生成
- config entry data[api_key]：Fernet 密文（.storage/core.config_entries 中不落明文）

并发与一致性设计：
- 模块级 asyncio.Lock 串行化 load-or-create，并发首次初始化只有一个生成者，
  后到者必然从盘上读到先到者写入的同一把主密钥——杜绝双主密钥竞态
- 刻意不做进程内缓存：每次调用都从 .storage 取当前主密钥。若缓存，用户
  手动删主密钥文件后重录（不重启 HA）会用内存旧钥加密，跨重启后文件
  重建为新钥、密文作废，需二次 reauth 才收敛；调用点仅在 setup 与
  config flow，每次多一次 Store 读不值一顾
- 主密钥文件形状异常或 key 非法（Fernet 构造抛 ValueError，已实测）一律
  记 warning 后重建：旧密文解密必然 InvalidToken，async_setup_entry 捕获
  后抛 ConfigEntryAuthFailed 走 reauth——全程无静默回落
"""

from __future__ import annotations

import asyncio
import logging

from cryptography.fernet import Fernet
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

_MASTER_STORE_KEY = "glm_quota_master_key"
_STORE_VERSION = 1

# 进程内互斥；HA 主进程单实例，无跨进程共享面
_lock = asyncio.Lock()


async def async_get_fernet(hass: HomeAssistant) -> Fernet:
    """从 .storage 加载（或首次生成）主密钥并返回 Fernet 实例。"""
    async with _lock:
        return await _async_load_or_create(hass)


async def _async_load_or_create(hass: HomeAssistant) -> Fernet:
    """加载主密钥；缺失或损坏时重建并留下 warning。"""
    store = Store(hass, _STORE_VERSION, _MASTER_STORE_KEY)
    data = await store.async_load()
    if isinstance(data, dict) and isinstance(data.get("key"), str):
        try:
            return Fernet(data["key"].encode("ascii"))
        except ValueError:
            _LOGGER.warning(
                "主密钥文件损坏（key 非法），已重建；已存密文无法解密，"
                "相关条目需重新认证"
            )
    elif data is not None:
        _LOGGER.warning(
            "主密钥文件形状异常，已重建；已存密文无法解密，相关条目需重新认证"
        )
    key = Fernet.generate_key()
    await store.async_save({"key": key.decode("ascii")})
    return Fernet(key)


def encrypt_key(fernet: Fernet, plaintext: str) -> str:
    """加密 API Key，返回可入库的密文字符串。"""
    return fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_key(fernet: Fernet, ciphertext: str) -> str:
    """解密 API Key；主密钥不匹配时抛 cryptography.fernet.InvalidToken。"""
    return fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
