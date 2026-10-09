"""实体公共构件：设备信息。"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN


def device_info_for(entry: ConfigEntry) -> DeviceInfo:
    """设备信息：名称带 key 指纹后缀，多账号可区分。"""
    fingerprint = (entry.unique_id or "").removeprefix("glm_")
    name = f"GLM Coding Plan ({fingerprint})" if fingerprint else "GLM Coding Plan"
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=name,
        manufacturer="Zhipu AI",
        model="Coding Plan",
        entry_type=DeviceEntryType.SERVICE,
    )
