import base64
import hashlib
import html
import json
import logging
import os
import random
import re
import ssl
import struct
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib import parse, request

from app.core.cache import TTLCache
from app.core.config import settings
from app.plugins import _PluginBase
from app.schemas import NotificationType

try:
    from app.events import EventType, eventmanager
except ImportError:
    from app.core.event import eventmanager
    from app.schemas.types import EventType


VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m2ts", ".webm", ".iso"}
SUBTITLE_EXTS = {"ass", "ssa", "srt"}
SUBTITLE_EXTS_TUPLE = (".srt", ".sub", ".smi", ".ssa", ".ass", ".sup")
ARCHIVE_EXTS = (".zip", ".7z", ".tar", ".bz2", ".rar", ".gz", ".xz", ".iso", ".tgz", ".tbz2", ".cbr")
LANG_ALIASES = {
    "zh": "chi",
    "zh-cn": "chi",
    "zh-tw": "chi",
    "zh-hk": "chi",
    "zho": "chi",
    "chi": "chi",
    "chs": "chi",
    "cht": "chi",
    "cn": "chi",
    "en": "eng",
    "eng": "eng",
}
LANG_SUFFIX = {"chi": "zh-CN", "eng": "en"}

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


@dataclass
class SubtitleCandidate:
    source: str
    name: str
    url: str
    ext: str
    language: str
    score: float = 0
    hash_match: bool = False
    detail_url: str = ""
    tags: Dict[str, Any] = field(default_factory=dict)


