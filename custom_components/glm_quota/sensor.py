"""GLM Coding Plan 限额传感器：5 小时窗口与周限额，读数为已用百分比。"""

from __future__ import annotations

from typing import Any

import homeassistant.util.dt as dt_util
from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import entity
from .const import DOMAIN, FIVE_HOUR, WEEKLY
from .coordinator import GlmQuotaCoordinator
from .parse import WindowUsage

_ICONS = {FIVE_HOUR: "mdi:timer", WEEKLY: "mdi:calendar-week"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the two quota sensors from a config entry."""
    coordinator: GlmQuotaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GlmQuotaSensor(coordinator, entry, FIVE_HOUR),
            GlmQuotaSensor(coordinator, entry, WEEKLY),
        ]
    )


class GlmQuotaSensor(CoordinatorEntity[GlmQuotaCoordinator], SensorEntity):
    """单个限额窗口的已用百分比。"""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(
        self,
        coordinator: GlmQuotaCoordinator,
        entry: ConfigEntry,
        slot: str,
    ) -> None:
        """Initialize the sensor for one quota window slot."""
        super().__init__(coordinator)
        self._slot = slot
        self._attr_translation_key = slot
        self._attr_unique_id = f"glm_quota_{slot}_{entry.entry_id}"
        self._attr_icon = _ICONS[slot]
        self._attr_device_info = entity.device_info_for(entry)

    @property
    def _window(self) -> WindowUsage | None:
        """当前槽位的窗口数据；尚未轮询到时为 None。"""
        data = self.coordinator.data or {}
        return data.get(self._slot)

    @property
    def native_value(self) -> int | None:
        """已用百分比；窗口数据缺失时返回 None 以免污染统计。"""
        window = self._window
        return None if window is None else window.used_pct

    @property
    def available(self) -> bool:
        """最后一次刷新成功且本窗口有数据才可用。"""
        return super().available and self._window is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """窗口量值、重置时间与套餐信息。"""
        window = self._window
        if window is None:
            return None
        data = self.coordinator.data or {}
        remaining = window.remaining
        total = window.total
        attrs: dict[str, Any] = {
            "used": window.used,
            "total": total,
            "remaining": remaining,
            "remaining_percent": (
                round(remaining / total * 100, 1)
                if remaining is not None and total
                else None
            ),
            "reset_time": dt_util.as_local(
                dt_util.utc_from_timestamp(window.reset_ms / 1000)
            ).isoformat(),
            "window": (
                f"{window.number}×{window.unit}"
                if window.unit is not None and window.number is not None
                else None
            ),
            "raw_type": window.raw_type,
            "plan_level": data.get("level"),
            "plan_name": data.get("plan_name"),
            "plan_valid_until": data.get("plan_valid_until"),
            "plan_next_renew": data.get("plan_next_renew"),
        }
        return {k: v for k, v in attrs.items() if v is not None}
