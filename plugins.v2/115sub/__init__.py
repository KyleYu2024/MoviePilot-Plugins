import json
import logging

import requests
from app.core.config import settings
from app.core.event import eventmanager, Event
from app.schemas.types import EventType
from app.plugins import _PluginBase

logger = logging.getLogger(__name__)


class Plugin115Sub(_PluginBase):
    plugin_name = "115sub"
    plugin_desc = "将 MoviePilot 订阅/下载/整理事件实时推送给 115sub。"
    plugin_icon = "link.png"
    plugin_version = "1.0.0"
    plugin_author = "115sub"
    author_url = "https://github.com"
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

    def get_form(self):
        return [
            {
                "component": "VSwitch",
                "model": "enabled",
                "label": "启用",
            },
            {
                "component": "VTextField",
                "model": "base_url",
                "label": "115sub 地址",
                "placeholder": "http://115sub:8000",
            },
            {
                "component": "VTextField",
                "model": "secret",
                "label": "Webhook Secret",
            },
        ], {
            "enabled": False,
            "base_url": "",
            "secret": "",
        }

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

    @eventmanager.register(EventType.SubscribeModified)
    def subscribe_modified(self, event: Event):
        data = self._jsonable(event.event_data or {})
        if isinstance(data, dict):
            data.setdefault("event", "subscribe.modified")
        self._post("subscribe.modified", data)

    @eventmanager.register(EventType.SubscribeDeleted)
    def subscribe_deleted(self, event: Event):
        data = self._jsonable(event.event_data or {})
        if isinstance(data, dict):
            data.setdefault("event", "subscribe.deleted")
        self._post("subscribe.deleted", data)

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
