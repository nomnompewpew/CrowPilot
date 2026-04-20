from __future__ import annotations

from copy import deepcopy

_BASE_CAPABILITIES = {
    "nav": {
        "deck": True,
        "mcp": True,
        "knowledge": True,
        "tasks": True,
        "skills": True,
        "credentials": True,
        "integrations": True,
        "projects": True,
        "copilot-history": True,
        "server": True,
    },
    "features": {
        "lan_tools": True,
        "router_tools": True,
        "agent_download": True,
        "monaco_editor": True,
        "big_brain_mode": True,
    },
}

_EDITION_OVERRIDES = {
    "crowpilot-developer": {
        "label": "CrowPilot Developer",
        "intent": "All tools enabled for playground and rapid iteration.",
        "nav": {},
        "features": {},
    },
    "crowpi": {
        "label": "CrowPi",
        "intent": "Entry-level footprint for Raspberry Pi and Orange Pi deployments.",
        "nav": {
            "projects": False,
            "copilot-history": False,
        },
        "features": {
            "lan_tools": False,
            "router_tools": False,
            "agent_download": False,
            "monaco_editor": False,
            "big_brain_mode": False,
        },
    },
    "crowpilot-lite": {
        "label": "CrowPilot Lite",
        "intent": "Balanced CPU-focused profile for older laptops and desktops.",
        "nav": {
            "copilot-history": False,
        },
        "features": {
            "router_tools": False,
            "agent_download": False,
        },
    },
    "crowpilot": {
        "label": "CrowPilot",
        "intent": "Full production profile for GPU and Jetson-class hardware.",
        "nav": {},
        "features": {},
    },
}


def get_edition_profile(edition: str) -> dict:
    payload = deepcopy(_BASE_CAPABILITIES)
    overrides = _EDITION_OVERRIDES.get(edition, _EDITION_OVERRIDES["crowpilot-developer"])
    payload["nav"].update(overrides.get("nav", {}))
    payload["features"].update(overrides.get("features", {}))
    payload["edition"] = edition
    payload["label"] = overrides["label"]
    payload["intent"] = overrides["intent"]
    payload["disabled_nav"] = [name for name, enabled in payload["nav"].items() if not enabled]
    payload["disabled_features"] = [name for name, enabled in payload["features"].items() if not enabled]
    return payload
