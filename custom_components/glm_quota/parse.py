"""GLM 限额响应解析（纯函数，无 HA 依赖，便于离线单测）。

接口为智谱订阅页同源的非官方接口，2026 年内已观测到三代响应格式：

- 一代: type=TIME_LIMIT(5小时)/TOKENS_LIMIT(周)，字段 percentage / nextResetTime
- 二代: type=两枚 TOKENS_LIMIT(5小时、周) + TIME_LIMIT(月度 MCP)，
        字段 used_percent / reset_time
- 三代(2026-10 实测): 均为 CREDIT_LIMIT，窗口由 unit/number 标明
        (unit=3 小时、unit=6 周)，字段 percentage / nextResetTime /
        currentValue / usage / remaining

因此窗口归属以 unit/number 为准，缺失时按重置时间距离兜底；
字段名同时兼容 percentage 与 used_percent、nextResetTime 与 reset_time。

距离兜底歧义（仅旧格式）：周窗临近重置（≤6h）会与 5 小时窗撞槽，
此时撞槽条目改投另一个空槽并记 warning，两窗标签存在互换可能；
无法确证是响应本身信息不足所致，属于旧格式的已知限制。
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger(__name__)

FIVE_HOUR = "five_hour"
WEEKLY = "weekly"

# unit 枚举：3=小时、6=周（2026-10-09 实测）；其余值走重置距离兜底
_UNIT_HOURS = 3
_UNIT_WEEKS = 6

# 距离兜底阈值：5 小时窗口的重置点最远在 now+5h，留 1h 余量
_FALLBACK_5H_MAX_MS = 6 * 3600 * 1000
# 周窗口锚定周一，重置点距离在 1~7 天，留 1 天余量
_FALLBACK_WEEK_MAX_MS = 8 * 24 * 3600 * 1000
# epoch 毫秒约 10^12 起；小于该值视为秒级时间戳并归一为毫秒
_MS_EPOCH_THRESHOLD = 10**12

_VALID_END_RE = re.compile(r"-\s*(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})\s*$")


class QuotaError(Exception):
    """响应解析或业务层错误，message 面向日志与 UI。"""


class QuotaAuthError(QuotaError):
    """API Key 无效或过期（业务码 401）。"""


class QuotaNoPlanError(QuotaError):
    """账号通过鉴权但没有有效的 Coding Plan 限额数据。"""


@dataclass(slots=True)
class WindowUsage:
    """单个限额窗口的用量。"""

    used_pct: int
    used: int | None
    total: int | None
    remaining: int | None
    reset_ms: int
    unit: int | None
    number: int | None
    raw_type: str | None


@dataclass(slots=True)
class QuotaData:
    """一次成功轮询解析出的全部额度数据。"""

    five_hour: WindowUsage
    weekly: WindowUsage
    level: str | None


def _as_int(value: Any, field: str) -> int | None:
    """宽松转 int；None 原样放行，其余非数值直接报错。"""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QuotaError(f"{field} 不是数值: {value!r}")
    return int(value)


def _as_int_soft(limit: dict[str, Any], field: str, index: int) -> int | None:
    """展示字段宽松解析：畸形按缺失（None）处理并告警，不影响窗口识别。"""
    value = limit.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _LOGGER.warning("limits[%d] %s 值异常，按缺失处理: %r", index, field, value)
        return None
    return int(value)


def _reset_ms(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QuotaError(f"重置时间不是数值: {value!r}")
    ms = float(value)
    if ms < _MS_EPOCH_THRESHOLD:
        ms *= 1000
    return int(ms)


def _percentage(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QuotaError(f"percentage 不是数值: {value!r}")
    return round(float(value))


def _slot_by_distance(reset_ms: int, now_ms: int) -> str | None:
    """无 unit 字段时按重置距离判定窗口；超出两个窗口范围（如月度 MCP）返回 None。"""
    delta = reset_ms - now_ms
    if delta <= _FALLBACK_5H_MAX_MS:
        return FIVE_HOUR
    if delta <= _FALLBACK_WEEK_MAX_MS:
        return WEEKLY
    return None


def parse_quota(payload: Any, now_ms: int | None = None) -> QuotaData:
    """解析限额接口响应；结构异常抛 QuotaError，鉴权失败抛 QuotaAuthError。"""
    now = now_ms if now_ms is not None else int(time.time() * 1000)

    if not isinstance(payload, dict):
        raise QuotaError(f"响应不是 JSON 对象: {type(payload).__name__}")
    code = payload.get("code")
    if code == 401:
        raise QuotaAuthError(str(payload.get("msg") or "令牌无效"))
    if code != 200:
        raise QuotaError(f"业务码 {code}: {payload.get('msg')}")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise QuotaError(f"data 缺失或不是对象: {payload!r}")
    limits = data.get("limits")
    if not isinstance(limits, list) or not limits:
        raise QuotaNoPlanError(f"limits 缺失或为空（无有效 Coding Plan）: {data!r}")

    slots: dict[str, WindowUsage] = {}
    for index, limit in enumerate(limits):
        if not isinstance(limit, dict):
            _LOGGER.warning("limits[%d] 不是对象，跳过: %r", index, limit)
            continue
        # 窗口识别字段（percentage/reset/unit/number）异常 → 单条跳过；
        # 全部跳过导致的缺槽由下方聚合抛错。
        # 显式 null 不占用主字段回退权（dict.get 的 default 只在键缺失时生效）
        pct_raw = limit.get("percentage")
        if pct_raw is None:
            pct_raw = limit.get("used_percent")
        reset_raw = limit.get("nextResetTime")
        if reset_raw is None:
            reset_raw = limit.get("reset_time")
        try:
            used_pct = _percentage(pct_raw)
            reset = _reset_ms(reset_raw)
            unit = _as_int(limit.get("unit"), "unit")
            number = _as_int(limit.get("number"), "number")
        except QuotaError as err:
            _LOGGER.warning("limits[%d] 窗口识别字段异常，跳过: %s", index, err)
            continue

        slot_from_unit = unit == _UNIT_HOURS or unit == _UNIT_WEEKS
        if unit == _UNIT_HOURS:
            slot = FIVE_HOUR
        elif unit == _UNIT_WEEKS:
            slot = WEEKLY
        else:
            slot = _slot_by_distance(reset, now)
        if slot is None:
            # 月度 MCP/web-search 等第三窗口：当前只监控 5 小时与周窗口
            _LOGGER.debug("limits[%d] 不属于 5 小时/周窗口，跳过: %r", index, limit)
            continue

        # 量值仅作展示属性（旧格式本就缺失），畸形按缺失处理，不打挂整轮
        used = _as_int_soft(limit, "currentValue", index)
        total = _as_int_soft(limit, "usage", index)
        remaining = _as_int_soft(limit, "remaining", index)
        entry = WindowUsage(
            used_pct=used_pct,
            used=used,
            total=total,
            remaining=remaining,
            reset_ms=reset,
            unit=unit,
            number=number,
            raw_type=limit.get("type") if isinstance(limit.get("type"), str) else None,
        )

        if slot in slots:
            # 仅距离兜底产生的撞槽允许降级（周窗临近重置 ≤6h 的已知歧义），
            # 显式 unit 的撞槽说明响应本身异常，保留第一条并告警——
            # 不把已确证窗口的数据伪填进另一槽（跨窗错标比失败更糟）
            other = WEEKLY if slot == FIVE_HOUR else FIVE_HOUR
            if other not in slots and not slot_from_unit:
                _LOGGER.warning(
                    "limits[%d] 与 %s 槽冲突（无 unit 字段，距离兜底歧义），"
                    "改投 %s，两窗标签可能互换",
                    index,
                    slot,
                    other,
                )
                slots[other] = entry
            else:
                _LOGGER.warning("limits[%d] 重复映射到 %s，保留第一条", index, slot)
            continue
        slots[slot] = entry

    missing = [s for s in (FIVE_HOUR, WEEKLY) if s not in slots]
    if missing:
        raise QuotaError(
            f"未能从 limits 识别出窗口 {missing}，原始数据: {data!r}"
        )
    level = data.get("level")
    return QuotaData(
        five_hour=slots[FIVE_HOUR],
        weekly=slots[WEEKLY],
        level=level if isinstance(level, str) else None,
    )


def parse_subscription(payload: Any) -> dict[str, str | None]:
    """解析订阅列表，取第一条 VALID 订阅的套餐名/到期/续费日。

    订阅信息是属性级辅助数据：解析失败抛 QuotaError，由调用方决定降级方式。
    """
    if not isinstance(payload, dict):
        raise QuotaError(f"订阅响应不是 JSON 对象: {type(payload).__name__}")
    code = payload.get("code")
    if code == 401:
        raise QuotaAuthError(str(payload.get("msg") or "令牌无效"))
    if code != 200:
        raise QuotaError(f"订阅业务码 {code}: {payload.get('msg')}")
    items = payload.get("data")
    if not isinstance(items, list):
        raise QuotaError(f"订阅 data 不是列表: {payload!r}")

    valid = next(
        (i for i in items if isinstance(i, dict) and i.get("status") == "VALID"), None
    )
    if valid is None:
        raise QuotaError(f"订阅列表中没有 VALID 条目: {items!r}")

    valid_str = valid.get("valid")
    end_part = None
    if isinstance(valid_str, str):
        match = _VALID_END_RE.search(valid_str)
        end_part = match.group(1) if match else valid_str
    renew = valid.get("nextRenewTime")
    return {
        "plan_name": valid.get("productName")
        if isinstance(valid.get("productName"), str)
        else None,
        "plan_valid_until": end_part,
        "plan_next_renew": renew if isinstance(renew, str) else None,
    }
