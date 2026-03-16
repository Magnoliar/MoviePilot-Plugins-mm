import os
import re
import time
import json
import random
import threading
import copy
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

from app.plugins import _PluginBase
from app.core.config import settings
from app.helper.downloader import DownloaderHelper
from app.helper.sites import SitesHelper
from app.core.cache import TTLCache

class SeedRescuer(_PluginBase):
    # 插件基本信息
    plugin_name = "种子找回助手"
    plugin_desc = "基于特征扫描智能找回种子。支持全特征匹配、关键词校验与风控规避。"
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/mediasyncdel.png"
    plugin_version = "5.1.0"
    plugin_author = "Gemini"

    # 内部变量
    _enabled = False
    _scan_path = ""
    _selected_sites =[]
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
            self._enabled = config.get("enabled", False)
            self._scan_path = config.get("scan_path", "")
            self._selected_sites = config.get("selected_sites",[])
            self._downloader_name = config.get("downloader_name", "")
            self._cron = config.get("cron", "")
            self._only_paused = config.get("only_paused", True)
            self._max_depth = int(config.get("max_depth", 3))
            self._path_mapping = config.get("path_mapping", "")
            self._sleep_min = int(config.get("sleep_min", 3))
            self._sleep_max = int(config.get("sleep_max", 8))

    def get_state(self) -> bool:
        return self._enabled

    def stop_service(self):
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled or not self._cron:
            return[]
        return[{
            "id": "seed_rescuer_auto_task",
            "name": "种子自动找回",
            "trigger": self._cron, 
            "func": self.download_all,
            "kwargs": {}
        }]

    def _load_history(self) -> Dict[str, bool]:
        if self._history_file.exists():
            try: 
                return json.loads(self._history_file.read_text(encoding='utf-8'))
            except Exception: 
                return {}
        return {}

    def _save_history(self, item_name: str):
        history = self._load_history()
        history[item_name] = True
        self._history_file.write_text(json.dumps(history, ensure_ascii=False), encoding='utf-8')

    # ==========================
    # 获取插件配置表单 (解决Vue渲染错误)
    # 严格返回纯表单元素与配置项，不可包含页面布局组件如 VTabs 等
    # ==========================
    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        site_options = []
        try:
            sites =[]
            if hasattr(self.sites_helper, 'get_indexers'):
                sites = self.sites_helper.get_indexers()
            elif hasattr(self.sites_helper, 'get_sites'):
                sites = self.sites_helper.get_sites()
                
            for s in sites:
                s_id = s.get("id") if isinstance(s, dict) else getattr(s, "id", "")
                s_name = s.get("name") if isinstance(s, dict) else getattr(s, "name", "")
                if s_id and s_name:
                    site_options.append({"title": s_name, "value": s_id})
        except Exception:
            pass

        downloader_options =[]
        try:
            downloaders = self.downloader_helper.get_configs()
            downloader_options =[{"title": name, "value": name} for name in downloaders.keys()]
        except Exception:
            pass
            
        return [
            {
                "component": "VRow",
                "content":[
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content":[{"component": "VSwitch", "props": {"model": "enabled", "label": "启用定时任务"}}]}, 
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content":[{"component": "VTextField", "props": {"model": "cron", "label": "自动周期", "placeholder": "0 2 * * *"}}]}, 
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content":[{"component": "VTextField", "props": {"model": "max_depth", "label": "扫描深度", "type": "number"}}]}
                ]
            },
            {"component": "VTextField", "props": {"model": "scan_path", "label": "扫描路径 (逗号分隔)", "placeholder": "/media/movies"}},
            {"component": "VTextField", "props": {"model": "path_mapping", "label": "路径转换", "placeholder": "/media:/downloads"}},
            {
                "component": "VRow", 
                "content":[
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content":[{"component": "VSelect", "props": {"model": "selected_sites", "label": "选择站点", "items": site_options, "multiple": True, "chips": True}}]}, 
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content":[{"component": "VSelect", "props": {"model": "downloader_name", "label": "下载器", "items": downloader_options}}]}
                ]
            },
            {
                "component": "VRow", 
                "content":[
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content":[{"component": "VTextField", "props": {"model": "sleep_min", "label": "最小延迟(秒)", "type": "number"}}]}, 
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content":[{"component": "VTextField", "props": {"model": "sleep_max", "label": "最大延迟(秒)", "type": "number"}}]}
                ]
            },
            {"component": "VSwitch", "props": {"model": "only_paused", "label": "暂停添加"}}
        ], {
            "enabled": self._enabled,
            "scan_path": self._scan_path,
            "selected_sites": self._selected_sites,
            "downloader_name": self._downloader_name,
            "cron": self._cron,
            "only_paused": self._only_paused,
            "max_depth": self._max_depth,
            "path_mapping": self._path_mapping,
            "sleep_min": self._sleep_min,
            "sleep_max": self._sleep_max
        }

    # ==========================
    #  获取详情展示页面 (不混杂表单配置)
    # ==========================
    def get_page(self) -> List[dict]:
        stats = self.cache.get("stats") or {}

        return[
            {
                "component": "div",
                "content": [
                    {
                        "component": "VRow",
                        "content":[
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content":[{"component": "VCard", "props": {"title": "待找回项目", "subtitle": str(stats.get("total", 0))}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content":[{"component": "VCard", "props": {"title": "成功找回", "subtitle": str(stats.get("rescued", 0))}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content":[{"component": "VCard", "props": {"title": "已在下载器", "subtitle": str(stats.get("existing", 0))}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content":[{"component": "VCard", "props": {"title": "匹配失败", "subtitle": str(stats.get("failed", 0))}}]}
                        ]
                    },
                    {
                        "component": "VRow",
                        "props": {"class": "mt-2 mb-4"},
                        "content":[
                            {"component": "VCol", "content":[
                                {"component": "VBtn", "props": {"color": "primary", "variant": "tonal", "class": "mr-2"}, "content": "🔍 扫描磁盘", "events": {"click": {"api": "plugin/SeedRescuer/scan_now", "method": "get"}}},
                                {"component": "VBtn", "props": {"color": "warning", "variant": "tonal", "class": "mr-2"}, "content": "🧪 灰度测试 (5项)", "events": {"click": {"api": "plugin/SeedRescuer/test_run", "method": "post"}}},
                                {"component": "VBtn", "props": {"color": "success", "variant": "tonal", "class": "mr-2"}, "content": "🚀 全量找回", "events": {"click": {"api": "plugin/SeedRescuer/download_all", "method": "post"}}},
                                {"component": "VBtn", "props": {"color": "error", "variant": "tonal"}, "content": "🗑️ 重置记录", "events": {"click": {"api": "plugin/SeedRescuer/reset_history", "method": "post"}}}
                            ]}
                        ]
                    },
                    {
                        "component": "VCard",
                        "props": {"title": "找回清单"},
                        "content":[
                            {
                                "component": "VDataTable", 
                                "props": {
                                    "headers":[
                                        {"title": "目录名", "key": "name"}, 
                                        {"title": "体积", "key": "size_str"}, 
                                        {"title": "状态", "key": "status"}, 
                                        {"title": "匹配率", "key": "confidence"}, 
                                        {"title": "操作", "key": "actions", "sortable": False}
                                    ], 
                                    "items": "{{data_list}}"
                                }
                            }
                        ]
                    }
                ]
            }
        ]

    def get_data(self) -> Dict[str, Any]:
        raw_data = self.cache.get("items") or[]
        # 使用深拷贝防止Vue绑定事件修改持久化缓存从而导致溢出
        data_list = copy.deepcopy(raw_data)
        
        for item in data_list:
            item["actions"] =[
                {
                    "component": "VBtn", 
                    "props": {"icon": "mdi-download", "variant": "text", "color": "primary"}, 
                    "events": {
                        "click": {
                            "api": "plugin/SeedRescuer/download_item", 
                            "method": "post", 
                            "data": {"item_id": item["id"]}
                        }
                    }
                }
            ]
        return {"data_list": data_list, "stats": self.cache.get("stats")}

    def get_api(self) -> List[Dict[str, Any]]:
        return[
            {"path": "/scan_now", "endpoint": self.scan_now, "methods": ["GET"]},
            {"path": "/download_item", "endpoint": self.download_item, "methods": ["POST"]},
            {"path": "/download_all", "endpoint": self.download_all, "methods": ["POST"]},
            {"path": "/test_run", "endpoint": self.test_run, "methods": ["POST"]},
            {"path": "/reset_history", "endpoint": self.reset_history, "methods": ["POST"]}
        ]

    # ==========================
    #  核心 API 及逻辑
    # ==========================
    def reset_history(self, **kwargs):
        if self._history_file.exists(): 
            self._history_file.unlink()
        return {"success": True, "message": "找回历史记录已清空重置"}

    def scan_now(self, **kwargs):
        if not self._scan_path: 
            return {"success": False, "message": "未配置扫描路径，请先在设置中配置。"}
            
        all_items =[]
        history = self._load_history()
        existing_torrents = self._get_existing_torrents()
        paths =[p.strip() for p in self._scan_path.split(",") if p.strip()]
        stats = {"total": 0, "rescued": 0, "existing": 0, "failed": 0}

        for base_path in paths:
            items = self._get_local_items(base_path)
            for name, path, size in items:
                stats["total"] += 1
                if name in history:
                    status = "✨ 已找回"
                    stats["rescued"] += 1
                    conf = "100%"
                elif name in existing_torrents:
                    status = "✅ 已存在"
                    stats["existing"] += 1
                    conf = "100%"
                else:
                    status = "⏳ 待找回"
                    conf = "-"
                
                all_items.append({
                    "id": str(hash(path)), 
                    "name": name, 
                    "path": path, 
                    "size": size, 
                    "size_str": self._format_size(size), 
                    "status": status, 
                    "confidence": conf
                })
        
        self.cache.set("items", all_items)
        self.cache.set("stats", stats)
        return {"success": True, "message": f"扫描完毕，共发现 {len(all_items)} 个符合特征的影视文件夹/文件。"}

    def test_run(self, **kwargs):
        self.scan_now()
        cached_items = self.cache.get("items") or[]
        items =[i for i in cached_items if "待找回" in i.get("status", "")][:5]
        
        if not items: 
            return {"success": False, "message": "清单中没有待找回的项目"}

        def run_test_background():
            for item in items: 
                self.download_item(item_id=item["id"])
                time.sleep(random.uniform(self._sleep_min, self._sleep_max))
                
        threading.Thread(target=run_test_background, daemon=True).start()
        return {"success": True, "message": f"已在后台启动灰度测试，将尝试找回 {len(items)} 个项目，请稍后刷新页面查看状态。"}

    def download_all(self, **kwargs):
        cached_items = self.cache.get("items") or []
        to_do =[i for i in cached_items if "待找回" in i.get("status", "")]
        
        if not to_do: 
            return {"success": False, "message": "清单中没有待找回的项目，请先执行扫描！"}

        def run_all_background():
            for item in to_do:
                self.download_item(item_id=item["id"])
                time.sleep(random.uniform(self._sleep_min, self._sleep_max))
                
        threading.Thread(target=run_all_background, daemon=True).start()
        return {"success": True, "message": f"全量自动化作业已在后台启动，共计 {len(to_do)} 个任务，请随时刷新看板。"}

    def download_item(self, item_id: str = None, **kwargs):
        items = self.cache.get("items") or[]
        stats = self.cache.get("stats") or {"total": 0, "rescued": 0, "existing": 0, "failed": 0}
        
        target = next((i for i in items if i["id"] == item_id), None)
        if not target: 
            return {"success": False, "message": "该记录已失效，请重新扫描"}

        search_queries = [
            target["name"].replace(".", " "),
            re.sub(r'\[.*?\]', '', target["name"].replace(".", " ")).strip()
        ]
        clean_title = self._parse_media_name(target["name"])
        if clean_title: 
            search_queries.append(clean_title)

        best_torrent = None
        best_diff = 1.0
        for query in list(dict.fromkeys(search_queries)): 
            results = self.sites_helper.search(keyword=query, site_ids=self._selected_sites)
            best_torrent, best_diff = self._match_torrent(results, target["size"], target["name"])
            if best_torrent: 
                break 

        if best_torrent:
            success, msg = self._download_and_add(best_torrent, target["path"])
            if success:
                target["status"] = "✨ 找回成功"
                target["confidence"] = f"{100-best_diff*100:.3f}%"
                stats["rescued"] += 1
                self._save_history(target["name"])
                
                self.cache.set("items", items)
                self.cache.set("stats", stats)
                return {"success": True, "message": f"找回成功！精准度: {100-best_diff*100:.3f}%"}
            else:
                return {"success": False, "message": f"推送到下载器失败: {msg}"}
        
        stats["failed"] += 1
        self.cache.set("stats", stats)
        return {"success": False, "message": "未匹配到体积或特征相符的种子"}

    # ==========================
    #  内部辅助方法
    # ==========================
    def _parse_media_name(self, name: str) -> str:
        year_match = re.search(r'[\.\s](19|20)\d{2}[\.\s]', name)
        season_match = re.search(r'[\.\s]S\d{2}[\.\s]', name, re.I)
        split_point = -1
        if year_match: 
            split_point = year_match.start()
        elif season_match: 
            split_point = season_match.start()
            
        if split_point > 0:
            title = name[:split_point].replace(".", " ").strip()
            suffix = name[split_point:].split(".")[1] if "." in name[split_point:] else ""
            return f"{title} {suffix}".strip()
        return ""

    def _get_local_items(self, scan_path: str) -> List[Tuple[str, str, int]]:
        res =[]
        root = Path(scan_path)
        if not root.exists(): 
            return res
            
        feature_pattern = re.compile(r'\d{4}|S\d{2}|1080p|2160p|WEB-DL|BluRay|REMUX', re.I)
        
        def scan_recursive(current_path: Path, depth: int):
            if depth > self._max_depth: return
            try:
                items = current_path.iterdir()
            except Exception:
                return
                
            for item in items:
                try:
                    if item.name.startswith(('.', '@', '$')): 
                        continue
                        
                    if item.is_dir():
                        if item.name.count('.') >= 3 or feature_pattern.search(item.name):
                            size = sum(f.stat().st_size for f in item.rglob('*') if f.is_file())
                            if size > 100 * 1024 * 1024: 
                                res.append((item.name, str(item.absolute()), size))
                        else: 
                            scan_recursive(item, depth + 1)
                    elif item.suffix.lower() in ['.mp4', '.mkv', '.ts', '.iso']:
                        res.append((item.name, str(item.absolute()), item.stat().st_size))
                except Exception:
                    continue
                    
        scan_recursive(root, 1)
        return res

    def _get_existing_torrents(self) -> set:
        names = set()
        downloader = self.downloader_helper.get_service(name=self._downloader_name)
        if downloader and not downloader.instance.is_inactive():
            try:
                torrents = downloader.instance.get_torrents()
                if torrents:
                    for t in torrents: 
                        names.add(t.name)
            except Exception:
                pass
        return names

    def _match_torrent(self, search_results: List[Any], target_size: int, local_name: str) -> Tuple[Optional[Any], float]:
        if not search_results: 
            return None, 1.0
            
        def get_priority(t):
            site_id = getattr(t, 'site', getattr(t, 'site_id', ''))
            try: 
                return self._selected_sites.index(site_id)
            except Exception: 
                return 999
                
        sorted_res = sorted(search_results, key=get_priority)
        core_tags = [w for w in["iQIYI", "MWeb", "Netflix", "NF", "Tencent", "WEB-DL", "BluRay", "REMUX", "HFR"] if w.lower() in local_name.lower()]
        
        for t in sorted_res:
            t_size = getattr(t, 'size', 0)
            t_title = getattr(t, 'title', getattr(t, 'name', ''))
            
            if not t_size: 
                continue
                
            diff = abs(t_size - target_size) / target_size
            if diff < 0.001: 
                tag_match = True
                for tag in core_tags:
                    if tag.lower() not in t_title.lower():
                        tag_match = False
                        break
                if tag_match: 
                    return t, diff
                    
        return None, 1.0

    def _download_and_add(self, torrent: Any, local_path: str) -> Tuple[bool, str]:
        downloader = self.downloader_helper.get_service(name=self._downloader_name)
        if not downloader or downloader.instance.is_inactive(): 
            return False, "选定下载器当前不可用或已离线"
            
        save_path = str(Path(local_path).parent).replace("\\", "/")
        
        if self._path_mapping and ":" in self._path_mapping:
            internal, external = self._path_mapping.split(":", 1)
            internal = internal.replace("\\", "/")
            external = external.replace("\\", "/")
            
            if save_path.startswith(internal):
                save_path = external + save_path[len(internal):]

        torrent_url = getattr(torrent, 'enclosure', getattr(torrent, 'url', ''))
        
        try:
            success = downloader.instance.add_torrent(
                torrent_url=torrent_url, 
                save_path=save_path.rstrip("/"), 
                is_paused=self._only_paused, 
                tag="SeedRescuer"
            )
            return success, ("添加成功" if success else "下载器拒绝接受任务")
        except Exception as e:
            return False, str(e)

    def _format_size(self, size: int) -> str:
        for unit in['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024: 
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} PB"