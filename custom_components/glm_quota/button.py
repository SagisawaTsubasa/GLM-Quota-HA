"""手动查询按钮：仅手动模式（自动轮询关闭）下可用。"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import entity
from .const import DOMAIN
from .coordinator import GlmQuotaCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the manual-refresh button from a config entry."""
    coordinator: GlmQuotaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([GlmQuotaManualRefreshButton(coordinator, entry)])


class GlmQuotaManualRefreshButton(
    CoordinatorEntity[GlmQuotaCoordinator], ButtonEntity
):
    """手动查询：按下立即拉取限额；自动轮询开启时置灰（互斥）。

    挂 CoordinatorEntity 以订阅巡查模式变化：set_auto_polling 里的
    async_update_listeners 会触发本实体重写状态，available 即时生效。
    """

    _attr_has_entity_name = True
    _attr_translation_key = "manual_refresh"
    _attr_icon = "mdi:refresh"

    def __init__(
        self,
        coordinator: GlmQuotaCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self._attr_unique_id = f"glm_quota_manual_refresh_{entry.entry_id}"
        self._attr_device_info = entity.device_info_for(entry)

    @property
    def available(self) -> bool:
        """自动轮询开着时按钮无意义，置灰不可按。

        刻意不组合 super().available：手动模式下拉取失败（last_update_success
        为 False）时它恰是重试入口，不应随刷新失败禁用。
        """
        return not self.coordinator.auto_polling

    async def async_press(self) -> None:
        """立即拉取一次限额数据。"""
        await self.coordinator.async_request_refresh()