class MeiamSubtitles(_PluginBase):
    plugin_name = "Meiam 自动字幕"
    plugin_desc = "入库后自动从射手网、迅雷看看、SubHD、Zimuku 下载同名字幕"
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/autosubtitles.jpeg"
    plugin_version = "1.2.4"
    plugin_author = "Meiam/mm"
    auth_level = 1

    _enabled = False
    _notify = True
    _overwrite = False
    _sources = "shooter,thunder,subhd,zimuku"
    _languages = "chi"
    _max_depth = 2
    _min_size_mb = 50
    _timeout = 30
    _manual_path = ""
    _auto_delay_min = 0
    _auto_delay_max = 0
    _enable_ai_filter = False
    _ai_base_url = "https://api.openai.com/v1"
    _ai_model = "gpt-4o-mini"
    _ai_api_key = ""
    _ai_timeout = 20
    _ai_top_n = 5

    _task_lock = threading.RLock()

    def init_plugin(self, config: dict = None):
        self.cache = TTLCache(region="MeiamSubtitles", maxsize=500, ttl=86400)
        self._setup_logger()
        self._check_dependencies()

        if config:
            self._enabled = config.get("enabled", False)
            self._notify = config.get("notify", True)
            self._overwrite = config.get("overwrite", False)
            self._sources = config.get("sources", "shooter,thunder,subhd,zimuku")
            self._languages = config.get("languages", "chi")
            self._max_depth = self._safe_int(config.get("max_depth"), 2)
            self._min_size_mb = self._safe_int(config.get("min_size_mb"), 50)
            self._timeout = self._safe_int(config.get("timeout"), 30)
            self._manual_path = config.get("manual_path", "")
            self._auto_delay_min = self._safe_int(config.get("auto_delay_min"), 0)
            self._auto_delay_max = self._safe_int(config.get("auto_delay_max"), 0)
            self._enable_ai_filter = self._safe_bool(config.get("enable_ai_filter"), False)
            self._ai_base_url = config.get("ai_base_url", "https://api.openai.com/v1")
            self._ai_model = config.get("ai_model", "gpt-4o-mini")
            self._ai_api_key = config.get("ai_api_key", "")
            self._ai_timeout = self._safe_int(config.get("ai_timeout"), 20)
            self._ai_top_n = self._safe_int(config.get("ai_top_n"), 5)

    def _check_dependencies(self):
        """检查必要的 Python 依赖是否已安装"""
        missing = []
        try:
            import requests  # noqa: F401
        except ImportError:
            missing.append("requests")
        try:
            import bs4  # noqa: F401
        except ImportError:
            missing.append("beautifulsoup4")
        if missing:
            self._logger.error("缺少依赖: %s — SubHD/Zimuku 搜索将不可用，请安装: pip install %s",
                ", ".join(missing), " ".join(missing))
        else:
            self._logger.info("依赖检查通过 (requests, beautifulsoup4)")

    def _setup_logger(self):
        log_dir = Path(getattr(settings, "LOG_PATH", "/moviepilot/logs")) / "plugins"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger(f"plugin.{self.__class__.__name__}")
        self._logger.setLevel(logging.INFO)
        # 避免重复添加 handler（插件重载时）
        if not self._logger.handlers:
            # 文件日志
            fh = logging.FileHandler(log_dir / "meiam_subtitles.log", encoding="utf-8")
            fh.setLevel(logging.INFO)
            fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
            self._logger.addHandler(fh)
            # 控制台日志（MoviePilot 主日志可见）
            sh = logging.StreamHandler()
            sh.setLevel(logging.INFO)
            sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
            self._logger.addHandler(sh)

    def get_state(self) -> bool:
        return self._enabled

    def stop_service(self):
        pass

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
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用入库自动下载",
                                            "hint": "监听 MoviePilot 转移完成事件，自动下载字幕。",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "notify",
                                            "label": "发送通知",
                                            "hint": "下载成功或失败后发送插件通知。",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "overwrite",
                                            "label": "覆盖已有字幕",
                                            "hint": "关闭时，同名字幕已存在会跳过。",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "timeout",
                                            "label": "请求超时(秒)",
                                            "type": "number",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VAlert",
                        "props": {"type": "success", "variant": "tonal", "class": "mt-2"},
                        "text": "AI 测速接口：/api/v1/plugin/MeiamSubtitles/test_ai；会使用当前 Base URL、模型和 API Key 发起一次极小请求。",
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "sources",
                                            "label": "字幕来源",
                                            "chips": True,
                                            "multiple": True,
                                            "items": [
                                                {"title": "射手网", "value": "shooter"},
                                                {"title": "迅雷看看", "value": "thunder"},
                                                {"title": "SubHD", "value": "subhd"},
                                                {"title": "Zimuku", "value": "zimuku"},
                                            ],
                                            "hint": "推荐同时启用所有来源。射手/迅雷通过文件哈希匹配；SubHD/Zimuku 通过豆瓣元数据精确搜索，资源更丰富。",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "languages",
                                            "label": "字幕语言",
                                            "chips": True,
                                            "multiple": True,
                                            "items": [
                                                {"title": "中文", "value": "chi"},
                                                {"title": "英文", "value": "eng"},
                                            ],
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 2},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "max_depth",
                                            "label": "目录扫描深度",
                                            "type": "number",
                                            "hint": "事件给出目录时向下查找视频。",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 2},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "min_size_mb",
                                            "label": "最小体积(MB)",
                                            "type": "number",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VAlert",
                        "props": {"type": "info", "variant": "tonal", "class": "mt-2"},
                        "text": "字幕会保存为视频同目录同名文件，例如 Movie.zh-CN.srt；如已有同语言字幕且未开启覆盖，会自动跳过。",
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "auto_delay_min",
                                            "label": "自动延时最小值(秒)",
                                            "type": "number",
                                            "hint": "入库自动任务每个视频处理前随机等待。",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "auto_delay_max",
                                            "label": "自动延时最大值(秒)",
                                            "type": "number",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enable_ai_filter",
                                            "label": "启用 AI 筛选",
                                            "hint": "候选字幕较多时，让 AI 根据文件名和候选标题重排。",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "ai_top_n",
                                            "label": "AI 筛选候选数",
                                            "type": "number",
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
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "ai_base_url",
                                            "label": "AI Base URL",
                                            "placeholder": "https://api.openai.com/v1",
                                            "hint": "兼容 OpenAI Chat Completions；可填写 /v1 或完整 /chat/completions。",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "ai_model",
                                            "label": "AI 模型",
                                            "placeholder": "gpt-4o-mini",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "ai_api_key",
                                            "label": "AI API Key",
                                            "type": "password",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 2},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "ai_timeout",
                                            "label": "AI 超时(秒)",
                                            "type": "number",
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
                                "props": {"cols": 12, "md": 8},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "manual_path",
                                            "label": "手动下载路径",
                                            "placeholder": "/media/Movies/Movie.mkv 或 /media/TV/Show/Season 01",
                                            "hint": "保存配置后，可通过插件 API /manual_download?path=... 手动触发；路径可以是视频文件或目录。",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {"type": "success", "variant": "tonal"},
                                        "text": "远程命令：/meiam_subtitles；API：/api/v1/plugin/MeiamSubtitles/manual_download",
                                    }
                                ],
                            },
                        ],
                    },
                ],
            }
        ], {
            "enabled": self._enabled,
            "notify": self._notify,
            "overwrite": self._overwrite,
            "sources": self._split_config(self._sources),
            "languages": self._split_config(self._languages),
            "max_depth": self._max_depth,
            "min_size_mb": self._min_size_mb,
            "timeout": self._timeout,
            "manual_path": self._manual_path,
            "auto_delay_min": self._auto_delay_min,
            "auto_delay_max": self._auto_delay_max,
            "enable_ai_filter": self._enable_ai_filter,
            "ai_base_url": self._ai_base_url,
            "ai_model": self._ai_model,
            "ai_api_key": self._ai_api_key,
            "ai_timeout": self._ai_timeout,
            "ai_top_n": self._ai_top_n,
        }

    def get_page(self) -> List[dict]:
        try:
            records = self.cache.get("records") or []
        except Exception:
            records = []
        rows = [
            {
                "component": "tr",
                "content": [
                    {"component": "td", "text": item.get("time", "")},
                    {"component": "td", "text": item.get("video", "")},
                    {"component": "td", "text": item.get("language", "")},
                    {"component": "td", "text": item.get("source", "")},
                    {"component": "td", "text": item.get("status", "")},
                    {"component": "td", "text": item.get("path", "")},
                ],
            }
            for item in records[-50:]
        ]
        return [
            {
                "component": "VTable",
                "props": {"density": "compact"},
                "content": [
                    {
                        "component": "thead",
                        "content": [
                            {
                                "component": "tr",
                                "content": [
                                    {"component": "th", "text": "时间"},
                                    {"component": "th", "text": "视频"},
                                    {"component": "th", "text": "语言"},
                                    {"component": "th", "text": "来源"},
                                    {"component": "th", "text": "状态"},
                                    {"component": "th", "text": "字幕路径"},
                                ],
                            }
                        ],
                    },
                    {"component": "tbody", "content": rows},
                ],
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/manual_download",
                "endpoint": self.manual_download,
                "methods": ["GET"],
                "summary": "手动下载指定媒体字幕",
                "auth": "bear",
            },
            {
                "path": "/manual_download_saved",
                "endpoint": self.manual_download_saved,
                "methods": ["GET"],
                "summary": "按配置里的手动下载路径执行",
                "auth": "bear",
            },
            {
                "path": "/test_ai",
                "endpoint": self.test_ai,
                "methods": ["GET"],
                "summary": "AI 接口测速",
                "auth": "bear",
            },
        ]

    def get_command(self) -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/meiam_subtitles",
                "event": EventType.PluginAction,
                "desc": "手动下载指定影视字幕",
                "category": "字幕",
                "data": {
                    "action": "meiam_subtitles_manual",
                },
            }
        ]

    @eventmanager.register(EventType.TransferComplete)
    def on_transfer_complete(self, event: Any):
        if not self._enabled:
            return
        event_data = getattr(event, "event_data", None)
        threading.Thread(
            target=self._handle_transfer_event,
            args=(event_data,),
            name="meiam-subtitles-transfer",
            daemon=True,
        ).start()

    def _handle_transfer_event(self, event_data: Any):
        with self._task_lock:
            videos = self._extract_video_paths(event_data)
            if not videos:
                self._logger.info("未从 TransferComplete 事件中找到可处理的视频文件")
                return

            ok_count = 0
            fail_count = 0
            for video in videos:
                self._sleep_auto_delay()
                for language in self._configured_languages():
                    success, message = self.download_for_video(video, language)
                    if success:
                        ok_count += 1
                    else:
                        fail_count += 1
                    self._logger.info("%s | %s | %s", video.name, language, message)

            if self._notify:
                self._send_notify(
                    title="Meiam 自动字幕",
                    text=f"入库字幕任务完成：处理 {len(videos)} 个视频，成功 {ok_count} 个，失败/跳过 {fail_count} 个。",
                )

    @eventmanager.register(EventType.PluginAction)
    def command_action(self, event: Any):
        event_data = getattr(event, "event_data", None) or {}
        if event_data.get("action") != "meiam_subtitles_manual":
            return

        channel = event_data.get("channel")
        userid = event_data.get("user") or event_data.get("userid")
        path = (
            event_data.get("path")
            or event_data.get("args")
            or event_data.get("arg")
            or event_data.get("text")
            or self._manual_path
        )

        if isinstance(path, str):
            path = path.replace("/meiam_subtitles", "", 1).strip()

        if not path:
            self._send_notify(
                title="Meiam 自动字幕",
                text="请提供要下载字幕的视频文件或目录路径，例如：/meiam_subtitles /media/Movies/Movie.mkv",
                channel=channel,
                userid=userid,
            )
            return

        threading.Thread(
            target=self._run_manual_task,
            args=(str(path), None, channel, userid),
            name="meiam-subtitles-manual",
            daemon=True,
        ).start()

    def manual_download_saved(self) -> Dict[str, Any]:
        if not self._manual_path:
            return {"success": False, "message": "未配置手动下载路径"}
        return self.manual_download(path=self._manual_path)

    def manual_download(self, path: str = "", languages: str = "", notify: bool = True) -> Dict[str, Any]:
        if not path:
            return {"success": False, "message": "请通过 path 参数指定视频文件或目录"}
        return self._run_manual_task(path=path, languages=languages, notify=self._safe_bool(notify, True))

    def test_ai(self) -> Dict[str, Any]:
        if not self._ai_api_key:
            return {"success": False, "message": "未配置 AI API Key"}
        if not self._ai_model:
            return {"success": False, "message": "未配置 AI 模型"}

        started = time.time()
        content = self._ai_chat(
            messages=[
                {"role": "system", "content": "你是接口测速助手，只返回 OK。"},
                {"role": "user", "content": "ping"},
            ],
            max_tokens=8,
            temperature=0,
        )
        elapsed_ms = int((time.time() - started) * 1000)
        success = bool(content)
        message = f"AI 测速{'成功' if success else '失败'}，耗时 {elapsed_ms}ms"
        if success:
            message += f"，返回：{content[:80]}"
        self.cache.set("ai_test", {"success": success, "elapsed_ms": elapsed_ms, "message": message})
        if self._notify:
            self._send_notify("Meiam 自动字幕", message)
        return {"success": success, "elapsed_ms": elapsed_ms, "message": message}

    def _run_manual_task(
        self,
        path: str,
        languages: Optional[str] = None,
        channel: Any = None,
        userid: Any = None,
        notify: bool = True,
    ) -> Dict[str, Any]:
        with self._task_lock:
            target = Path(path)
            video_set: Set[Path] = set()
            self._add_path_candidate(target, video_set)
            videos = sorted(video_set, key=lambda item: str(item))

            if not videos:
                result = {"success": False, "message": f"未找到可处理的视频：{path}"}
                if notify:
                    self._send_notify("Meiam 自动字幕", result["message"], channel=channel, userid=userid)
                return result

            lang_list = (
                [self._normalize_language(item) for item in self._split_config(languages)]
                if languages
                else self._configured_languages()
            )
            lang_list = [item for item in lang_list if item in {"chi", "eng"}] or ["chi"]

            ok_count = 0
            failed: List[str] = []
            downloaded: List[str] = []
            for video in videos:
                for language in lang_list:
                    success, message = self.download_for_video(video, language)
                    if success:
                        ok_count += 1
                        downloaded.append(f"{video.name} [{language}] {message}")
                    else:
                        failed.append(f"{video.name} [{language}] {message}")

            lines = [f"手动字幕任务完成：处理 {len(videos)} 个视频，成功 {ok_count} 个，失败/跳过 {len(failed)} 个。"]
            if downloaded:
                lines.append("成功：\n" + "\n".join(downloaded[:10]))
            if failed:
                lines.append("失败/跳过：\n" + "\n".join(failed[:10]))
            message = "\n\n".join(lines)

            if notify:
                self._send_notify("Meiam 自动字幕", message, channel=channel, userid=userid)

            return {
                "success": ok_count > 0,
                "message": message,
                "total": len(videos),
                "success_count": ok_count,
                "failed_count": len(failed),
            }

    def _send_notify(
        self,
        title: str,
        text: str,
        channel: Any = None,
        userid: Any = None,
    ):
        try:
            kwargs = {
                "mtype": NotificationType.Plugin,
                "title": title,
                "text": text,
            }
            if channel:
                kwargs["channel"] = channel
            if userid:
                kwargs["userid"] = userid
            self.post_message(**kwargs)
        except TypeError:
            self.post_message(mtype=NotificationType.Plugin, title=title, text=text)

    def download_for_video(self, video: Path, language: str = "chi") -> Tuple[bool, str]:
        if not video.exists() or video.suffix.lower() not in VIDEO_EXTS:
            return False, "不是有效视频文件"
        if video.stat().st_size < self._min_size_mb * 1024 * 1024:
            return False, "视频体积小于最小阈值"

        language = self._normalize_language(language)
        existing = self._existing_subtitles(video, language)
        if existing and not self._overwrite:
            self._record(video, language, "", "已存在", str(existing[0]))
            return False, f"已存在字幕: {existing[0].name}"

        candidates = self._search(video, language)
        if not candidates:
            self._record(video, language, "", "未找到", "")
            return False, "未搜索到字幕"

        # 按源分组，每个源只取排名第一的候选，避免同一源反复请求
        seen_sources = set()
        best_per_source = []
        for c in candidates:
            if c.source not in seen_sources:
                seen_sources.add(c.source)
                best_per_source.append(c)

        # 依次尝试不同源
        for i, candidate in enumerate(best_per_source):
            self._logger.info("尝试源[%d/%d]: %s %s", i + 1, len(best_per_source), candidate.source, candidate.name[:40])

            if candidate.source == "SubHD":
                content = self._download_subhd(candidate)
            elif candidate.source == "Zimuku":
                content = self._download_zimuku(candidate)
            else:
                content = self._http_bytes(candidate.url)

            if content:
                sub_path = self._subtitle_path(video, candidate.ext, language)
                sub_path.write_bytes(content)
                self._record(video, language, candidate.source, "已下载", str(sub_path))
                if i > 0:
                    return True, f"回退下载成功 {candidate.source}: {sub_path.name}"
                return True, f"已下载 {candidate.source}: {sub_path.name}"

            self._logger.info("源 %s 下载失败，切换到下一个源", candidate.source)

        self._record(video, language, best_per_source[0].source, "下载失败", best_per_source[0].url)
        return False, "字幕下载失败（所有源均失败）"

    def _search(self, video: Path, language: str) -> List[SubtitleCandidate]:
        candidates: List[SubtitleCandidate] = []
        sources = self._configured_sources()
        if "shooter" in sources and language in {"chi", "eng"}:
            candidates.extend(self._search_shooter(video, language))
        if "thunder" in sources and language == "chi":
            candidates.extend(self._search_thunder(video, language))

        # SubHD/Zimuku 使用豆瓣元数据精确搜索
        need_douban = ("subhd" in sources or "zimuku" in sources) and language == "chi"
        douban_info = self._search_douban(video) if need_douban else None
        if "subhd" in sources and language == "chi":
            candidates.extend(self._search_subhd(video, language, douban_info))
        if "zimuku" in sources and language == "chi":
            candidates.extend(self._search_zimuku(video, language, douban_info))

        sorted_candidates = sorted(
            candidates,
            key=lambda item: (
                item.hash_match,
                self._lang_tier(item),
                self._name_similarity(video.name, item.name),
                self._quality_score(item.name),
                self._format_priority(item.ext),
                item.score,
            ),
            reverse=True,
        )
        self._logger.info("搜索完成: %s | 共 %d 条候选 (射手:%d 迅雷:%d SubHD:%d Zimuku:%d)",
            video.name, len(sorted_candidates),
            sum(1 for c in candidates if c.source == "射手"),
            sum(1 for c in candidates if c.source == "迅雷"),
            sum(1 for c in candidates if c.source == "SubHD"),
            sum(1 for c in candidates if c.source == "Zimuku"))
        return self._ai_filter_candidates(video, sorted_candidates) if self._enable_ai_filter else sorted_candidates

    def _search_shooter(self, video: Path, language: str) -> List[SubtitleCandidate]:
        file_hash = self._shooter_hash(video)
        if not file_hash:
            return []

        body = parse.urlencode(
            {
                "filehash": file_hash,
                "pathinfo": str(video),
                "format": "json",
                "lang": "chn" if language == "chi" else "eng",
            }
        ).encode("utf-8")
        headers = {
            "User-Agent": "MeiamSub.Shooter",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "*/*",
        }

        try:
            raw = self._http_bytes("https://www.shooter.cn/api/subapi.php", data=body, headers=headers)
            if not raw:
                return []
            text = raw.decode("utf-8", errors="ignore").strip()
            if not text.startswith("["):
                return []
            data = json.loads(text)
        except Exception as err:
            self._logger.warning("射手字幕搜索失败: %s", err)
            return []

        results: List[SubtitleCandidate] = []
        for item in data or []:
            for sub_file in item.get("Files") or item.get("files") or []:
                url = sub_file.get("Link") or sub_file.get("link")
                ext = self._extract_format(sub_file.get("Ext") or sub_file.get("ext"))
                if not url or not ext:
                    continue
                results.append(
                    SubtitleCandidate(
                        source="射手",
                        name=f"{Path(parse.urlparse(url).path).name} | {language} | 射手",
                        url=url,
                        ext=ext,
                        language=language,
                        score=100,
                        hash_match=True,
                    )
                )
        return results

    def _search_thunder(self, video: Path, language: str) -> List[SubtitleCandidate]:
        cid = self._thunder_cid(video)
        api_url = "https://api-shoulei-ssl.xunlei.com/oracle/subtitle?" + parse.urlencode({"name": video.name})
        try:
            raw = self._http_bytes(api_url, headers={"User-Agent": "MeiamSub.Thunder", "Accept": "*/*"})
            if not raw:
                return []
            data = json.loads(raw.decode("utf-8", errors="ignore"))
        except Exception as err:
            self._logger.warning("迅雷字幕搜索失败: %s", err)
            return []

        if data.get("Code", data.get("code")) != 0:
            return []

        results: List[SubtitleCandidate] = []
        for item in data.get("Data") or data.get("data") or []:
            url = item.get("Url") or item.get("url")
            ext = self._extract_format(item.get("Ext") or item.get("ext"))
            name = item.get("Name") or item.get("name") or ""
            if not url or not ext or not name:
                continue
            item_cid = item.get("Cid") or item.get("cid")
            fp_score = item.get("FingerprintfScore") or item.get("fingerprintfScore") or 0
            score = item.get("Score") or item.get("score") or 0
            languages = item.get("Languages") or item.get("languages") or []
            lang_text = ",".join(languages) if isinstance(languages, list) else str(languages or "")
            results.append(
                SubtitleCandidate(
                    source="迅雷",
                    name=f"{name} | {lang_text} | 迅雷",
                    url=url,
                    ext=ext,
                    language=language,
                    score=float(fp_score or 0) + float(score or 0),
                    hash_match=bool(cid and item_cid and cid.lower() == str(item_cid).lower()),
                )
            )
        return results

    # ── 豆瓣元数据解析 ──────────────────────────────────────────────

    def _search_douban(self, video: Path) -> Optional[Dict[str, Any]]:
        """通过豆瓣解析影片元数据，返回 {id, title, year, type} 或 None"""
        title = self._extract_title(video)
        if not title:
            self._logger.info("豆瓣: 无法从文件名提取标题: %s", video.name)
            return None
        queries = [title]
        if video.parent.name:
            parent_title = re.sub(r"(?i)\b(season\s*\d+|s\d+|第.季)\b", "", video.parent.name).strip()
            if parent_title and parent_title != title:
                queries.insert(0, parent_title)
        for query in queries:
            self._logger.info("豆瓣: 搜索 '%s'", query)
            result = self._douban_search(query)
            if result:
                self._logger.info("豆瓣: 找到 %s (ID:%s, %s)", result.get("title"), result.get("id"), result.get("type"))
                return result
        self._logger.warning("豆瓣: 所有查询均未找到结果")
        return None

    def _douban_search(self, query: str) -> Optional[Dict[str, Any]]:
        """搜索豆瓣并返回第一个匹配结果"""
        ssl_ctx = ssl._create_unverified_context()
        headers = {
            **DEFAULT_HEADERS,
            "Referer": "https://movie.douban.com/",
        }
        for page in range(3):
            params = {"search_text": query, "cat": "1002", "start": str(page * 15)}
            url = f"https://search.douban.com/movie/subject_search?{parse.urlencode(params)}"
            try:
                req = request.Request(url, headers=headers)
                with request.urlopen(req, context=ssl_ctx, timeout=10) as resp:
                    if resp.status != 200:
                        break
                    html_text = resp.read().decode("utf-8", errors="ignore")
            except Exception as err:
                self._logger.warning("豆瓣搜索请求失败 '%s': %s", query, err)
                break

            match = re.search(r"window\.__DATA__\s*=\s*({.+?});", html_text, re.DOTALL)
            if not match:
                continue
            try:
                data = json.loads(match.group(1).strip())
            except Exception:
                continue

            for item in data.get("items", []):
                if item.get("tpl_name") != "search_subject":
                    continue
                sid = item.get("id")
                if not sid:
                    continue
                full_title = item.get("title", "").strip()
                year_match = re.search(r"\((\d{4})\)", full_title)
                year = year_match.group(1) if year_match else None
                more_url = item.get("more_url", "")
                res_type = "tv" if "is_tv:'1'" in more_url else "movie"
                return {"id": str(sid), "title": full_title, "year": year, "type": res_type}
        return None

    @staticmethod
    def _extract_title(video: Path) -> str:
        """从文件名提取影片标题（去除编码信息等，保留中文片名）"""
        name = video.stem
        # 只去除明确的编码/质量标签，保留中文和数字
        name = re.sub(r"[\.\-_]?(1080[pi]|720p|2160p|4K|BluRay|BDRip|WEBRip|HDRip|DVDRip|H\.?264|H\.?265|HEVC|x264|x265|AAC|DTS|FLAC|AC3|REMUX|AMZN|NF|ATVP|DSNP)", "", name, flags=re.IGNORECASE)
        name = re.sub(r"[\.\-_]?(S\d{1,2}E\d{1,3}|E\d{1,3}|EP\d{1,3})", "", name, flags=re.IGNORECASE)
        # 用点、下划线、空格分隔，取前面有意义的部分
        parts = re.split(r"[\.\_\s]+", name.strip())
        # 过滤掉纯数字年份（4位）和编码相关短词，但保留中文和有意义的英文
        meaningful = []
        for p in parts:
            if not p:
                continue
            # 跳过纯4位数字年份
            if re.match(r"^\d{4}$", p):
                continue
            # 跳过方括号内容（如 [BD]、[FLAC]）
            if re.match(r"^[\[\(\{].*[\]\)\}]$", p):
                continue
            meaningful.append(p)
        title = " ".join(meaningful)[:50]
        return title.strip()

    # ── SubHD 字幕源 ────────────────────────────────────────────────

    def _search_subhd(self, video: Path, language: str, douban_info: Optional[Dict] = None) -> List[SubtitleCandidate]:
        """从 SubHD 搜索字幕（优先用豆瓣 ID，回退用标题搜索）"""
        session = None
        try:
            import requests as _requests
            session = _requests.Session()
            session.headers.update(DEFAULT_HEADERS)

            search_id = None
            if douban_info:
                search_id = douban_info.get("id")
                self._logger.info("SubHD: 尝试豆瓣 ID %s", search_id)

            # 策略 1: 用豆瓣 ID 搜索
            detail_url = None
            if search_id:
                resp = session.get(f"https://subhd.tv/search/{search_id}", timeout=self._timeout)
                if resp.status_code == 200:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(resp.text, "html.parser")
                    container = soup.select_one("div.col-lg-9")
                    if container:
                        link = container.select_one('a[href*="/d/"]')
                        if link:
                            m = re.search(r"/d/(\w+)", link.get("href", ""))
                            if m:
                                detail_url = f"https://subhd.tv/d/{m.group(1)}"
                                self._logger.info("SubHD: 豆瓣 ID 映射到 %s", detail_url)

            # 策略 2: 用标题搜索（回退）
            if not detail_url:
                title = self._extract_title(video) if not douban_info else None
                if not title and douban_info:
                    title = douban_info.get("title", "").split("(")[0].strip()
                if not title:
                    title = self._extract_title(video)
                if title:
                    self._logger.info("SubHD: 标题搜索 '%s'", title)
                    resp = session.get(f"https://subhd.tv/search/{parse.quote(title)}", timeout=self._timeout)
                    if resp.status_code == 200:
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(resp.text, "html.parser")
                        container = soup.select_one("div.col-lg-9")
                        if container:
                            link = container.select_one('a[href*="/d/"]')
                            if link:
                                m = re.search(r"/d/(\w+)", link.get("href", ""))
                                if m:
                                    detail_url = f"https://subhd.tv/d/{m.group(1)}"

            if not detail_url:
                self._logger.info("SubHD: 未找到字幕页")
                return []

            self._logger.info("SubHD: 字幕页 %s", detail_url)
            resp = session.get(detail_url, timeout=self._timeout)
            if resp.status_code != 200:
                self._logger.warning("SubHD: 字幕页 HTTP %s", resp.status_code)
                return []

            results = self._parse_subhd_subtitles(resp.text, video, douban_info or {})
            self._logger.info("SubHD: 找到 %d 条字幕", len(results))
            return results
        except ImportError as err:
            self._logger.error("SubHD 搜索缺少依赖: %s", err)
            return []
        except Exception as err:
            self._logger.warning("SubHD 搜索失败: %s", err)
            return []
        finally:
            if session:
                session.close()

    def _parse_subhd_subtitles(self, html_text: str, video: Path, douban_info: Dict) -> List[SubtitleCandidate]:
        """解析 SubHD 字幕列表页面"""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_text, "html.parser")
        container = soup.select_one("div.bg-white.shadow-sm.rounded-3.mb-5")
        if not container:
            return []

        results = []
        category = "general"
        for child in container.children:
            if not hasattr(child, "name") or child.name != "div":
                continue
            classes = child.get("class", [])
            if "bg-light" in classes:
                text = child.get_text().strip()
                if "合集" in text:
                    category = "collection"
                elif "第" in text and "集" in text:
                    match = re.search(r"第\s*(\d+)\s*集", text)
                    category = int(match.group(1)) if match else "general"
                else:
                    category = "general"
            elif "row" in classes:
                tags = self._extract_subhd_tags(child.find_all("span"))
                link = child.select_one("a.link-dark")
                if not link:
                    continue
                href = link.get("href", "")
                if not href.startswith("/a/"):
                    continue

                # 剧集过滤
                episode = self._extract_episode(video)
                if episode and category != "collection":
                    if isinstance(category, int) and category != episode:
                        continue

                if category == "collection":
                    tags["collection"] = True

                prod = "剧集" if douban_info.get("type") == "tv" else "电影"
                tags["production"] = prod

                zu = child.select_one('a[href^="/zu/"]') or child.select_one('a[href^="/u/"]')
                if zu:
                    tags["fansub"] = zu.get_text().strip()

                name = link.get_text().strip()
                ext = self._extract_format_from_tags(tags.get("fmt", []))
                lang = "chi" if any(l in tags.get("lang", []) for l in ("chs", "cht")) else "eng"

                results.append(SubtitleCandidate(
                    source="SubHD",
                    name=f"[SubHD] {name}",
                    url=f"https://subhd.tv{href}",
                    ext=ext or "srt",
                    language=lang,
                    score=80,
                    detail_url=f"https://subhd.tv{href}",
                    tags=tags,
                ))
        return results

    @staticmethod
    def _extract_subhd_tags(spans) -> Dict[str, Any]:
        """从 SubHD span 元素提取标签"""
        tags = {"source": [], "lang": [], "fmt": [], "bilingual": False}
        for span in spans:
            classes = span.get("class", [])
            text = span.get_text().strip()
            if "rounded" in classes and "text-white" in classes:
                src_map = {"转载精修": "reprint", "官方字幕": "official", "原创翻译": "original", "机器翻译": "machine", "AI翻润色": "ai"}
                for k, v in src_map.items():
                    if k in text:
                        tags["source"].append(v)
                        break
            if "fw-bold" in classes:
                if "简体" in text:
                    tags["lang"].append("chs")
                if "繁体" in text:
                    tags["lang"].append("cht")
                if "英语" in text:
                    tags["lang"].append("eng")
                if "双语" in text:
                    tags["bilingual"] = True
            if "text-secondary" in classes:
                for fmt in ("ASS", "SRT", "SSA", "SUB", "SUP", "VTT"):
                    if fmt in text.upper():
                        tags["fmt"].append(fmt.lower())
                        break
        return tags

    def _download_subhd(self, candidate: SubtitleCandidate) -> Optional[bytes]:
        """下载 SubHD 字幕（处理验证码）"""
        session = None
        try:
            import requests as _requests
            session = _requests.Session()
            session.headers.update(DEFAULT_HEADERS)

            detail_url = candidate.detail_url or candidate.url
            resp = session.get(detail_url, timeout=self._timeout)
            if resp.status_code != 200:
                return None

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")

            down_btn = soup.find("a", class_="down")
            if not down_btn:
                for a in soup.find_all("a", href=True):
                    if "/down/" in a["href"]:
                        down_btn = a
                        break
            if not down_btn:
                return None

            down_url = down_btn["href"]
            if not down_url.startswith("http"):
                down_url = f"https://subhd.tv{down_url}"

            session.get(down_url, headers={"Referer": detail_url}, timeout=self._timeout)
            sid = down_url.split("/")[-1]

            api_url = "https://subhd.tv/api/sub/down"
            payload = {"sid": sid, "cap": ""}
            res = session.post(api_url, json=payload, headers={"Referer": down_url}, timeout=10)
            if res.status_code != 200:
                return None
            data = res.json()

            if data.get("pass") is False:
                svg = data.get("msg")
                if svg:
                    code = self._solve_subhd_captcha(svg)
                    payload["cap"] = code
                    res = session.post(api_url, json=payload, headers={"Referer": down_url}, timeout=10)
                    data = res.json()
                    if not data.get("success"):
                        return None

            if not data.get("success"):
                return None

            file_url = data.get("url")
            if not file_url:
                return None
            if not file_url.startswith("http"):
                file_url = f"https://subhd.tv{file_url}"

            file_res = session.get(file_url, headers={"Referer": down_url}, timeout=15)
            if file_res.status_code != 200:
                return None

            return self._unpack_subtitle_data(file_res.content, file_res.headers, file_url)
        except Exception as err:
            self._logger.warning("SubHD 下载失败: %s", err)
            return None
        finally:
            if session:
                session.close()

    @staticmethod
    def _solve_subhd_captcha(svg_content: str) -> str:
        """解决 SubHD SVG 验证码"""
        LENGTH_MAP = {
            986: "I", 998: "1", 1068: "I", 1081: "1", 1082: "v",
            1130: "Y", 1134: "Y", 1172: "v", 1224: "Y", 1274: "L",
            1298: "V", 1311: "V", 1360: "i", 1380: "L", 1406: "V",
            1473: "i", 1478: "T", 1491: "r", 1598: "N", 1601: "T",
            1604: "X", 1610: "J", 1613: "x", 1614: "N", 1615: "r",
            1616: "N", 1617: "N", 1618: "N", 1634: "k", 1637: "k",
            1694: "z", 1706: "K", 1709: "K", 1731: "X", 1744: "x",
            1754: "F", 1770: "k", 1835: "z", 1838: "u", 1840: "A",
            1844: "A", 1848: "K", 1850: "Z", 1853: "Z", 1886: "h",
            1900: "F", 1922: "H", 1928: "H", 1960: "P", 1991: "u",
            1993: "A", 1996: "D", 2004: "Z", 2018: "w", 2035: "w",
            2042: "7", 2043: "h", 2080: "j", 2082: "H", 2104: "R",
            2107: "R", 2123: "P", 2140: "4", 2162: "D", 2164: "O",
            2183: "w", 2198: "n", 2199: "C", 2200: "C", 2201: "C",
            2202: "C", 2210: "f", 2212: "7", 2246: "E", 2253: "j",
            2260: "o", 2272: "d", 2279: "R", 2282: "M", 2294: "U",
            2301: "U", 2310: "W", 2318: "W", 2321: "M", 2332: "a",
            2344: "O", 2345: "W", 2346: "W", 2366: "s", 2380: "b",
            2381: "n", 2382: "0", 2394: "f", 2433: "E", 2448: "o",
            2461: "d", 2464: "p", 2466: "M", 2485: "U", 2498: "c",
            2501: "e", 2503: "W", 2512: "q", 2526: "a", 2546: "2",
            2563: "s", 2578: "b", 2580: "0", 2606: "5", 2632: "6",
            2669: "p", 2706: "c", 2709: "e", 2721: "q", 2758: "2",
            2800: "9", 2823: "5", 2851: "6", 3033: "9", 3038: "S",
            3054: "B", 3160: "g", 3244: "Q", 3254: "Q", 3266: "G",
            3291: "S", 3308: "B", 3414: "8", 3423: "g", 3514: "Q",
            3538: "G", 3663: "m", 3667: "m", 3698: "8", 3878: "3",
            3968: "m", 4201: "3",
        }

        def get_all_xy(path):
            return [float(m) for m in re.findall(r"(\d+(?:\.\d*)?)", path)]

        def resolve_collision(length, path):
            vals = get_all_xy(path)
            xs = vals[0::2]
            ys = vals[1::2]
            if not xs:
                return None
            min_y = min(ys)
            move_match = re.search(r"M(\d+(?:\.\d*)?)\s+(\d+(?:\.\d*)?)", path)
            move_y = float(move_match.group(2)) if move_match else 0.0
            w = max(xs) - min(xs)
            if length in (986, 1068):
                return "I" if min_y > 13 else "l"
            if length in (1274, 1380):
                return "y" if move_y > 30 else "L"
            if length in (1610, 1744):
                return "x" if min_y > 19 else "J"
            if length == 1615:
                return "r" if min_y > 18 else "N"
            if length in (2198, 2381):
                return "n" if min_y > 19 else "C"
            if length == 2318:
                return "W" if w > 30 else "4"
            if length in (1598, 1731):
                return "X" if min_y > 13 else "N"
            if length in (1694, 1835):
                return "z" if min_y > 22 else "t"
            if length == 2279:
                return "R" if min_y > 13 else "M"
            return None

        candidates = []
        for m in re.finditer(r'd="([^"]+)"', svg_content):
            d = m.group(1)
            if len(d) > 500:
                x_match = re.search(r"(\d+(?:\.\d*)?)", d)
                start_x = float(x_match.group(1)) if x_match else 0.0
                candidates.append((start_x, d))
        candidates.sort(key=lambda x: x[0])
        result = []
        for _, d in candidates:
            length = len(d)
            char = resolve_collision(length, d)
            if not char:
                char = LENGTH_MAP.get(length, "")
            result.append(char)
        return "".join(result)

    # ── Zimuku 字幕源 ───────────────────────────────────────────────

    def _search_zimuku(self, video: Path, language: str, douban_info: Optional[Dict] = None) -> List[SubtitleCandidate]:
        """从 Zimuku 搜索字幕（优先用豆瓣 ID，回退用标题）"""
        session = None
        try:
            import requests as _requests
            session = _requests.Session()
            session.headers.update(DEFAULT_HEADERS)
            session.mount("https://", _requests.adapters.HTTPAdapter(max_retries=3))

            search_query = None
            if douban_info:
                search_query = str(douban_info.get("id", ""))
                self._logger.info("Zimuku: 搜索豆瓣 ID %s", search_query)
            if not search_query:
                search_query = self._extract_title(video)
                self._logger.info("Zimuku: 标题搜索 '%s'", search_query)
            if not search_query:
                return []

            search_url = f"https://zimuku.org/search?q={parse.quote(search_query)}&chost=zimuku.org"
            resp = self._zimuku_get_page(session, search_url)
            if not resp:
                self._logger.info("Zimuku: 搜索页无响应")
                return []

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp, "html.parser")
            link = soup.find("a", href=re.compile(r"/subs/\d+\.html"))
            if not link:
                self._logger.info("Zimuku: 未找到字幕页链接")
                return []

            subs_url = parse.urljoin("https://zimuku.org", link.get("href"))
            self._logger.info("Zimuku: 字幕页 %s", subs_url)
            resp = self._zimuku_get_page(session, subs_url)
            if not resp:
                self._logger.warning("Zimuku: 字幕页无响应")
                return []

            soup = BeautifulSoup(resp, "html.parser")
            box = soup.select_one("div.subs.box.clearfix")
            if not box or not box.tbody:
                self._logger.info("Zimuku: 字幕列表为空")
                return []

            subs = box.tbody.find_all("tr")
            episode = self._extract_episode(video)
            season = self._extract_season(video)
            ep_filter = self._build_episode_filter(season, episode)
            prod = "剧集" if douban_info.get("type") == "tv" else "电影"

            results = []
            for sub in reversed(subs):
                include, is_coll = ep_filter(sub.a.text if sub.a else "")
                if not include:
                    continue
                info = self._extract_zimuku_sub_info(sub, prod, is_coll)
                if info:
                    results.append(info)
            self._logger.info("Zimuku: 找到 %d 条字幕", len(results))
            return results
        except ImportError as err:
            self._logger.error("Zimuku 搜索缺少依赖: %s", err)
            return []
        except Exception as err:
            self._logger.warning("Zimuku 搜索失败: %s", err)
            return []
        finally:
            if session:
                session.close()

    def _zimuku_get_page(self, session, url: str, max_retries: int = 3) -> Optional[bytes]:
        """获取 Zimuku 页面，自动处理验证码"""
        for attempt in range(max_retries + 1):
            try:
                resp = session.get(url, timeout=10)
                if resp.status_code == 200 and b'class="verifyimg"' not in resp.content:
                    return resp.content
                if b'class="verifyimg"' in resp.content and attempt < max_retries:
                    self._logger.info("Zimuku: 验证码触发 (attempt %d/%d) %s", attempt + 1, max_retries, url[:60])
                    self._solve_zimuku_captcha(session, url, resp.content)
                    continue
                if resp.status_code != 200:
                    self._logger.warning("Zimuku: HTTP %s -> %s", resp.status_code, url[:80])
                    return None
            except Exception as e:
                self._logger.warning("Zimuku: 请求异常 %s -> %s", url[:80], e)
                return None
        return None

    @staticmethod
    def _solve_zimuku_captcha(session, url: str, page_content: bytes):
        """解决 Zimuku BMP 验证码"""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(page_content, "html.parser")
            img = soup.find(attrs={"class": "verifyimg"})
            if not img:
                return
            img_src = img.get("src", "")
            if "data:image/bmp;base64," not in img_src:
                return
            b64 = img_src.split("data:image/bmp;base64,", 1)[1]

            SAMPLE_POINTS = [(10, 7), (7, 8), (12, 8), (10, 13), (7, 19), (12, 19), (10, 20), (6, 13), (14, 13)]
            TEMPLATES = {
                "0": [1, 1, 1, 1, 1, 1, 1, 1, 0], "1": [0, 1, 0, 0, 0, 0, 1, 0, 0],
                "2": [1, 0, 1, 0, 1, 0, 1, 0, 0], "3": [1, 0, 1, 1, 0, 1, 1, 0, 0],
                "4": [0, 0, 1, 0, 0, 1, 0, 0, 0], "5": [1, 1, 0, 0, 0, 1, 1, 0, 0],
                "6": [1, 0, 1, 1, 1, 1, 1, 1, 0], "7": [1, 0, 1, 0, 0, 0, 0, 0, 0],
                "8": [1, 1, 1, 1, 1, 1, 1, 0, 0], "9": [1, 1, 1, 0, 1, 0, 1, 0, 0],
            }

            data = base64.b64decode(b64)
            if len(data) < 54 or data[:2] != b"BM":
                return
            w = struct.unpack_from("<i", data, 18)[0]
            h = struct.unpack_from("<i", data, 22)[0]
            if (w, h) != (100, 27):
                return

            stride = (100 * 3 + 3) & ~3

            def is_fg(x, y, threshold=70):
                bmp_y = 26 - y
                offset = 54 + bmp_y * stride + x * 3
                b, g, r = data[offset], data[offset + 1], data[offset + 2]
                return (r + g + b) / 3 < threshold

            result = []
            one_offset = 0
            for i in range(5):
                char_x = i * 20
                features = [1 if is_fg(char_x + px - one_offset, py) else 0 for px, py in SAMPLE_POINTS]
                best_digit, min_diff = "?", float("inf")
                for digit, template in TEMPLATES.items():
                    diff = sum(f != t for f, t in zip(features, template))
                    if diff < min_diff:
                        min_diff, best_digit = diff, digit
                    if min_diff == 0:
                        break
                if best_digit == "1":
                    one_offset += 1
                elif best_digit == "4":
                    one_offset -= 1
                result.append(best_digit)

            text = "".join(result)
            hex_str = "".join(f"{ord(c):x}" for c in text)
            sep = "&" if "?" in url else "?"
            verify_url = f"{url}{sep}security_verify_img={hex_str}"
            session.get(verify_url, timeout=10)
        except Exception:
            pass

    def _extract_zimuku_sub_info(self, sub, production: str, collection: bool) -> Optional[SubtitleCandidate]:
        """解析单个 Zimuku 字幕条目"""
        try:
            if not sub.a:
                return None
            link = parse.urljoin("https://zimuku.org", sub.a.get("href"))
            name = sub.a.text

            langs = []
            td = sub.find("td", class_="tac lang")
            if td:
                langs = [img.get("title", "").rstrip("字幕") for img in td.find_all("img")]

            tags = {"source": [], "lang": [], "fmt": [], "bilingual": False, "production": production, "collection": collection}
            fmt_span = sub.find("span", class_="label-info")
            if fmt_span:
                fmt_text = fmt_span.text.strip().lower()
                tags["fmt"] = [f.strip() for f in fmt_text.split("/")] if "/" in fmt_text else [fmt_text]

            fansub_link = sub.select_one('a[href^="/t/"]')
            if fansub_link:
                tags["fansub"] = fansub_link.text.strip()
            else:
                danger = sub.find("span", class_="label-danger")
                if danger:
                    tags["fansub"] = danger.text.strip()

            if "简体中文" in langs:
                tags["lang"].append("chs")
            if "繁體中文" in langs:
                tags["lang"].append("cht")
            if "English" in langs:
                tags["lang"].append("eng")
            if "双语" in langs:
                tags["bilingual"] = True

            ext = self._extract_format_from_tags(tags.get("fmt", [])) or "srt"
            lang = "chi" if any(l in tags["lang"] for l in ("chs", "cht")) else "eng"

            return SubtitleCandidate(
                source="Zimuku",
                name=f"[Zimuku] {name}",
                url=link,
                ext=ext,
                language=lang,
                score=80,
                detail_url=link,
                tags=tags,
            )
        except Exception:
            return None

    def _download_zimuku(self, candidate: SubtitleCandidate) -> Optional[bytes]:
        """下载 Zimuku 字幕"""
        session = None
        try:
            import requests as _requests
            session = _requests.Session()
            session.headers.update(DEFAULT_HEADERS)
            session.mount("https://", _requests.adapters.HTTPAdapter(max_retries=3))

            detail_url = candidate.detail_url or candidate.url
            self._logger.info("Zimuku 下载: 详情页 %s", detail_url)
            data = self._zimuku_get_page(session, detail_url)
            if not data:
                self._logger.warning("Zimuku 下载: 详情页获取失败 (验证码或网络问题)")
                return None

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(data, "html.parser")
            dl_link = soup.find("li", class_="dlsub")
            if not dl_link or not dl_link.a:
                self._logger.warning("Zimuku 下载: 未找到 li.dlsub 链接，页面长度 %d", len(data))
                return None

            dl_url = parse.urljoin("https://zimuku.org", dl_link.a.get("href"))
            self._logger.info("Zimuku 下载: 下载页 %s", dl_url)
            data = self._zimuku_get_page(session, dl_url)
            if not data:
                self._logger.warning("Zimuku 下载: 下载页获取失败")
                return None

            soup = BeautifulSoup(data, "html.parser")
            links_div = soup.find("div", class_="clearfix")
            if not links_div:
                self._logger.warning("Zimuku 下载: 未找到 div.clearfix 容器，页面长度 %d", len(data))
                return None

            links = links_div.find_all("a")
            self._logger.info("Zimuku 下载: 找到 %d 个下载链接", len(links))
            for i, link in enumerate(links):
                href = link.get("href")
                if not href:
                    continue
                file_url = parse.urljoin("https://zimuku.org", href)
                try:
                    resp = session.get(file_url, headers={"Referer": dl_url}, timeout=10)
                    if resp is None or resp.status_code != 200:
                        self._logger.info("Zimuku 下载: 链接[%d] HTTP %s", i, getattr(resp, 'status_code', 'None'))
                        continue
                    size = len(resp.content)
                    if size <= 1024:
                        self._logger.info("Zimuku 下载: 链接[%d] 过小 (%d bytes)", i, size)
                        continue
                    self._logger.info("Zimuku 下载: 链接[%d] 成功 (%d bytes)", i, size)
                    return self._unpack_subtitle_data(resp.content, resp.headers, file_url)
                except Exception as e:
                    self._logger.info("Zimuku 下载: 链接[%d] 异常 %s", i, e)
                    continue
            self._logger.warning("Zimuku 下载: 所有 %d 个链接均无效", len(links))
            return None
        except ImportError as err:
            self._logger.error("Zimuku 下载缺少依赖: %s", err)
            return None
        except Exception as err:
            self._logger.warning("Zimuku 下载失败: %s", err)
            return None
        finally:
            if session:
                session.close()

    @staticmethod
    def _build_episode_filter(season: Optional[int], episode: Optional[int]):
        """构建剧集过滤器，返回 (include, is_collection) 元组"""
        if not (season and episode):
            return lambda name: (True, False)
        tokens = [
            f"S{int(season):02d}E{int(episode):02d}", f"E{int(episode):02d}",
            f"EP{int(episode):02d}", f"E{int(episode)}", f"EP{int(episode)}",
            f"第{int(episode)}集",
        ]
        tag_re = re.compile(r"(S\d{1,2}\s*(E|EP)\d{1,3})|(\bEP?\d{1,3}\b)|(第\s*\d+\s*集)")
        ep_re = re.compile(rf"(?<!\d)({'|'.join(re.escape(t) for t in tokens)})(?!\d)", re.IGNORECASE)

        def fn(name):
            upper = name.upper()
            has_tag = tag_re.search(upper) is not None
            matches = ep_re.search(upper) is not None
            return (not has_tag or matches, not has_tag)

        return fn

    @staticmethod
    def _extract_episode(video: Path) -> Optional[int]:
        """从文件名提取集数"""
        m = re.search(r"[\. _\-]?(?:S\d{1,2})?E(\d{1,3})|EP(\d{1,3})|第(\d{1,3})集", video.stem, re.IGNORECASE)
        if m:
            for g in m.groups():
                if g:
                    return int(g)
        return None

    @staticmethod
    def _extract_season(video: Path) -> Optional[int]:
        """从文件名或父目录提取季数"""
        for text in (video.stem, video.parent.name):
            m = re.search(r"S(\d{1,2})|第(\d{1,2})季", text, re.IGNORECASE)
            if m:
                return int(m.group(1) or m.group(2))
        return None

    @staticmethod
    def _extract_format_from_tags(fmts: List[str]) -> Optional[str]:
        for fmt in fmts:
            if fmt.lower() in ("ass", "ssa", "srt"):
                return fmt.lower()
        return None

    # ── 字幕解压 ────────────────────────────────────────────────────

    def _unpack_subtitle_data(self, data: bytes, headers: Any, url: str) -> Optional[bytes]:
        """解压字幕包，如果已经是字幕文件则直接返回"""
        cd = headers.get("Content-Disposition", "") if hasattr(headers, "get") else ""
        filename = self._filename_from_cd(cd) or os.path.basename(parse.urlparse(url).path) or "subtitle.srt"

        ext = Path(filename).suffix.lower()
        if ext in SUBTITLE_EXTS_TUPLE:
            return data

        if ext == ".zip":
            return self._unpack_zip(data)

        if ext in (".rar", ".7z"):
            self._logger.info("不支持的压缩格式 %s: %s", ext, filename)
            return None

        # URL/Content-Disposition 无法识别扩展名时，从文件内容检测格式
        detected = self._detect_subtitle_format(data)
        if detected:
            self._logger.info("从内容检测到字幕格式: %s (原文件名: %s)", detected, filename)
            return data

        self._logger.warning("未知文件类型 %s: %s (内容前20字节: %s)", ext, filename, data[:20])
        return None

    @staticmethod
    def _detect_subtitle_format(data: bytes) -> Optional[str]:
        """从文件内容检测字幕格式"""
        if not data or len(data) < 10:
            return None
        # SRT: BOM + 数字序号 或 直接以数字序号开头
        head = data[:200]
        if head.startswith(b'\xef\xbb\xbf'):
            head = head[3:]
        if re.match(rb'\d+\s*\r?\n\d{2}:\d{2}:\d{2}', head):
            return "srt"
        # ASS/SSA: [Script Info] 或 [V4+ Styles]
        if b'[Script Info]' in head or b'[V4+ Styles]' in head:
            return "ass"
        # SSA
        if b'[Script Info]' in head and b'PlayResX' in head:
            return "ssa"
        return None

    @staticmethod
    def _filename_from_cd(cd: str) -> str:
        if not cd:
            return ""
        fname_star = re.findall(r"filename\*\s*=\s*(\".*?\"|[^;]+)", cd, flags=re.IGNORECASE)
        if fname_star:
            raw = fname_star[0].strip().strip('"').strip("'")
            if "''" in raw:
                raw = raw.split("''", 1)[1]
            return html.unescape(parse.unquote(raw))
        fname = re.findall(r"filename\s*=\s*(\".*?\"|[^;]+)", cd, flags=re.IGNORECASE)
        if fname:
            return html.unescape(fname[0].strip().strip('"').strip("'"))
        return ""

    def _unpack_zip(self, data: bytes) -> Optional[bytes]:
        """解压 ZIP 文件，返回第一个字幕文件的内容（支持 GBK 编码文件名）"""
        import io
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    # 修复 GBK 编码文件名（中文 ZIP 包常见）
                    name = self._fix_zip_filename(info)
                    if Path(name).suffix.lower() in SUBTITLE_EXTS_TUPLE:
                        return zf.read(info)
        except Exception as err:
            self._logger.warning("ZIP 解压失败: %s", err)
        return None

    @staticmethod
    def _fix_zip_filename(info: zipfile.ZipInfo) -> str:
        """修复 ZIP 文件中的 GBK 编码文件名"""
        try:
            # flag_bits bit 11 (0x800) = UTF-8 编码标志
            if info.flag_bits & 0x800:
                return info.filename
            # 尝试 GBK 解码
            raw = info.filename.encode("cp437")
            return raw.decode("gbk")
        except (UnicodeDecodeError, UnicodeEncodeError):
            return info.filename

    def _ai_filter_candidates(self, video: Path, candidates: List[SubtitleCandidate]) -> List[SubtitleCandidate]:
        if not candidates or len(candidates) < 2:
            return candidates
        if not self._ai_api_key or not self._ai_model:
            return candidates

        top_n = max(1, min(self._ai_top_n, len(candidates)))
        top_candidates = candidates[:top_n]
        candidate_lines = "\n".join(
            [
                f"{index + 1}. 来源={item.source}; 格式={item.ext}; 哈希匹配={item.hash_match}; 名称={item.name}"
                for index, item in enumerate(top_candidates)
            ]
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "你是字幕筛选助手。根据视频文件名和候选字幕列表，按最适合到最不适合排序。"
                    "只输出候选序号，用英文逗号分隔，不要输出其它文字。"
                    "优先考虑名称匹配、剧集季集信息、清晰度/版本信息、中文特效/精校/官方、ASS/SSA 格式。"
                ),
            },
            {
                "role": "user",
                "content": f"视频文件名：{video.name}\n候选字幕：\n{candidate_lines}",
            },
        ]

        content = self._ai_chat(messages=messages, max_tokens=64, temperature=0)
        if not content:
            return candidates

        ordered_indexes: List[int] = []
        for token in re.findall(r"\d+", content):
            index = int(token) - 1
            if 0 <= index < len(top_candidates) and index not in ordered_indexes:
                ordered_indexes.append(index)

        if not ordered_indexes:
            return candidates

        ordered = [top_candidates[index] for index in ordered_indexes]
        ordered.extend([item for index, item in enumerate(top_candidates) if index not in ordered_indexes])
        ordered.extend(candidates[top_n:])
        self._logger.info("AI 字幕筛选完成: %s -> %s", video.name, content)
        return ordered

    def _ai_chat(self, messages: List[Dict[str, str]], max_tokens: int = 64, temperature: float = 0) -> str:
        endpoint = self._ai_chat_endpoint()
        payload = {
            "model": self._ai_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self._ai_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "MeiamSubtitles",
        }
        try:
            req = request.Request(
                url=endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with request.urlopen(req, timeout=max(self._ai_timeout, 1)) as resp:
                if getattr(resp, "status", 200) != 200:
                    return ""
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        except Exception as err:
            self._logger.warning("AI 请求失败: %s", err)
            return ""

        try:
            return str(data["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError):
            return ""

    def _ai_chat_endpoint(self) -> str:
        base_url = (self._ai_base_url or "").strip().rstrip("/")
        if not base_url:
            base_url = "https://api.openai.com/v1"
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    def _extract_video_paths(self, event_data: Any) -> List[Path]:
        candidates: Set[Path] = set()

        def walk(value: Any):
            if value is None:
                return
            if isinstance(value, Path):
                self._add_path_candidate(value, candidates)
                return
            if isinstance(value, str):
                if self._looks_like_path(value):
                    self._add_path_candidate(Path(value), candidates)
                return
            if isinstance(value, dict):
                for item in value.values():
                    walk(item)
                return
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    walk(item)
                return
            for attr in ("path", "file_path", "dest", "target_path", "target", "to_path", "save_path"):
                if hasattr(value, attr):
                    walk(getattr(value, attr))

        walk(event_data)
        return sorted(candidates, key=lambda item: str(item))

    def _add_path_candidate(self, path: Path, candidates: Set[Path]):
        try:
            if path.is_file() and path.suffix.lower() in VIDEO_EXTS:
                candidates.add(path)
            elif path.is_dir():
                for item in self._iter_videos(path):
                    candidates.add(item)
        except Exception:
            return

    def _iter_videos(self, root: Path) -> Iterable[Path]:
        max_depth = max(self._max_depth, 0)
        root_parts = len(root.parts)
        for item in root.rglob("*"):
            if len(item.parts) - root_parts > max_depth:
                continue
            if item.is_file() and item.suffix.lower() in VIDEO_EXTS:
                yield item

    @staticmethod
    def _looks_like_path(value: str) -> bool:
        if not value or len(value) > 1024:
            return False
        if "\n" in value or "\r" in value:
            return False
        return bool(re.search(r"(^/|^[A-Za-z]:[\\/]|\\\\)", value))

    def _existing_subtitles(self, video: Path, language: str) -> List[Path]:
        suffix = LANG_SUFFIX.get(language, language)
        patterns = [
            f"{video.stem}.{suffix}.*",
            f"{video.stem}.{language}.*",
            f"{video.stem}.zh.*" if language == "chi" else f"{video.stem}.en.*",
        ]
        found: List[Path] = []
        for pattern in patterns:
            for item in video.parent.glob(pattern):
                if item == video:
                    continue
                ext = item.suffix.lower().lstrip(".")
                if ext in SUBTITLE_EXTS and item not in found:
                    found.append(item)
        return found

    def _subtitle_path(self, video: Path, ext: str, language: str) -> Path:
        ext = self._extract_format(ext) or "srt"
        lang_suffix = LANG_SUFFIX.get(language, language)
        return video.with_name(f"{video.stem}.{lang_suffix}.{ext}")

    def _http_bytes(
        self,
        url: str,
        data: bytes = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Optional[bytes]:
        headers = headers or {"User-Agent": "MeiamSubtitles", "Accept": "*/*"}
        try:
            req = request.Request(url=url, data=data, headers=headers, method="POST" if data else "GET")
            with request.urlopen(req, timeout=self._timeout) as resp:
                if getattr(resp, "status", 200) != 200:
                    return None
                return resp.read()
        except Exception as err:
            self._logger.warning("HTTP 请求失败 %s: %s", url, err)
            return None

    def _sleep_auto_delay(self):
        delay_min = max(self._auto_delay_min, 0)
        delay_max = max(self._auto_delay_max, 0)
        if delay_max <= 0:
            return
        if delay_max < delay_min:
            delay_min, delay_max = delay_max, delay_min
        delay = delay_min if delay_min == delay_max else random.randint(delay_min, delay_max)
        if delay > 0:
            self._logger.info("自动字幕任务延时 %s 秒后继续", delay)
            time.sleep(delay)

    @staticmethod
    def _shooter_hash(video: Path) -> str:
        size = video.stat().st_size
        if size < 8 * 1024:
            return ""

        offsets = [4 * 1024, size // 3 * 2, size // 3, size - 8 * 1024]
        values = []
        with video.open("rb") as file_obj:
            for offset in offsets:
                file_obj.seek(max(offset, 0))
                values.append(hashlib.md5(file_obj.read(4 * 1024)).hexdigest())
        return ";".join(values)

    @staticmethod
    def _thunder_cid(video: Path) -> str:
        size = video.stat().st_size
        with video.open("rb") as file_obj:
            if size < 0xF000:
                return hashlib.sha1(file_obj.read()).hexdigest().upper()

            chunks = []
            file_obj.seek(0)
            chunks.append(file_obj.read(0x5000))
            file_obj.seek(size // 3)
            chunks.append(file_obj.read(0x5000))
            file_obj.seek(size - 0x5000)
            chunks.append(file_obj.read(0x5000))
        return hashlib.sha1(b"".join(chunks)).hexdigest().upper()

    @staticmethod
    def _quality_score(name: str) -> int:
        if not name:
            return 0
        keywords = [("特效", 5), ("精校", 4), ("官方", 3), ("简中", 2), ("中文", 1)]
        return next((score for keyword, score in keywords if keyword.lower() in name.lower()), 0)

    @staticmethod
    def _lang_tier(candidate: SubtitleCandidate) -> int:
        """语言优先级：简中+双语(0) > 简中(1) > 繁中+双语(2) > 繁中(3) > 英文(4)"""
        tags = getattr(candidate, "tags", {}) or {}
        langs = set(tags.get("lang", []))
        bilingual = tags.get("bilingual", False)
        if "chs" in langs and bilingual:
            return 4
        if "chs" in langs:
            return 3
        if "cht" in langs and bilingual:
            return 2
        if "cht" in langs:
            return 1
        return 0

    @staticmethod
    def _format_priority(ext: str) -> int:
        ext = (ext or "").lower()
        if ext in {"ass", "ssa"}:
            return 2
        if ext == "srt":
            return 1
        return 0

    @staticmethod
    def _name_similarity(video_name: str, subtitle_name: str) -> float:
        clean_video = re.sub(r"\W+", "", video_name or "").lower()
        clean_subtitle = re.sub(r"\W+", "", subtitle_name or "").lower()
        if not clean_video:
            return 0
        matched = sum(1 for char in clean_video if char in clean_subtitle)
        return matched / len(clean_video)

    @staticmethod
    def _extract_format(value: str) -> Optional[str]:
        text = (value or "").lower()
        for ext in ("ass", "ssa", "srt"):
            if ext in text:
                return ext
        return None

    def _record(self, video: Path, language: str, source: str, status: str, path: str):
        try:
            records = self.cache.get("records") or []
            records.append(
                {
                    "video": video.name,
                    "language": language,
                    "source": source,
                    "status": status,
                    "path": path,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
            self.cache.set("records", records[-100:])
            self._logger.info("记录: %s | %s | %s | %s", video.name, language, source, status)
        except Exception as err:
            self._logger.warning("记录保存失败: %s", err)

    def _configured_sources(self) -> Set[str]:
        return {item.lower() for item in self._split_config(self._sources)} or {"shooter", "thunder", "subhd", "zimuku"}

    def _configured_languages(self) -> List[str]:
        languages = [self._normalize_language(item) for item in self._split_config(self._languages)]
        return [item for item in languages if item in {"chi", "eng"}] or ["chi"]

    @staticmethod
    def _normalize_language(language: str) -> str:
        return LANG_ALIASES.get(str(language or "").strip().lower(), str(language or "").strip().lower())

    @staticmethod
    def _split_config(value: Any) -> List[str]:
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        return [item.strip() for item in str(value or "").split(",") if item.strip()]

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        return str(value).strip().lower() not in {"0", "false", "no", "off", "否", "关闭"}
