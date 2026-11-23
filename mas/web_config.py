"""Public configuration catalog and per-run overrides for the local workspace."""
from __future__ import annotations

from dataclasses import replace

from mas.config import Settings, research_limit_overrides


_PROVIDERS = {"hkgai": "HKGAI", "deepseek": "DeepSeek"}
_PARAMETERS = {"budget", "research", "min_use"}
_FIELDS = {"provider", "model", "key_source", "api_key", "preset"} | _PARAMETERS


def config_catalog(settings: Settings) -> dict:
    providers = {
        provider: {"name": name, "model": getattr(settings, f"{provider}_model"),
                   "has_key": bool(getattr(settings, f"{provider}_api_key").strip())}
        for provider, name in _PROVIDERS.items()
    }
    presets = {
        "environment": {"name": "当前环境", "budget": settings.request_budget_s,
                        "research": settings.research_max_calls, "min_use": settings.finish_not_before},
        "fast": {"name": "快速", "budget": 270, "research": 14, "min_use": 0.5},
        "full": {"name": "完整", "budget": 900, "research": 28, "min_use": 0},
    }
    return {"provider": settings.llm_provider.strip().lower(), "providers": providers,
            "preset": "environment", "presets": presets}


def _custom_parameters(options: dict) -> dict:
    budget, research, min_use = (options.get(k) for k in ("budget", "research", "min_use"))
    # Positive comparisons also reject NaN and infinities. Check types separately
    # because bool is an int in Python; JSON true must never become a one-second run.
    if type(budget) not in (int, float) or not 0 <= budget <= 2**31 - 1:
        raise ValueError("时间预算必须是非负的有限秒数。")
    if type(research) is not int or not 0 <= research <= 2**31 - 1:
        raise ValueError("研究次数必须是非负整数。")
    if type(min_use) not in (int, float) or not 0 <= min_use < 1:
        raise ValueError("最低时间使用比例必须大于等于 0 且小于 1。")
    return {"budget": budget, "research": research, "min_use": min_use}


def resolve_config(settings: Settings, options: dict | None) -> tuple[Settings, dict]:
    """Produce a new Settings and a separately constructed, safe-to-return description."""
    options = {} if options is None else options
    if not isinstance(options, dict) or set(options) - _FIELDS:
        raise ValueError("运行配置格式或字段无效。")
    catalog = config_catalog(settings)
    provider = options.get("provider", catalog["provider"])
    if not isinstance(provider, str) or provider not in _PROVIDERS:
        raise ValueError("请选择 HKGAI 或 DeepSeek。")
    model = options.get("model", catalog["providers"][provider]["model"])
    if not isinstance(model, str) or not model.strip() or len(model) > 256 or not model.isprintable():
        raise ValueError("请输入有效的模型 ID。")
    model = model.strip()
    overrides = {"llm_provider": provider, f"{provider}_model": model}
    source = options.get("key_source", "server")
    if source == "custom":
        key = options.get("api_key")
        if not isinstance(key, str) or not 1 <= len(key) <= 4096 or not all(33 <= ord(c) <= 126 for c in key):
            raise ValueError("请输入有效的 API Key，不能包含空格或换行。")
        overrides[f"{provider}_api_key"] = key
    elif source != "server" or "api_key" in options:
        raise ValueError("请选择有效的密钥来源。只有本次输入模式可以提交 API Key。")

    preset = options.get("preset", "environment")
    if preset == "custom":
        values = _custom_parameters(options)
    else:
        if not isinstance(preset, str) or preset not in catalog["presets"]:
            raise ValueError("运行预设无效。")
        if _PARAMETERS & options.keys():
            raise ValueError("只有自定义预设可以更改运行参数。")
        values = {k: catalog["presets"][preset][k] for k in _PARAMETERS}
    if preset != "environment":
        overrides.update(request_budget_s=values["budget"], finish_not_before=values["min_use"])
        if preset == "fast":
            # The documented fast preset uses the defaults (without --research-limit).
            overrides.update(research_max_calls=14, research_note_after=Settings.research_note_after,
                             research_note_every=Settings.research_note_every)
        elif preset == "full" or values["research"] != settings.research_max_calls:
            overrides.update(research_limit_overrides(values["research"]))
    public = {"provider": provider, "model": model, "key_source": source, "preset": preset, **values}
    return replace(settings, **overrides), public
