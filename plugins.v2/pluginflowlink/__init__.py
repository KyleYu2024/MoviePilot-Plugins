import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import requests
from app.core.event import Event, eventmanager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType


class PluginFlowLink(_PluginBase):
    plugin_name = "FlowLink"
    plugin_desc = "MoviePilot 整理完成后，将本次新增文件精准通知 FlowLink 上传。"
    plugin_icon = "https://img.andp.cc/icons/upload/fl-logo.png"
    plugin_version = "0.0.2"
    plugin_author = "KyleYu"
    author_url = "https://github.com/KyleYu2024/MoviePilot-Plugins"
    plugin_config_prefix = "pluginflowlink_"
    plugin_order = 20
    auth_level = 1

    _enabled = False
    _base_url = ""
    _api_token = ""
    _task_name = ""
    _path_mappings: List[Tuple[str, str]] = []
    _watch_dirs: List[str] = []
    _precise_endpoint = "/api/transfer/upload/files"
    _scan_endpoint = "/api/transfer/upload/scan"
    _timeout = 10
    _require_existing_file = True
    _expand_directories = False
    _fallback_scan = False

    _path_key_pattern = re.compile(
        r"(path|file|files|target|dest|destination|library|local|new|output)",
        re.IGNORECASE,
    )
    _source_key_pattern = re.compile(r"(source|src|download|origin|original|torrent)", re.IGNORECASE)

    def init_plugin(self, config=None):
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._base_url = str(config.get("base_url") or "").strip().rstrip("/")
        self._api_token = str(config.get("api_token") or "").strip()
        self._task_name = str(config.get("task_name") or "").strip()
        self._precise_endpoint = str(config.get("precise_endpoint") or "/api/transfer/upload/files").strip()
        self._scan_endpoint = str(config.get("scan_endpoint") or "/api/transfer/upload/scan").strip()
        self._timeout = self._positive_int(config.get("timeout"), 10, 1, 120)
        self._require_existing_file = bool(config.get("require_existing_file", True))
        self._expand_directories = bool(config.get("expand_directories", False))
        self._fallback_scan = bool(config.get("fallback_scan", False))
        self._path_mappings = self._parse_path_mappings(config.get("path_mappings"))
        self._watch_dirs = self._parse_path_list(config.get("watch_dirs"))

        if self._enabled:
            logger.info(
                "FlowLink 上传联动已启用：地址=%s，任务=%s，路径映射=%s",
                self._base_url or "未配置",
                self._task_name or "自动匹配",
                len(self._path_mappings),
            )
        else:
            logger.info("FlowLink 上传联动未启用")

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
                                        "props": {"model": "enabled", "label": "启用插件"},
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
                                            "label": "FlowLink 地址",
                                            "placeholder": "http://flowlink:6118",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "api_token",
                                            "label": "FlowLink API Token",
                                            "type": "password",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "task_name",
                                            "label": "FlowLink 上传任务名",
                                            "placeholder": "留空则由 FlowLink 按路径自动匹配",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "watch_dirs",
                                            "label": "MoviePilot 整理后目录",
                                            "placeholder": "/media/Movies\n/media/TV",
                                            "rows": 3,
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "path_mappings",
                                            "label": "路径映射",
                                            "placeholder": "/media=/data/media\n/mnt/library => /media",
                                            "rows": 4,
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                ],
            },
        ], {
            "enabled": False,
            "base_url": "http://flowlink:6118",
            "api_token": "",
            "task_name": "",
            "watch_dirs": "",
            "path_mappings": "",
            "require_existing_file": True,
            "expand_directories": False,
            "fallback_scan": False,
            "precise_endpoint": "/api/transfer/upload/files",
            "scan_endpoint": "/api/transfer/upload/scan",
            "timeout": 10,
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        pass

    @eventmanager.register(EventType.TransferComplete)
    def transfer_complete(self, event: Event):
        if not self._enabled:
            return
        if not self._base_url:
            logger.warning("FlowLink 上传联动未配置地址，跳过整理完成事件")
            return

        data = self._jsonable(event.event_data or {})
        moviepilot_paths = self._extract_transfer_files(data)
        if not moviepilot_paths:
            logger.info("FlowLink 上传联动未从整理完成事件中提取到文件级路径")
            if self._fallback_scan:
                self._post_scan()
            return

        flowlink_paths = []
        seen = set()
        for path in moviepilot_paths:
            mapped = self._map_path(path)
            if mapped and mapped not in seen:
                seen.add(mapped)
                flowlink_paths.append(mapped)

        if not flowlink_paths:
            logger.info("FlowLink 上传联动路径过滤后没有可通知文件")
            return

        if self._post_files(flowlink_paths):
            logger.info("FlowLink 精确上传通知成功：%s 个文件", len(flowlink_paths))
        elif self._fallback_scan:
            self._post_scan()

    def _post_files(self, paths: List[str]) -> bool:
        payload = {
            "task_name": self._task_name or None,
            "paths": paths,
            "source": "moviepilot",
            "event": "transfer.complete",
        }
        try:
            response = requests.post(
                self._url(self._precise_endpoint),
                headers=self._headers(),
                params=self._token_params(),
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
            result = response.json() if response.content else {}
            if isinstance(result, dict) and result.get("ok") is False:
                logger.warning("FlowLink 精确上传通知失败：%s", result)
                return False
            return True
        except Exception as exc:
            logger.warning("FlowLink 精确上传通知失败：%s", self._error_summary(exc))
            return False

    def _post_scan(self):
        payload = {"task_name": self._task_name or None}
        try:
            response = requests.post(
                self._url(self._scan_endpoint),
                headers=self._headers(),
                params=self._token_params(),
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
            result = response.json() if response.content else {}
            queued = result.get("queued") if isinstance(result, dict) else ""
            logger.info("FlowLink 上传扫描回退已触发：queued=%s", queued)
        except Exception as exc:
            logger.warning("FlowLink 上传扫描回退失败：%s", self._error_summary(exc))

    def _extract_transfer_files(self, data: Any) -> List[str]:
        paths = []
        for raw in self._iter_path_candidates(data):
            normalized = self._normalize_path(raw)
            if not normalized:
                continue
            path = Path(normalized)
            if self._watch_dirs and not self._under_any_dir(normalized, self._watch_dirs):
                continue
            if path.is_dir():
                if self._expand_directories:
                    paths.extend(self._walk_files(path))
                continue
            if self._require_existing_file and not path.is_file():
                continue
            paths.append(normalized)
        return self._dedupe(paths)

    def _iter_path_candidates(self, value: Any, key: str = "", depth: int = 0) -> Iterable[str]:
        if depth > 8 or value is None:
            return
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                child_key = str(child_key)
                if self._source_key_pattern.search(child_key) and not self._targetish_key(child_key):
                    continue
                yield from self._iter_path_candidates(child_value, child_key, depth + 1)
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                yield from self._iter_path_candidates(item, key, depth + 1)
            return
        if isinstance(value, Path):
            yield str(value)
            return
        if isinstance(value, str) and self._targetish_key(key) and self._looks_like_path(value):
            yield value

    def _targetish_key(self, key: str) -> bool:
        if not key:
            return False
        return bool(self._path_key_pattern.search(key))

    @staticmethod
    def _looks_like_path(value: str) -> bool:
        text = str(value or "").strip()
        return bool(text) and (text.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", text))

    @staticmethod
    def _normalize_path(value: str) -> str:
        text = str(value or "").strip().strip('"').strip("'")
        if not text:
            return ""
        return str(Path(text))

    def _map_path(self, path: str) -> str:
        normalized = self._normalize_path(path)
        for source, target in self._path_mappings:
            if normalized == source or normalized.startswith(source.rstrip("/") + "/"):
                suffix = normalized[len(source.rstrip("/")) :].lstrip("/")
                return str(Path(target) / suffix) if suffix else target
        return normalized

    @staticmethod
    def _under_any_dir(path: str, dirs: List[str]) -> bool:
        normalized = str(Path(path))
        for root in dirs:
            root = str(Path(root))
            if normalized == root or normalized.startswith(root.rstrip("/") + "/"):
                return True
        return False

    @staticmethod
    def _walk_files(root: Path) -> List[str]:
        files = []
        try:
            for item in root.rglob("*"):
                if item.is_file():
                    files.append(str(item))
        except Exception:
            return []
        return files

    @staticmethod
    def _dedupe(values: Iterable[str]) -> List[str]:
        result = []
        seen = set()
        for value in values:
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result

    @staticmethod
    def _parse_path_list(value: Any) -> List[str]:
        if isinstance(value, list):
            items = value
        else:
            items = re.split(r"[\n,]+", str(value or ""))
        return [str(Path(item.strip())) for item in items if str(item or "").strip()]

    @classmethod
    def _parse_path_mappings(cls, value: Any) -> List[Tuple[str, str]]:
        mappings = []
        for line in re.split(r"[\n]+", str(value or "")):
            text = line.strip()
            if not text:
                continue
            if "=>" in text:
                source, target = text.split("=>", 1)
            elif "=" in text:
                source, target = text.split("=", 1)
            else:
                continue
            source = cls._normalize_path(source)
            target = cls._normalize_path(target)
            if source and target:
                mappings.append((source.rstrip("/"), target.rstrip("/")))
        mappings.sort(key=lambda item: len(item[0]), reverse=True)
        return mappings

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_token:
            headers["X-Api-Token"] = self._api_token
            headers["Authorization"] = f"Bearer {self._api_token}"
        return headers

    def _token_params(self) -> Dict[str, str]:
        return {"token": self._api_token} if self._api_token else {}

    def _url(self, endpoint: str) -> str:
        endpoint = endpoint or ""
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            return endpoint
        return f"{self._base_url}/{endpoint.lstrip('/')}"

    @staticmethod
    def _positive_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except Exception:
            parsed = default
        return max(minimum, min(maximum, parsed))

    @staticmethod
    def _error_summary(exc: Exception) -> str:
        response = getattr(exc, "response", None)
        if response is not None:
            return f"HTTP {response.status_code} {response.reason}".strip()
        return f"{type(exc).__name__}: {exc}"

    @classmethod
    def _jsonable(cls, value: Any):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {str(key): cls._jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [cls._jsonable(item) for item in value]
        if hasattr(value, "model_dump"):
            try:
                return cls._jsonable(value.model_dump())
            except Exception:
                pass
        if hasattr(value, "dict"):
            try:
                return cls._jsonable(value.dict())
            except Exception:
                pass
        if hasattr(value, "__dict__"):
            try:
                return {
                    str(key): cls._jsonable(item)
                    for key, item in vars(value).items()
                    if not str(key).startswith("_")
                }
            except Exception:
                pass
        try:
            return json.loads(json.dumps(value, default=str, ensure_ascii=False))
        except Exception:
            return str(value)
