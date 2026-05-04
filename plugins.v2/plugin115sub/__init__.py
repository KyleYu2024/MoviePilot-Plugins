import json
from typing import Any, Dict, List, Tuple

import requests
from app.core.event import eventmanager, Event
from app.log import logger
from app.schemas.types import EventType, ChainEventType
from app.plugins import _PluginBase


class Plugin115Sub(_PluginBase):
    plugin_name = "115sub"
    plugin_desc = "将 MoviePilot 与 115sub 进行订阅、下载、占位和完成态双向联动。"
    plugin_icon = "link.png"
    plugin_version = "0.0.5"
    plugin_author = "KyleYu2024"
    author_url = "https://github.com/KyleYu2024/MoviePilot-Plugins"
    plugin_config_prefix = "plugin115sub_"
    plugin_order = 10
    auth_level = 1

    _enabled = False
    _base_url = ""
    _secret = ""
    _status_cache = {}

    def init_plugin(self, config=None):
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._base_url = str(config.get("base_url") or "").strip().rstrip("/")
        self._secret = str(config.get("secret") or "").strip()
        if self._enabled:
            logger.info("115sub 插件已启用，目标地址：%s", self._base_url or "未配置")
        else:
            logger.info("115sub 插件未启用")

    def get_state(self):
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/status",
                "endpoint": self.receive_status,
                "methods": ["POST"],
                "auth": "apikey",
                "summary": "接收 115sub 占位/完成状态",
                "description": "由 115sub 在转存占位和 Emby 入库确认后推送状态。",
            }
        ]

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
        pass

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
            logger.info("115sub 联动事件推送成功: %s", event_name)
        except Exception as exc:
            logger.warning("115sub 联动事件推送失败: %s", exc)

    def _query_linkage(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self._enabled or not self._base_url or not self._secret:
            return {"success": False, "reason": "plugin_disabled"}
        payload = dict(payload or {})
        payload.setdefault("secret", self._secret)
        try:
            response = requests.post(
                f"{self._base_url}{endpoint}",
                headers={"X-Moviepilot-Linkage-Secret": self._secret},
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {"success": False, "reason": "invalid_response"}
        except Exception as exc:
            logger.warning("115sub 联动查询失败: %s", exc)
            return {"success": False, "reason": "request_failed", "message": str(exc)}

    def _status_key(self, tmdb_id, media_type, season, episode):
        try:
            season = int(season or 0)
        except Exception:
            season = 0
        try:
            episode = int(episode or 0)
        except Exception:
            episode = 0
        return f"{tmdb_id}:{str(media_type or '').lower()}:{season}:{episode}"

    def receive_status(self, payload: Dict[str, Any]):
        data = payload or {}
        tmdb_id = str(data.get("tmdb_id") or "").strip()
        media_type = str(data.get("type") or "tv").strip().lower()
        season = int(data.get("season") or 0)
        status = str(data.get("status") or "processing").strip().lower()
        episodes = data.get("episodes") or [0 if media_type == "movie" else data.get("episode")]
        if not isinstance(episodes, (list, tuple, set)):
            episodes = [episodes]
        if not tmdb_id:
            return {"success": False, "reason": "missing_tmdb_id"}

        upserted = 0
        for ep in episodes:
            try:
                episode = int(ep or 0)
            except Exception:
                continue
            if media_type != "movie" and episode <= 0:
                continue
            self._status_cache[self._status_key(tmdb_id, media_type, season, episode)] = {
                "tmdb_id": tmdb_id,
                "type": media_type,
                "season": season,
                "episode": episode,
                "status": status,
                "updated_at": data.get("updated_at") or "",
                "source": data.get("source") or "115sub",
            }
            upserted += 1
        logger.info("115sub 状态已接收: tmdb=%s season=%s episodes=%s status=%s", tmdb_id, season, episodes, status)
        return {"success": True, "upserted": upserted}

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

    @eventmanager.register(ChainEventType.ResourceDownload, priority=1)
    def resource_download(self, event: Event):
        data = event.event_data
        if not data:
            return

        context = getattr(data, "context", None)
        media = getattr(context, "media_info", None) if context else None
        meta = getattr(context, "meta_info", None) if context else None
        if not media:
            return

        raw_episodes = getattr(data, "episodes", None)
        if raw_episodes is None and meta is not None:
            raw_episodes = getattr(meta, "episode_list", None)
        if raw_episodes is None:
            raw_episodes = []
        if not isinstance(raw_episodes, (list, tuple, set)):
            raw_episodes = [raw_episodes]

        episodes = []
        for ep in raw_episodes:
            try:
                ep_num = int(str(ep).strip())
            except Exception:
                continue
            if ep_num > 0:
                episodes.append(ep_num)

        season = getattr(meta, "begin_season", None) or getattr(media, "season", None) or 0
        media_type = getattr(media, "type", "")
        media_type_text = getattr(media_type, "value", None) or str(media_type or "")
        if media_type_text.lower() in {"movie", "电影"}:
            season = 0
            episodes = [0]
        elif not episodes:
            episode = getattr(meta, "begin_episode", None)
            try:
                episode = int(episode or 0)
            except Exception:
                episode = 0
            if episode > 0:
                episodes = [episode]

        payload = {
            "tmdb_id": getattr(media, "tmdb_id", "") or getattr(meta, "tmdb_id", "") or "",
            "type": media_type_text,
            "season": season,
            "episodes": episodes,
            "origin": getattr(data, "origin", "") or "",
            "downloader": getattr(data, "downloader", "") or "",
        }

        cached_rows = [
            self._status_cache.get(self._status_key(payload["tmdb_id"], media_type_text, season, ep))
            for ep in episodes
        ]
        cached_rows = [row for row in cached_rows if row and row.get("status") in {"processing", "completed"}]
        if cached_rows and len(cached_rows) == len(episodes):
            completed = all(row.get("status") == "completed" for row in cached_rows)
            data.cancel = True
            data.source = "115sub"
            data.reason = "115sub/Emby 已确认入库" if completed else "115sub 已占位"
            logger.info(
                "115sub 本地状态命中，拦截 MoviePilot 下载: tmdb=%s season=%s episodes=%s status=%s",
                payload.get("tmdb_id"),
                payload.get("season"),
                payload.get("episodes"),
                "completed" if completed else "processing",
            )
            return

        result = self._query_linkage("/api/v1/moviepilot/linkage/placeholder/check", payload)
        if result.get("success") and result.get("block"):
            data.cancel = True
            data.source = "115sub"
            data.reason = result.get("message") or "115sub 已占位"
            logger.info(
                "115sub 占位命中，拦截 MoviePilot 下载: tmdb=%s season=%s episodes=%s",
                payload.get("tmdb_id"),
                payload.get("season"),
                payload.get("episodes"),
            )
