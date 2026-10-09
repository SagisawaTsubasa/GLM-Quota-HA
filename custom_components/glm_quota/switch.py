"""自动轮询开关：开=自动轮询；关=手动模式（与手动查询按钮互斥）。"""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import entity
from .const import DOMAIN
from .coordinator import GlmQuotaCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the auto-polling switch from a config entry."""
    coordinator: GlmQuotaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([GlmQuotaAutoPollingSwitch(coordinator, entry)])


class GlmQuotaAutoPollingSwitch(SwitchEntity, RestoreEntity):
    """自动轮询开关；关闭即进入手动模式（定时轮询停止）。"""

    _attr_has_entity_name = True
    _attr_translation_key = "auto_polling"
    _attr_icon = "mdi:autorenew"

    def __init__(
        self,
        coordinator: GlmQuotaCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the switch."""
        self.coordinator = coordinator
        self._attr_unique_id = f"glm_quota_auto_polling_{entry.entry_id}"
        self._attr_device_info = entity.device_info_for(entry)

    async def async_added_to_hass(self) -> None:
        """恢复上次模式：重启前为手动模式则继续停轮询。"""
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        if state is not None and state.state == STATE_OFF:
            self.coordinator.set_auto_polling(False)
            _LOGGER.debug("恢复巡查模式为手动查询")
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """开=自动轮询；关=手动模式。"""
        return self.coordinator.auto_polling

    async def async_turn_on(self, **kwargs) -> None:
        """开启自动轮询。"""
        self.coordinator.set_auto_polling(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """关闭自动轮询，进入手动模式。"""
        self.coordinator.set_auto_polling(False)
        self.async_write_ha_state()
