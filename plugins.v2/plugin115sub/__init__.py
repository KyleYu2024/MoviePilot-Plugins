import json
import re
import threading
import time
from typing import Any, Dict, List, Tuple

import requests
from app.core.config import settings
from app.core.event import eventmanager, Event
from app.log import logger
from app.schemas.types import EventType, ChainEventType
from app.plugins import _PluginBase


class Plugin115Sub(_PluginBase):
    plugin_name = "115sub"
    plugin_desc = "将 MoviePilot 与 115sub 进行订阅、下载、占位和完成态双向联动。"
    plugin_icon = "link.png"
    plugin_version = "0.1.3"
    plugin_author = "KyleYu"
    author_url = "https://github.com/KyleYu2024/MoviePilot-Plugins"
    plugin_config_prefix = "plugin115sub_"
    plugin_order = 10
    auth_level = 1

    _enabled = False
    _base_url = ""
    _status_cache = {}
    _warning_cooldown_until = {}
    _warning_cooldown_seconds = 10 * 60
    _subscribe_search_cooldown_until = {}
    _subscribe_search_cooldown_seconds = 2 * 60
    _active_instance = None
    _downloadchain_patched = False
    _downloadchain_original_get_no_exists_info = None
    _logger_patched = False
    _logger_patch_mode = ""
    _original_logger_info = None
    _original_logger_warning = None

    def init_plugin(self, config=None):
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._base_url = str(config.get("base_url") or "").strip().rstrip("/")
        self._warning_cooldown_until = {}
        self._subscribe_search_cooldown_until = {}
        self.__class__._active_instance = self
        self._install_log_noise_patch()
        self._install_downloadchain_patch()
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
                        ],
                    }
                ],
            },
        ], {
            "enabled": False,
            "base_url": "",
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        if self.__class__._active_instance is self:
            self.__class__._active_instance = None

    @classmethod
    def _format_log_message(cls, message, args, kwargs):
        text = str(message or "")
        if not args:
            return text
        try:
            return text % args
        except Exception:
            pass
        try:
            return text.format(*args, **kwargs)
        except Exception:
            return " ".join([text, *(str(arg) for arg in args)])

    @classmethod
    def _should_suppress_info(cls, message, args, kwargs):
        text = cls._format_log_message(message, args, kwargs)
        if "在媒体库 " in text and " 中找到了这些季集" in text:
            return True
        if "没有在媒体库 " in text:
            return True
        if "115sub 原始下载任务事件缺少 TMDB ID" in text:
            return True
        if "115sub 下载占位跳过" in text:
            return True
        if "115sub 下载任务事件暂未接收" in text:
            return True
        return False

    @classmethod
    def _should_suppress_warning(cls, message, args, kwargs):
        text = cls._format_log_message(message, args, kwargs)
        return text.startswith("115sub ")

    @classmethod
    def _install_log_noise_patch(cls):
        if cls._logger_patched:
            return
        original_info = getattr(logger, "info", None)
        original_warning = getattr(logger, "warning", None)
        if not original_info or not original_warning:
            return

        def patched_info(message, *args, **kwargs):
            if cls._should_suppress_info(message, args, kwargs):
                return None
            return original_info(message, *args, **kwargs)

        def patched_warning(message, *args, **kwargs):
            if cls._should_suppress_warning(message, args, kwargs):
                return None
            return original_warning(message, *args, **kwargs)

        try:
            setattr(logger, "info", patched_info)
            setattr(logger, "warning", patched_warning)
            cls._logger_patch_mode = "instance"
        except Exception:
            return
        cls._original_logger_info = original_info
        cls._original_logger_warning = original_warning
        cls._logger_patched = True

    def _jsonable(self, value):
        try:
            return json.loads(json.dumps(value, ensure_ascii=False, default=str))
        except Exception:
            return str(value)

    @staticmethod
    def _api_token():
        return str(getattr(settings, "API_TOKEN", "") or "").strip()

    @staticmethod
    def _event_label(event_name):
        labels = {
            "subscribe.added": "订阅新增",
            "download.added": "下载任务新增",
            "download.deleted": "下载任务删除",
            "transfer.complete": "整理完成",
        }
        return labels.get(str(event_name or ""), str(event_name or "未知事件"))

    @staticmethod
    def _status_label(status):
        labels = {
            "processing": "占位中",
            "completed": "已入库",
            "failed": "失败",
            "cancelled": "已取消",
        }
        return labels.get(str(status or "").lower(), str(status or "未知"))

    @staticmethod
    def _media_type_label(media_type):
        value = str(media_type or "").lower()
        if value in {"movie", "电影"}:
            return "电影"
        if value in {"tv", "series", "电视剧", "剧集"}:
            return "剧集"
        return str(media_type or "未知")

    @staticmethod
    def _clean_text(value):
        text = str(value or "").strip()
        if not text or text.lower() in {"none", "null"}:
            return ""
        return text

    @classmethod
    def _first_text(cls, *values):
        for value in values:
            text = cls._clean_text(value)
            if text:
                return text
        return ""

    @classmethod
    def _field_text(cls, source, *names):
        if not source:
            return ""
        for name in names:
            value = None
            if isinstance(source, dict):
                value = source.get(name)
            else:
                value = getattr(source, name, None)
            text = cls._clean_text(value)
            if text:
                return text
        return ""

    @classmethod
    def _payload_title(cls, data: Dict[str, Any]) -> str:
        return cls._first_text(
            cls._payload_field_text(
                data,
                "title",
                "media_title",
                "media_name",
                "title_cn",
                "cn_name",
                "original_title",
            ),
            cls._payload_field_text(
                data,
                "resource_name",
                "torrent_name",
                "file_name",
                "filename",
                "name",
            ),
        )

    @classmethod
    def _context_title(cls, media, meta) -> str:
        return cls._first_text(
            cls._field_text(media, "title", "name", "original_title", "cn_name", "title_year"),
            cls._field_text(meta, "title", "name", "org_string", "cn_name", "original_title"),
        )

    @classmethod
    def _media_log_label(cls, title, tmdb_id):
        title = cls._clean_text(title)
        if title:
            return f"片名=《{title}》"
        tmdb_id = cls._clean_text(tmdb_id)
        if tmdb_id:
            return f"TMDB={tmdb_id}"
        return "片名=未知"

    @classmethod
    def _iter_payload_nodes(cls, source, depth=0, seen=None):
        if source is None or depth > 6:
            return
        if seen is None:
            seen = set()
        if isinstance(source, (dict, list, tuple, set)):
            marker = id(source)
            if marker in seen:
                return
            seen.add(marker)

        yield source

        if isinstance(source, dict):
            for value in source.values():
                yield from cls._iter_payload_nodes(value, depth + 1, seen)
        elif isinstance(source, (list, tuple, set)):
            for value in source:
                yield from cls._iter_payload_nodes(value, depth + 1, seen)

    @classmethod
    def _payload_field_values(cls, source, *names):
        wanted = [(name, str(name).lower()) for name in names]
        for node in cls._iter_payload_nodes(source):
            if isinstance(node, dict):
                for _, field_name in wanted:
                    for key, value in node.items():
                        if str(key).lower() == field_name:
                            yield value
            elif not isinstance(node, (str, int, float, bool)):
                for name, _ in wanted:
                    if hasattr(node, name):
                        yield getattr(node, name, None)

    @classmethod
    def _payload_field_text(cls, source, *names):
        for value in cls._payload_field_values(source, *names):
            text = cls._clean_text(value)
            if text:
                return text
        return ""

    @classmethod
    def _first_int(cls, value):
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return int(value)
        text = cls._clean_text(value)
        if not text:
            return None
        match = re.search(r"\d+", text)
        if not match:
            return None
        try:
            return int(match.group(0))
        except Exception:
            return None

    @classmethod
    def _payload_tmdb_id(cls, data):
        return cls._payload_field_text(data, "tmdb_id", "tmdbid", "tmdbId", "tmdb")

    @classmethod
    def _payload_media_type(cls, data):
        return cls._payload_field_text(data, "media_type", "mediaType", "media_category", "type")

    @classmethod
    def _payload_season(cls, data):
        for value in cls._payload_field_values(data, "season", "season_number", "season_num", "begin_season"):
            number = cls._first_int(value)
            if number is not None:
                return number
        return None

    @classmethod
    def _episode_numbers_from_value(cls, value):
        if value is None or isinstance(value, bool):
            return []
        if isinstance(value, (list, tuple, set)):
            numbers = []
            for item in value:
                numbers.extend(cls._episode_numbers_from_value(item))
            return numbers
        if isinstance(value, dict):
            numbers = []
            for key in ("episode", "episode_number", "episode_num", "begin_episode", "ep", "number"):
                if key in value:
                    numbers.extend(cls._episode_numbers_from_value(value.get(key)))
            return numbers
        if isinstance(value, (int, float)):
            return [int(value)]

        text = cls._clean_text(value)
        if not text:
            return []

        episode_matches = re.findall(r"(?i)E(?:P)?\s*0*(\d{1,4})", text)
        if episode_matches:
            return [int(item) for item in episode_matches]

        chinese_matches = re.findall(r"第\s*0*(\d{1,4})\s*[集话話]", text)
        if chinese_matches:
            return [int(item) for item in chinese_matches]

        range_match = re.fullmatch(r"\s*0*(\d{1,4})\s*[-~至]\s*0*(\d{1,4})\s*", text)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            if start <= end and end - start <= 100:
                return list(range(start, end + 1))

        return [int(item) for item in re.findall(r"\d+", text)]

    @classmethod
    def _payload_episodes(cls, data):
        episodes = []
        for value in cls._payload_field_values(
            data,
            "episodes",
            "episode_list",
            "episode",
            "episode_number",
            "episode_num",
            "begin_episode",
            "ep",
        ):
            episodes.extend(cls._episode_numbers_from_value(value))

        unique = []
        for episode in episodes:
            if episode < 0 or episode in unique:
                continue
            unique.append(episode)
        return unique

    @classmethod
    def _format_episode_list(cls, episodes):
        if not episodes:
            return ""
        if not isinstance(episodes, (list, tuple, set)):
            episodes = [episodes]
        values = []
        for episode in episodes:
            number = cls._first_int(episode)
            if number is not None:
                values.append(str(number))
                continue
            text = cls._clean_text(episode)
            if text:
                values.append(text)
        if values == ["0"]:
            return "电影"
        if len(values) > 12:
            return f"{','.join(values[:12])} 等{len(values)}集"
        return ",".join(values)

    @classmethod
    def _episode_log_label(cls, media_type, season, episodes):
        media_value = str(media_type or "").lower()
        if media_value in {"movie", "电影"}:
            return ""

        parts = []
        season_number = cls._first_int(season)
        if season_number and season_number > 0:
            parts.append(f"第{season_number}季")
        episode_text = cls._format_episode_list(episodes)
        if episode_text:
            parts.append(f"集数={episode_text}")
        return "，".join(parts)

    @classmethod
    def _short_file_label(cls, value):
        text = cls._clean_text(value)
        if not text:
            return ""
        normalized = text.replace("\\", "/").rstrip("/")
        return normalized.rsplit("/", 1)[-1] or text

    @classmethod
    def _payload_file_label(cls, data):
        return cls._short_file_label(
            cls._payload_field_text(
                data,
                "file_name",
                "filename",
                "file",
                "torrent_name",
                "resource_name",
                "path",
                "save_path",
                "download_path",
            )
        )

    @classmethod
    def _event_log_context(cls, data):
        title = cls._payload_title(data)
        tmdb_id = cls._payload_tmdb_id(data)
        media_type = cls._payload_media_type(data)
        season = cls._payload_season(data)
        episodes = cls._payload_episodes(data)
        file_label = cls._payload_file_label(data)

        parts = []
        if title or tmdb_id:
            parts.append(cls._media_log_label(title, tmdb_id))
        type_label = cls._media_type_label(media_type) if media_type else ""
        if type_label and type_label != "未知":
            parts.append(f"类型={type_label}")
        episode_label = cls._episode_log_label(media_type, season, episodes)
        if episode_label:
            parts.append(episode_label)
        if file_label and file_label != title:
            parts.append(f"文件={file_label}")

        return f"，{'，'.join(parts)}" if parts else ""

    def _should_log_warning(self, key: str) -> bool:
        now = time.time()
        if now < float(self._warning_cooldown_until.get(key) or 0):
            return False
        self._warning_cooldown_until[key] = now + self._warning_cooldown_seconds
        return True

    @staticmethod
    def _request_error_summary(exc: Exception, token: str = "") -> str:
        response = getattr(exc, "response", None)
        if response is not None:
            return f"HTTP {response.status_code} {response.reason}".strip()
        text = str(exc)
        if token:
            text = text.replace(token, "***")
        return f"{type(exc).__name__}: {text}"

    @staticmethod
    def _failure_reason(data: Dict[str, Any]) -> str:
        return str((data or {}).get("reason") or (data or {}).get("message") or "unknown")

    def _post(self, event_name, event_data):
        token = self._api_token()
        if not self._enabled or not self._base_url or not token:
            return
        event_context = self._event_log_context(event_data)
        payload = {
            "event": event_name,
            "event_type": event_name,
            "data": self._jsonable(event_data),
            "source": "moviepilot",
            "secret": token,
        }
        try:
            response = requests.post(
                f"{self._base_url}/api/v1/moviepilot/linkage/event",
                headers={"X-Moviepilot-Linkage-Secret": token},
                params={"token": token},
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json() if response.content else {}
            if isinstance(data, dict) and data.get("success") is False:
                reason = self._failure_reason(data)
                log_key = f"event:{event_name}:{reason}"
                if event_name == "download.added" and reason in {"missing_tmdb_id", "missing_episodes", "missing_episode"}:
                    if event_context or self._should_log_warning(log_key):
                        logger.info(
                            "115sub 下载任务事件暂未接收：事件=%s，原因=%s%s",
                            self._event_label(event_name),
                            reason,
                            event_context,
                        )
                    return
                return
            logger.info("115sub 联动事件推送成功：moviepilot%s%s", self._event_label(event_name), event_context)
        except Exception:
            return

    def _query_linkage(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        token = self._api_token()
        if not self._enabled or not self._base_url or not token:
            return {"success": False, "reason": "plugin_disabled"}
        payload = dict(payload or {})
        payload.setdefault("secret", token)
        try:
            response = requests.post(
                f"{self._base_url}{endpoint}",
                headers={"X-Moviepilot-Linkage-Secret": token},
                params={"token": token},
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {"success": False, "reason": "invalid_response"}
        except Exception as exc:
            error = self._request_error_summary(exc, token)
            return {"success": False, "reason": "request_failed", "message": f"请求 115sub 失败：{error}"}

    def _install_downloadchain_patch(self):
        cls = self.__class__
        if cls._downloadchain_patched:
            return
        try:
            from app.chain.download import DownloadChain
        except Exception as exc:
            logger.debug("115sub MoviePilot 下载缺失集 hook 安装跳过：%s", exc)
            return

        original = getattr(DownloadChain, "get_no_exists_info", None)
        if not original or getattr(original, "_plugin115sub_patched", False):
            cls._downloadchain_patched = True
            return

        def patched_get_no_exists_info(chain_self, *args, **kwargs):
            result = original(chain_self, *args, **kwargs)
            plugin = cls._active_instance
            if not plugin:
                return result
            meta = kwargs.get("meta") if "meta" in kwargs else (args[0] if len(args) > 0 else None)
            mediainfo = kwargs.get("mediainfo") if "mediainfo" in kwargs else (args[1] if len(args) > 1 else None)
            return plugin._apply_115sub_placeholders_to_no_exists(result, meta, mediainfo)

        patched_get_no_exists_info._plugin115sub_patched = True
        patched_get_no_exists_info._plugin115sub_original = original
        cls._downloadchain_original_get_no_exists_info = original
        DownloadChain.get_no_exists_info = patched_get_no_exists_info
        cls._downloadchain_patched = True
        logger.info("115sub 已接入 MoviePilot 缺失集判断，下载拆包会参考 115sub 占位状态")

    @classmethod
    def _media_type_value(cls, media_type):
        return getattr(media_type, "value", None) or str(media_type or "")

    @classmethod
    def _safe_int(cls, value, default=0):
        number = cls._first_int(value)
        return default if number is None else number

    @classmethod
    def _season_missing_episodes(cls, not_exist):
        episodes = getattr(not_exist, "episodes", None) or []
        if episodes:
            values = []
            for ep in episodes:
                number = cls._safe_int(ep, 0)
                if number > 0:
                    values.append(number)
            return values

        total_episode = cls._safe_int(getattr(not_exist, "total_episode", 0), 0)
        start_episode = cls._safe_int(getattr(not_exist, "start_episode", 1), 1) or 1
        if total_episode <= 0:
            return []
        return list(range(start_episode, total_episode + 1))

    @staticmethod
    def _replace_not_exist_episodes(not_exist, episodes):
        try:
            not_exist.episodes = episodes
            return not_exist
        except Exception:
            pass
        try:
            return not_exist.__class__(
                season=getattr(not_exist, "season", 0),
                episodes=episodes,
                total_episode=getattr(not_exist, "total_episode", 0),
                start_episode=getattr(not_exist, "start_episode", 1),
            )
        except Exception:
            return not_exist

    def _apply_115sub_placeholders_to_no_exists(self, result, meta, mediainfo):
        if not self._enabled or not self._base_url or not self._api_token():
            return result
        if not isinstance(result, tuple) or len(result) != 2:
            return result

        exist_flag, no_exists = result
        if exist_flag or not no_exists or not isinstance(no_exists, dict) or not mediainfo:
            return result

        media_type = self._media_type_value(getattr(mediainfo, "type", ""))
        if media_type.lower() in {"movie", "电影"}:
            return result

        tmdb_id = self._clean_text(getattr(mediainfo, "tmdb_id", ""))
        if not tmdb_id:
            return result

        title = self._context_title(mediainfo, meta)
        media_keys = {
            self._clean_text(getattr(mediainfo, "tmdb_id", "")),
            self._clean_text(getattr(mediainfo, "douban_id", "")),
            self._clean_text(getattr(mediainfo, "bangumi_id", "")),
        }
        media_keys = {key for key in media_keys if key}
        removed_total = []
        remaining_total = []

        for media_key, seasons in list(no_exists.items()):
            if self._clean_text(media_key) not in media_keys or not isinstance(seasons, dict):
                continue
            for season_key, not_exist in list(seasons.items()):
                season = self._safe_int(getattr(not_exist, "season", None), self._safe_int(season_key, 1))
                requested = self._season_missing_episodes(not_exist)
                if not requested:
                    continue

                payload = {
                    "tmdb_id": tmdb_id,
                    "title": title,
                    "type": media_type,
                    "season": season,
                    "episodes": requested,
                    "skip_subscription_check": True,
                }
                check = self._query_linkage("/api/v1/moviepilot/linkage/placeholder/check", payload)
                if not check.get("success"):
                    continue

                covered = {
                    self._safe_int(row.get("episode"), 0)
                    for row in check.get("rows") or []
                    if self._safe_int(row.get("episode"), 0) > 0
                }
                if not covered:
                    continue

                remaining = [episode for episode in requested if episode not in covered]
                removed = [episode for episode in requested if episode in covered]
                removed_total.extend(removed)
                remaining_total.extend(remaining)
                if remaining:
                    seasons[season_key] = self._replace_not_exist_episodes(not_exist, remaining)
                else:
                    seasons.pop(season_key, None)

            if not seasons:
                no_exists.pop(media_key, None)

        if removed_total:
            logger.info(
                "115sub 占位已合并到 MoviePilot 缺失集判断%s，已占位集数=%s，剩余缺失=%s",
                self._event_log_context({"tmdb_id": tmdb_id, "title": title, "type": media_type, "episodes": sorted(set(removed_total))}),
                sorted(set(removed_total)),
                sorted(set(remaining_total)),
            )

        if not no_exists:
            return True, {}
        return exist_flag, no_exists

    @staticmethod
    def _is_failed_status(status):
        return str(status or "").strip().lower() in {"failed", "cancelled", "canceled", "deleted"}

    def _should_trigger_subscribe_search(self, key: str) -> bool:
        now = time.time()
        if now < float(self._subscribe_search_cooldown_until.get(key) or 0):
            return False
        self._subscribe_search_cooldown_until[key] = now + self._subscribe_search_cooldown_seconds
        return True

    def _find_moviepilot_subscribes(self, tmdb_id, media_type, season):
        tmdb_text = self._clean_text(tmdb_id)
        if not tmdb_text or not tmdb_text.isdigit():
            return []
        try:
            from app.db.subscribe_oper import SubscribeOper
        except Exception:
            return []

        try:
            tmdb_value = int(tmdb_text)
            media_value = str(media_type or "").lower()
            if media_value in {"movie", "电影"}:
                return SubscribeOper().list_by_tmdbid(tmdbid=tmdb_value, season=None) or []

            season_value = self._safe_int(season, 0)
            if season_value > 0:
                subscribes = SubscribeOper().list_by_tmdbid(tmdbid=tmdb_value, season=season_value) or []
                if subscribes:
                    return subscribes
            return SubscribeOper().list_by_tmdbid(tmdbid=tmdb_value, season=None) or []
        except Exception:
            return []

    def _trigger_moviepilot_subscribe_search(self, *, tmdb_id, media_type, season, episodes, title):
        if not self._enabled:
            return
        if not episodes:
            return
        subscribes = self._find_moviepilot_subscribes(tmdb_id, media_type, season)
        if not subscribes:
            logger.info(
                "115sub 占位失败已接收，但未找到可立即搜索的 MoviePilot 订阅%s",
                self._event_log_context({"tmdb_id": tmdb_id, "title": title, "type": media_type, "season": season, "episodes": episodes}),
            )
            return

        for subscribe in subscribes:
            subscribe_id = getattr(subscribe, "id", None)
            if not subscribe_id:
                continue
            key = f"subscribe_search:{subscribe_id}"
            if not self._should_trigger_subscribe_search(key):
                logger.info(
                    "115sub 占位失败触发 MoviePilot 订阅搜索冷却中：订阅ID=%s%s",
                    subscribe_id,
                    self._event_log_context({"tmdb_id": tmdb_id, "title": title, "type": media_type, "season": season, "episodes": episodes}),
                )
                continue

            def run_search(target_subscribe_id=subscribe_id):
                try:
                    from app.scheduler import Scheduler
                    Scheduler().start(
                        job_id="subscribe_search",
                        sid=int(target_subscribe_id),
                        state=None,
                        manual=True,
                    )
                    logger.info(
                        "115sub 占位失败已触发 MoviePilot 订阅立即搜索：订阅ID=%s%s",
                        target_subscribe_id,
                        self._event_log_context({"tmdb_id": tmdb_id, "title": title, "type": media_type, "season": season, "episodes": episodes}),
                    )
                except Exception:
                    return

            threading.Thread(target=run_search, name=f"plugin115sub-search-{subscribe_id}", daemon=True).start()

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
        title = self._payload_title(data)
        episodes = data.get("episodes") or [0 if media_type == "movie" else data.get("episode")]
        if not isinstance(episodes, (list, tuple, set)):
            episodes = [episodes]
        if not tmdb_id:
            return {"success": False, "reason": "missing_tmdb_id"}

        upserted = 0
        normalized_episodes = []
        for ep in episodes:
            try:
                episode = int(ep or 0)
            except Exception:
                continue
            if media_type != "movie" and episode <= 0:
                continue
            if episode not in normalized_episodes:
                normalized_episodes.append(episode)
            self._status_cache[self._status_key(tmdb_id, media_type, season, episode)] = {
                "tmdb_id": tmdb_id,
                "type": media_type,
                "season": season,
                "episode": episode,
                "status": status,
                "title": title,
                "updated_at": data.get("updated_at") or "",
                "source": data.get("source") or "115sub",
            }
            upserted += 1
        logger.info(
            "115sub 转存状态已接收%s，状态=%s",
            self._event_log_context({"tmdb_id": tmdb_id, "title": title, "type": media_type, "season": season, "episodes": episodes}),
            self._status_label(status),
        )
        if self._is_failed_status(status):
            self._trigger_moviepilot_subscribe_search(
                tmdb_id=tmdb_id,
                media_type=media_type,
                season=season,
                episodes=normalized_episodes,
                title=title,
            )
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
        if not self._payload_tmdb_id(data):
            event_context = self._event_log_context(data)
            log_key = "event:download.added:missing_tmdb_id"
            if event_context or self._should_log_warning(log_key):
                logger.info("115sub 原始下载任务事件缺少 TMDB ID，已等待资源下载占位链路%s", event_context)
            return
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
            "title": self._context_title(media, meta),
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
                "115sub 本地状态命中，已拦截 MoviePilot 下载%s，状态=%s",
                self._event_log_context({**payload, "title": payload.get("title") or cached_rows[0].get("title")}),
                self._status_label("completed" if completed else "processing"),
            )
            return

        if not payload.get("tmdb_id") or not payload.get("episodes"):
            reason = "missing_tmdb_id" if not payload.get("tmdb_id") else "missing_episodes"
            logger.info("115sub 下载占位跳过：原因=%s%s", reason, self._event_log_context(payload))
            return

        result = self._query_linkage("/api/v1/moviepilot/linkage/placeholder/check", payload)
        if result.get("success") and result.get("block"):
            data.cancel = True
            data.source = "115sub"
            data.reason = result.get("message") or "115sub 已占位"
            logger.info(
                "115sub 占位命中，已拦截 MoviePilot 下载%s",
                self._event_log_context(payload),
            )
            return

        notify_payload = dict(payload)
        notify_payload.setdefault("event", "download.added")
        self._post("download.added", notify_payload)
