"""Config flow for GLM Coding Plan quota integration."""

from __future__ import annotations

import hashlib
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import selector
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    CONF_API_KEY,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    QUOTA_API_URL,
)
from .coordinator import async_fetch_glm
from .crypto import async_get_fernet, encrypt_key
from .parse import QuotaError, QuotaNoPlanError, parse_quota


def _fingerprint(api_key: str) -> str:
    """明文 key 的 sha1 指纹前 12 位，用于 unique_id 与展示区分。"""
    return hashlib.sha1(api_key.encode("utf-8")).hexdigest()[:12]


def _unique_id_for(api_key: str) -> str:
    """由明文 key 派生稳定 unique_id（密文不可用作 unique_id：密文随主密钥变）。"""
    return "glm_" + _fingerprint(api_key)


def _title_for(api_key: str) -> str:
    """条目标题带指纹短后缀，多账号时可区分。"""
    return f"GLM Coding Plan ({_fingerprint(api_key)})"


def _api_key_field() -> Any:
    """密码框输入（PasswordSelector 已于新版本移除，统一用 TextSelector）。"""
    return selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
    )


STEP_USER_SCHEMA = vol.Schema({vol.Required(CONF_API_KEY): _api_key_field()})


class GlmQuotaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for GLM Coding Plan quota."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            error = await self._test_api_key(api_key)
            if error is None:
                await self.async_set_unique_id(_unique_id_for(api_key))
                self._abort_if_unique_id_configured()
                fernet = await async_get_fernet(self.hass)
                return self.async_create_entry(
                    title=_title_for(api_key),
                    data={CONF_API_KEY: encrypt_key(fernet, api_key)},
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def _test_api_key(self, api_key: str) -> str | None:
        """提交前实测：限额接口 200 且能解析出两个窗口才算有效。

        async_fetch_glm 把 body code=401 转成 ConfigEntryAuthFailed 抛出，
        这里必须接住映射为表单错误，否则坏 key 提交会以未捕获异常告终。
        """
        try:
            payload = await async_fetch_glm(self.hass, api_key, QUOTA_API_URL)
            parse_quota(payload)
        except ConfigEntryAuthFailed:
            return "invalid_auth"
        except QuotaNoPlanError:
            return "no_plan"
        except UpdateFailed:
            return "cannot_connect"
        except QuotaError:
            return "unknown"
        return None

    async def async_step_reauth(self, entry_data) -> ConfigFlowResult:
        """Perform reauthentication after the coordinator reported a bad key."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a (new) API key and store it encrypted on success."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            error = await self._test_api_key(api_key)
            if error is None:
                new_unique_id = _unique_id_for(api_key)
                for other in self._async_current_entries():
                    if (
                        other.entry_id != reauth_entry.entry_id
                        and other.unique_id == new_unique_id
                    ):
                        return self.async_abort(reason="already_configured")
                fernet = await async_get_fernet(self.hass)
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    title=_title_for(api_key),
                    data={CONF_API_KEY: encrypt_key(fernet, api_key)},
                    unique_id=new_unique_id,
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): _api_key_field()}),
            errors=errors,
            description_placeholders={"name": reauth_entry.title},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> GlmQuotaOptionsFlow:
        """Get the options flow for this handler."""
        return GlmQuotaOptionsFlow()


class GlmQuotaOptionsFlow(OptionsFlow):
    """Handle options flow for GLM Coding Plan quota."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options or {}
        default_scan = options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        if not isinstance(default_scan, int):
            default_scan = DEFAULT_SCAN_INTERVAL

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=default_scan,
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    ),
                }
            ),
        )
