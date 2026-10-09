"""GLM Coding Plan 限额数据更新协调器。"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FIVE_HOUR,
    QUOTA_API_URL,
    REQUEST_TIMEOUT,
    SUBSCRIPTION_API_URL,
    WEEKLY,
)
from .parse import QuotaError, parse_quota, parse_subscription

_LOGGER = logging.getLogger(__name__)


async def async_fetch_glm(
    hass: HomeAssistant, api_key: str, url: str
) -> dict[str, Any]:
    """请求智谱接口并按 body 业务码分诊。

    该接口的鉴权错误藏在 HTTP 200 的 body 里（code=401/success=false），
    不能按 HTTP 状态码判断认证失败。
    """
    session = async_get_clientsession(hass)
    try:
        async with session.get(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as response:
            text = await response.text()
            if response.status != 200:
                raise UpdateFailed(f"HTTP {response.status}: {text[:200]}")
            try:
                payload = json.loads(text)
            except ValueError as err:
                raise UpdateFailed(f"响应不是 JSON: {text[:200]!r}") from err
    except (TimeoutError, aiohttp.ClientError) as err:
        raise UpdateFailed(f"连接智谱接口失败: {err}") from err

    if not isinstance(payload, dict):
        raise UpdateFailed(f"响应不是 JSON 对象: {text[:200]!r}")
    code = payload.get("code")
    if code == 401:
        raise ConfigEntryAuthFailed(str(payload.get("msg") or "令牌无效"))
    if code != 200:
        raise UpdateFailed(f"业务码 {code}: {payload.get('msg')}")
    return payload


class GlmQuotaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """轮询 5 小时/周限额与订阅信息。"""

    def __init__(
        self,
        hass: HomeAssistant,
        entry,
        api_key: str,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        """初始化；api_key 为调用方解密后的明文，仅驻留内存。"""
        self.api_key = api_key
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """拉取并解析限额；订阅信息任何失败都降级为告警属性缺失。

        401 已在 async_fetch_glm 内转 ConfigEntryAuthFailed（额度端点直接
        冒泡触发 reauth；订阅端点按下方降级处理），parse 层的 QuotaAuthError
        属纯函数契约，集成链路不可达，由 except QuotaError 兜底。
        """
        quota_payload = await async_fetch_glm(
            self.hass, self.api_key, QUOTA_API_URL
        )
        try:
            quota = parse_quota(quota_payload)
        except QuotaError as err:
            raise UpdateFailed(f"限额响应解析失败: {err}") from err

        data: dict[str, Any] = {
            FIVE_HOUR: quota.five_hour,
            WEEKLY: quota.weekly,
            "level": quota.level,
        }
        try:
            sub_payload = await async_fetch_glm(
                self.hass, self.api_key, SUBSCRIPTION_API_URL
            )
            data.update(parse_subscription(sub_payload))
        except ConfigEntryAuthFailed as err:
            # 额度已成功说明 key 有效：订阅端点的端点级 401 属异常场景，
            # 走 reauth 会造成"重输同 key 仍 401"的空转回环，故降级留痕
            _LOGGER.warning("订阅信息鉴权异常（不影响额度实体）: %s", err)
        except (QuotaError, UpdateFailed) as err:
            # 订阅是辅助属性，失败不拦额度数据，但必须留痕不得静默
            _LOGGER.warning("订阅信息获取失败（不影响额度实体）: %s", err)
        return data
