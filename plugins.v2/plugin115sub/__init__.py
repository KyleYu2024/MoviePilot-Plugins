import json
import logging
from typing import Any, Dict, List, Tuple

import requests
from app.core.event import eventmanager, Event
from app.schemas.types import EventType
from app.plugins import _PluginBase

logger = logging.getLogger(__name__)


class Plugin115Sub(_PluginBase):
    plugin_name = "115sub"
    plugin_desc = "将 MoviePilot 订阅/下载/整理事件实时推送给 115sub。"
    plugin_icon = "link.png"
    plugin_version = "0.0.2"
    plugin_author = "KyleYu2024"
    author_url = "https://github.com/KyleYu2024/MoviePilot-Plugins"
    plugin_config_prefix = "plugin115sub_"
    plugin_order = 10
    auth_level = 1

    _enabled = False
    _base_url = ""
    _secret = ""

    def init_plugin(self, config=None):
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._base_url = str(config.get("base_url") or "").strip().rstrip("/")
        self._secret = str(config.get("secret") or "").strip()

    def get_state(self):
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 8},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "base_url",
                                            "label": "115sub 地址",
                                            "placeholder": "http://115sub:8000",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "secret",
                                            "label": "Webhook Secret",
                                            "type": "password",
                                        },
                                    }
                                ],
                            },
                        ],
                    }
                ],
            },
        ], {
            "enabled": False,
            "base_url": "",
            "secret": "",
        }

    def get_page(self) -> List[dict]:
        return []

    def stop_service(self):
        pass

    def _jsonable(self, value):
        try:
            json.dumps(value, ensure_ascii=False, default=str)
            return value
        except Exception:
            return json.loads(json.dumps(value, ensure_ascii=False, default=str))

    def _post(self, event_name, event_data):
        if not self._enabled or not self._base_url or not self._secret:
            return
        payload = {
            "event": event_name,
            "event_type": event_name,
            "data": self._jsonable(event_data),
            "source": "moviepilot",
        }
        try:
            response = requests.post(
                f"{self._base_url}/api/v1/moviepilot/linkage/event",
                headers={"X-Moviepilot-Linkage-Secret": self._secret},
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.warning("115sub 联动事件推送失败: %s", exc)

    @eventmanager.register(EventType.SubscribeAdded)
    def subscribe_added(self, event: Event):
        data = self._jsonable(event.event_data or {})
        if isinstance(data, dict):
            data.setdefault("event", "subscribe.added")
        self._post("subscribe.added", data)

    @eventmanager.register(EventType.DownloadAdded)
    def download_added(self, event: Event):
        data = self._jsonable(event.event_data or {})
        if isinstance(data, dict):
            data.setdefault("event", "download.added")
        self._post("download.added", data)

    @eventmanager.register(EventType.DownloadDeleted)
    def download_deleted(self, event: Event):
        data = self._jsonable(event.event_data or {})
        if isinstance(data, dict):
            data.setdefault("event", "download.deleted")
        self._post("download.deleted", data)

    @eventmanager.register(EventType.TransferComplete)
    def transfer_complete(self, event: Event):
        data = self._jsonable(event.event_data or {})
        if isinstance(data, dict):
            data.setdefault("event", "transfer.complete")
        self._post("transfer.complete", data)
