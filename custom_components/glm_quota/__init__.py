"""The GLM Coding Plan quota integration."""

from __future__ import annotations

import logging

from cryptography.fernet import InvalidToken
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed

from .const import (
    CONF_API_KEY,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .coordinator import GlmQuotaCoordinator
from .crypto import async_get_fernet, decrypt_key

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up GLM Coding Plan quota from a config entry."""
    fernet = await async_get_fernet(hass)
    try:
        ciphertext = entry.data[CONF_API_KEY]
        if not isinstance(ciphertext, str):
            raise TypeError(f"密文类型异常: {type(ciphertext).__name__}")
        api_key = decrypt_key(fernet, ciphertext)
    except (InvalidToken, KeyError, ValueError, TypeError) as err:
        # 主密钥文件被删/重建/损坏或 entry 数据畸形：必须重认证，不做静默回落
        # （UnicodeEncodeError ⊂ ValueError；InvalidToken 为 cryptography 异常）
        _LOGGER.error("API key 解密失败，请重新认证: %s", err)
        raise ConfigEntryAuthFailed("API key 解密失败，请重新认证") from err

    try:
        scan_interval = int(
            entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
    except (TypeError, ValueError):
        _LOGGER.warning(
            "scan_interval 配置非法（%r），回落默认 %d 秒",
            entry.options.get(CONF_SCAN_INTERVAL),
            DEFAULT_SCAN_INTERVAL,
        )
        scan_interval = DEFAULT_SCAN_INTERVAL
    if not MIN_SCAN_INTERVAL <= scan_interval <= MAX_SCAN_INTERVAL:
        # 应用内流程不会产生越界值；手工改 .storage 直改才会走到这里
        _LOGGER.warning(
            "scan_interval 超出允许范围（%d），钳制到 %d~%d 秒",
            scan_interval,
            MIN_SCAN_INTERVAL,
            MAX_SCAN_INTERVAL,
        )
        scan_interval = max(MIN_SCAN_INTERVAL, min(MAX_SCAN_INTERVAL, scan_interval))
    coordinator = GlmQuotaCoordinator(hass, entry, api_key, scan_interval)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry so option changes take effect."""
    await hass.config_entries.async_reload(entry.entry_id)
