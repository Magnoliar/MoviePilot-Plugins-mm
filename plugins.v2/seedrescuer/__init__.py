import os
import re
import time
import json
import random
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from app.plugins import _PluginBase
from app.core.config import settings
from app.helper.downloader import DownloaderHelper
from app.helper.sites import SitesHelper
from app.schemas.types import NotificationType
from app.core.cache import TTLCache

class SeedRescuer(_PluginBase):
    # 插件基本信息
    plugin_name = "种子找回助手"
    plugin_desc = "基于特征扫描智能找回种子。支持全特征匹配、关键词校验与风控规避。"
    plugin_icon = "mediasyncdel.png"
    plugin_version = "3.8"
    plugin_author = "Gemini"

    # 内部变量
    _enabled = False
    _scan_path = ""
    _selected_sites = []
    _downloader_name = ""
    _cron = ""
    _only_paused = True
    _max_depth = 3
    _path_mapping = ""
    _sleep_min = 3
    _sleep_max = 8
    
    _history_file = Path(settings.PLUGIN_DATA_PATH) / "seed_rescuer_history.json"

    def init_plugin(self, config: dict = None):
        self.downloader_helper = DownloaderHelper()
        self.sites_helper = SitesHelper()
        self.cache = TTLCache(region="SeedRescuer", maxsize=1000, ttl=86400)
        
        if not self.cache.get("stats"):
            self.cache.set("stats", {"total": 0, "rescued": 0, "existing": 0, "failed": 0})

        if config:
            self._enabled = config.get("enabled")
            self._scan_path = config.get("scan_path")
            self._selected_sites = config.get("selected_sites") or []
            self._downloader_name = config.get("downloader_name")
            self._cron = config.get("cron")
            self._only_paused = config.get("only_paused", True)
            self._max_depth = int(config.get("max_depth", 3))
            self._path_mapping = config.get("path_mapping", "")
            self._sleep_min = int(config.get("sleep_min", 3))
            self._sleep_max = int(config.get("sleep_max", 8))

    def _load_history(self) -> Dict[str, bool]:
        if self._history_file.exists():
            try: return json.loads(self._history_file.read_text(encoding='utf-8'))
            except: return {}
        return {}

    def _save_history(self, item_name: str):
        history = self._load_history()
        history[item_name] = True
        self._history_file.write_text(json.dumps(history, ensure_ascii=False), encoding='utf-8')

    def get_page(self) -> List[dict]:
        sites = self.sites_helper.get_active_sites()
        site_options = [{"title": s.name, "value": s.id} for s in sites]
        downloaders = self.downloader_helper.get_configs()
        downloader_options = [{"title": name, "value": name} for name in downloaders.keys()]

        return [
            {
                "component": "VTabs",
                "content": [
                    {
                        "title": "概览与操作",
                        "content": [
                            {
                                "component": "VRow",
                                "content": [
                                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VCard", "props": {"title": "待找回项目", "subtitle": "{{stats.total}}", "prepend-icon": "mdi-folder-search", "color": "blue-lighten-4"}}]},
                                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VCard", "props": {"title": "成功找回", "subtitle": "{{stats.rescued}}", "prepend-icon": "mdi-check-decagram", "color": "green-lighten-4"}}]},
                                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VCard", "props": {"title": "已在下载器", "subtitle": "{{stats.existing}}", "prepend-icon": "mdi-cloud-check", "color": "orange-lighten-4"}}]},
                                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VCard", "props": {"title": "匹配失败", "subtitle": "{{stats.failed}}", "prepend-icon": "mdi-close-circle", "color": "red-lighten-4"}}]}
                                ]
                            },
                            {
                                "component": "VRow",
                                "props": {"class": "mt-2"},
                                "content": [
                                    {"component": "VCol", "content": [
                                        {"component": "VBtn", "props": {"color": "primary", "variant": "tonal", "class": "mr-2"}, "content": "🔍 扫描磁盘", "events": {"click": {"api": "plugin/SeedRescuer/scan_now", "method": "get"}}},
                                        {"component": "VBtn", "props": {"color": "warning", "variant": "tonal", "class": "mr-2"}, "content": "🧪 灰度测试 (5项)", "events": {"click": {"api": "plugin/SeedRescuer/test_run", "method": "post"}}},
                                        {"component": "VBtn", "props": {"color": "success", "variant": "tonal"}, "content": "🚀 全量全自动找回", "events": {"click": {"api": "plugin/SeedRescuer/download_all", "method": "post"}}},
                                    ]}
                                ]
                            },
                            {"component": "VBtn", "props": {"color": "grey", "variant": "text", "class": "mt-4"}, "content": "重置历史记录", "events": {"click": {"api": "plugin/SeedRescuer/reset_history", "method": "post"}}}
                        ]
                    },
                    {
                        "title": "待找回清单",
                        "content": [
                            {"component": "VDataTable", "props": {"headers": [{"title": "本地目录名", "key": "name"}, {"title": "体积", "key": "size_str"}, {"title": "找回状态", "key": "status"}, {"title": "匹配率", "key": "confidence"}, {"title": "操作", "key": "actions", "sortable": False}], "items": "{{data_list}}"}}
                        ]
                    },
                    {
                        "title": "设置",
                        "content": [
                            {
                                "component": "VForm",
                                "content": [
                                    {"component": "VRow", "content": [{"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "enabled", "label": "启用定时任务"}}]}, {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "cron", "label": "自动周期", "placeholder": "0 2 * * *"}}, ]}, {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VTextField", "props": {"model": "max_depth", "label": "扫描深度", "type": "number"}}]}]},
                                    {"component": "VTextField", "props": {"model": "scan_path", "label": "扫描路径 (逗号分隔)", "placeholder": "/media/movies"}},
                                    {"component": "VTextField", "props": {"model": "path_mapping", "label": "路径转换 (内部:TR)", "placeholder": "/media:/downloads", "hint": "将MoviePilot识别路径转换为下载器路径"}},
                                    {"component": "VRow", "content": [{"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VSelect", "props": {"model": "selected_sites", "label": "选择站点", "items": site_options, "multiple": True, "chips": True}}]}, {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VSelect", "props": {"model": "downloader_name", "label": "目标下载器", "items": downloader_options}}]}]},
                                    {"component": "VRow", "content": [{"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VTextField", "props": {"model": "sleep_min", "label": "最小请求间隔(秒)", "type": "number", "hint": "防止触发站点风控"}}]}, {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VTextField", "props": {"model": "sleep_max", "label": "最大请求间隔(秒)", "type": "number"}}]}]},
                                    {"component": "VSwitch", "props": {"model": "only_paused", "label": "暂停添加 (推荐，确保校验)"}}
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

    def get_data(self) -> Dict[str, Any]:
        raw_data = self.cache.get("items") or []
        for item in raw_data:
            item["actions"] = [{"component": "VBtn", "props": {"icon": "mdi-download", "variant": "text", "color": "primary"}, "events": {"click": {"api": "plugin/SeedRescuer/download_item", "method": "post", "data": {"item_id": item["id"]}}}}]
        return {"data_list": raw_data, "stats": self.cache.get("stats")}

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {"path": "/scan_now", "endpoint": self.scan_now, "methods": ["GET"]},
            {"path": "/download_item", "endpoint": self.download_item, "methods": ["POST"]},
            {"path": "/download_all", "endpoint": self.download_all, "methods": ["POST"]},
            {"path": "/test_run", "endpoint": self.test_run, "methods": ["POST"]},
            {"path": "/reset_history", "endpoint": self.reset_history, "methods": ["POST"]}
        ]

    def reset_history(self, **kwargs):
        if self._history_file.exists(): self._history_file.unlink()
        return {"code": 0, "message": "历史已重置"}

    def scan_now(self, **kwargs):
        if not self._scan_path: return {"code": 1, "message": "请配置路径"}
        all_items = []
        history = self._load_history()
        existing_torrents = self._get_existing_torrents()
        paths = [p.strip() for p in self._scan_path.split(",")]
        stats = {"total": 0, "rescued": 0, "existing": 0, "failed": 0}

        for base_path in paths:
            items = self._get_local_items(base_path)
            for name, path, size in items:
                stats["total"] += 1
                if name in history:
                    status = "✨ 已找回 (历史)"; stats["rescued"] += 1; conf = "100%"
                elif name in existing_torrents:
                    status = "✅ 下载器已有"; stats["existing"] += 1; conf = "100%"
                else:
                    status = "⏳ 待处理"; conf = "-"
                all_items.append({"id": str(hash(path)), "name": name, "path": path, "size": size, "size_str": self._format_size(size), "status": status, "confidence": conf})
        
        self.cache.set("items", all_items); self.cache.set("stats", stats)
        return {"code": 0, "message": f"扫描完成，识别到 {len(all_items)} 个影视资源"}

    def download_item(self, item_id: str = None, **kwargs):
        items = self.cache.get("items") or []
        stats = self.cache.get("stats")
        target = next((i for i in items if i["id"] == item_id), None)
        if not target: return {"code": 1, "message": "项目失效"}

        search_queries = []
        search_queries.append(target["name"].replace(".", " "))
        search_queries.append(re.sub(r'\[.*?\]', '', target["name"].replace(".", " ")).strip())
        clean_title = self._parse_media_name(target["name"])
        if clean_title:
            search_queries.append(clean_title)

        best_torrent = None
        best_diff = 1.0

        for query in list(dict.fromkeys(search_queries)): 
            self.debug(f"尝试搜索词: {query}")
            results = self.sites_helper.search(keyword=query, site_ids=self._selected_sites)
            best_torrent, best_diff = self._match_torrent(results, target["size"], target["name"])
            if best_torrent: break 

        if best_torrent:
            success, msg = self._download_and_add(best_torrent, target["path"])
            if success:
                target["status"] = "✨ 找回成功"; target["confidence"] = f"{100-best_diff*100:.3f}%"
                stats["rescued"] += 1; self._save_history(target["name"])
                self.cache.set("items", items); self.cache.set("stats", stats)
                return {"code": 0, "message": "找回成功"}
        
        stats["failed"] += 1; self.cache.set("stats", stats)
        return {"code": 1, "message": "未匹配到完全一致的种子"}

    def _parse_media_name(self, name: str) -> str:
        year_match = re.search(r'[\.\s](19|20)\d{2}[\.\s]', name)
        season_match = re.search(r'[\.\s]S\d{2}[\.\s]', name, re.I)
        split_point = -1
        if year_match: split_point = year_match.start()
        elif season_match: split_point = season_match.start()
        if split_point > 0:
            title = name[:split_point].replace(".", " ").strip()
            suffix = name[split_point:].split(".")[1] if "." in name[split_point:] else ""
            return f"{title} {suffix}".strip()
        return ""

    def test_run(self, **kwargs):
        self.scan_now()
        items = [i for i in self.cache.get("items", []) if "待处理" in i["status"]][:5]
        if not items: return {"code": 1, "message": "无可测试项"}
        count = 0
        for item in items: 
            res = self.download_item(item_id=item["id"])
            if res.get("code") == 0: count += 1
            delay = random.uniform(self._sleep_min, self._sleep_max)
            self.info(f"防风控睡眠: 等待 {delay:.1f} 秒...")
            time.sleep(delay)
        return {"code": 0, "message": f"测试完成，成功 {count}/5 个，请检查 TR 状态"}

    def download_all(self, **kwargs):
        to_do = [i for i in self.cache.get("items", []) if "待处理" in i["status"]]
        count = 0
        for i, item in enumerate(to_do):
            self.info(f"正在全量执行 ({i+1}/{len(to_do)}): {item['name']}")
            res = self.download_item(item_id=item["id"])
            if res.get("code") == 0: count += 1
            delay = random.uniform(self._sleep_min, self._sleep_max)
            self.info(f"防风控睡眠: 等待 {delay:.1f} 秒...")
            time.sleep(delay)
        self.post_message(mtype=NotificationType.DownloadAdded, title="找回任务完成", text=f"成功为 {len(to_do)} 个资源找回了种子。")
        return {"code": 0, "message": "全量任务已完成"}

    def _get_local_items(self, scan_path: str) -> List[Tuple[str, str, int]]:
        res = []
        root = Path(scan_path)
        if not root.exists(): return res
        feature_pattern = re.compile(r'\d{4}|S\d{2}|1080p|2160p|WEB-DL|BluRay|REMUX', re.I)
        def scan_recursive(current_path: Path, depth: int):
            if depth > self._max_depth: return
            try:
                for item in current_path.iterdir():
                    if item.name.startswith(('.', '@', '$')): continue
                    if item.is_dir():
                        if item.name.count('.') >= 3 or feature_pattern.search(item.name):
                            size = sum(f.stat().st_size for f in item.rglob('*') if f.is_file())
                            if size > 100 * 1024 * 1024: res.append((item.name, str(item.absolute()), size))
                        else: scan_recursive(item, depth + 1)
                    elif item.suffix.lower() in ['.mp4', '.mkv', '.ts', '.iso']:
                        res.append((item.name, str(item.absolute()), item.stat().st_size))
            except: pass
        scan_recursive(root, 1); return res

    def _get_existing_torrents(self) -> set:
        names = set()
        downloader = self.downloader_helper.get_service(name=self._downloader_name)
        if downloader:
            torrents = downloader.instance.get_torrents()
            if torrents:
                for t in torrents: names.add(t.name)
        return names

    def _match_torrent(self, search_results: List[Any], target_size: int, local_name: str) -> Tuple[Optional[Dict], float]:
        if not search_results: return None, 1.0
        def get_priority(t):
            try: return self._selected_sites.index(t.get('site_id'))
            except: return 999
        sorted_res = sorted(search_results, key=get_priority)
        core_tags = [w for w in ["iQIYI", "MWeb", "Netflix", "NF", "Tencent", "WEB-DL", "BluRay", "REMUX", "HFR"] if w.lower() in local_name.lower()]
        for t in sorted_res:
            t_size = t.get('size')
            t_title = t.get('title', '')
            if not t_size: continue
            diff = abs(t_size - target_size) / target_size
            if diff < 0.001: 
                tag_match = True
                for tag in core_tags:
                    if tag.lower() not in t_title.lower():
                        tag_match = False; break
                if tag_match:
                    self.info(f"极致匹配成功！误差: {diff:.6%}, 标签校验通过: {core_tags}")
                    return t, diff
        return None, 1.0

    def _download_and_add(self, torrent: Dict, local_path: str) -> Tuple[bool, str]:
        downloader = self.downloader_helper.get_service(name=self._downloader_name)
        if not downloader: return False, "下载器不可用"
        save_path = str(Path(local_path).parent).replace("\\", "/")
        if self._path_mapping and ":" in self._path_mapping:
            internal, external = self._path_mapping.split(":")
            save_path = save_path.replace(internal.replace("\\", "/"), external.replace("\\", "/"))
        save_path = save_path.rstrip("/")
        return downloader.instance.add_torrent(torrent_url=torrent.get('enclosure'), save_path=save_path, is_paused=self._only_paused, tag="SeedRescuer")

    def _format_size(self, size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024: return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} PB"
