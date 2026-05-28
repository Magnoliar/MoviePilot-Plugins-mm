import hashlib
import json
import logging
import random
import re
import threading
import time
from dataclasses import dataclass
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


@dataclass
class SubtitleCandidate:
    source: str
    name: str
    url: str
    ext: str
    language: str
    score: float = 0
    hash_match: bool = False


class MeiamSubtitles(_PluginBase):
    plugin_name = "Meiam 自动字幕"
    plugin_desc = "入库后自动从射手网、迅雷看看下载同名字幕"
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/autosubtitles.jpeg"
    plugin_version = "1.1.0"
    plugin_author = "Meiam/mm"
    auth_level = 1

    _enabled = False
    _notify = True
    _overwrite = False
    _sources = "shooter,thunder"
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

        if config:
            self._enabled = config.get("enabled", False)
            self._notify = config.get("notify", True)
            self._overwrite = config.get("overwrite", False)
            self._sources = config.get("sources", "shooter,thunder")
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

    def _setup_logger(self):
        log_dir = Path(getattr(settings, "LOG_PATH", "/moviepilot/logs")) / "plugins"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger(f"plugin.{self.__class__.__name__}")
        self._logger.setLevel(logging.INFO)

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
                                            ],
                                            "hint": "推荐同时启用，射手支持中文/英文，迅雷主要支持中文。",
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
        records = self.cache.get("records") or []
        rows = [
            {
                "component": "tr",
                "content": [
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

        best = candidates[0]
        content = self._http_bytes(best.url)
        if not content:
            self._record(video, language, best.source, "下载失败", best.url)
            return False, "字幕下载失败"

        sub_path = self._subtitle_path(video, best.ext, language)
        sub_path.write_bytes(content)
        self._record(video, language, best.source, "已下载", str(sub_path))
        return True, f"已下载 {best.source}: {sub_path.name}"

    def _search(self, video: Path, language: str) -> List[SubtitleCandidate]:
        candidates: List[SubtitleCandidate] = []
        sources = self._configured_sources()
        if "shooter" in sources and language in {"chi", "eng"}:
            candidates.extend(self._search_shooter(video, language))
        if "thunder" in sources and language == "chi":
            candidates.extend(self._search_thunder(video, language))

        sorted_candidates = sorted(
            candidates,
            key=lambda item: (
                item.hash_match,
                self._name_similarity(video.name, item.name),
                self._quality_score(item.name),
                self._format_priority(item.ext),
                item.score,
            ),
            reverse=True,
        )
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
            f"{video.stem}.*",
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
        records = self.cache.get("records") or []
        records.append(
            {
                "video": video.name,
                "language": language,
                "source": source,
                "status": status,
                "path": path,
            }
        )
        self.cache.set("records", records[-100:])

    def _configured_sources(self) -> Set[str]:
        return {item.lower() for item in self._split_config(self._sources)} or {"shooter", "thunder"}

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
