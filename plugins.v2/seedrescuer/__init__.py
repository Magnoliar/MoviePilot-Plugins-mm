import os
import re
import time
import json
import random
import threading
import copy
import logging
from logging.handlers import RotatingFileHandler
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

from app.plugins import _PluginBase
from app.core.config import settings
from app.helper.downloader import DownloaderHelper
from app.helper.sites import SitesHelper
from app.core.cache import TTLCache

from apscheduler.triggers.cron import CronTrigger

class SeedRescuer(_PluginBase):
    plugin_name = "种子找回助手"
    plugin_desc = "基于特征扫描智能找回种子。(v5.2.2 增加全景搜索日志、优化关键词提取与误差宽容度)"
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/mediasyncdel.png"
    plugin_version = "5.2.2"  # 核心升级：大幅增强匹配透明度日志、修正状态回写丢失问题、放宽 3% 匹配误差
    plugin_author = "Gemini"
    
    auth_level = 1

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
    
    _history_lock = threading.Lock()
    _task_lock = threading.RLock()
    _exit_event = threading.Event()

    def init_plugin(self, config: dict = None):
        self.stop_service()
        self._exit_event.clear()

        # 初始化独立日志
        self._setup_logger()

        self.downloader_helper = DownloaderHelper()
        self.sites_helper = SitesHelper()
        self.cache = TTLCache(region="SeedRescuer", maxsize=1000, ttl=86400)
        
        if not self.cache.get("stats"):
            self.cache.set("stats", {"total": 0, "rescued": 0, "existing": 0, "failed": 0})
        if not self.cache.get("status_msg"):
            self.cache.set("status_msg", "空闲中 (等待任务指令)")

        if config:
            self._enabled = config.get("enabled", False)
            self._scan_path = config.get("scan_path", "")
            self._selected_sites = config.get("selected_sites",[])
            self._downloader_name = config.get("downloader_name", "")
            self._cron = config.get("cron", "")
            self._only_paused = config.get("only_paused", True)
            self._path_mapping = config.get("path_mapping", "")
            
            def safe_int(val, default):
                try:
                    return int(val) if val not in[None, ""] else default
                except (ValueError, TypeError):
                    return default

            self._max_depth = safe_int(config.get("max_depth"), 3)
            self._sleep_min = safe_int(config.get("sleep_min"), 3)
            self._sleep_max = safe_int(config.get("sleep_max"), 8)

    def _setup_logger(self):
        """配置插件独立的日志输出文件"""
        log_dir = Path(getattr(settings, "LOG_PATH", "/moviepilot/logs")) / "plugins"
        log_dir.mkdir(parents=True, exist_ok=True)
        
        self.log_file = log_dir / "seedrescuer.log"
        if not self.log_file.exists():
            self.log_file.touch()

        self._logger = logging.getLogger(f"plugin.{self.__class__.__name__}")
        self._logger.setLevel(logging.INFO)
        self._logger.handlers.clear()

        file_handler = RotatingFileHandler(self.log_file, maxBytes=2*1024*1024, backupCount=3, encoding='utf-8')
        formatter = logging.Formatter('[%(asctime)s] %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        self._logger.addHandler(file_handler)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self._logger.addHandler(console_handler)
        
        self._logger.info("[SeedRescuer] 插件日志模块初始化完毕。")

    def get_state(self) -> bool:
        return self._enabled

    def stop_service(self):
        try:
            if hasattr(self, '_logger'):
                self._logger.info("尝试停止插件服务并释放资源...")
            self._exit_event.set()
            if hasattr(self, 'cache') and self.cache:
                self.cache.clear()
        except Exception as e:
            if hasattr(self, '_logger'):
                self._logger.error(f"插件服务停止异常: {str(e)}", exc_info=True)

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled or not self._cron:
            return[]
            
        try:
            trigger = CronTrigger.from_crontab(self._cron)
        except Exception as e:
            self._logger.error(f"Cron 表达式解析失败: {e}", exc_info=True)
            return []

        return[{
            "id": "seed_rescuer_auto_task",
            "name": "种子自动找回",
            "trigger": trigger, 
            "func": self.download_all,
            "kwargs": {}
        }]

    # ==========================
    #  本地持久化记录
    # ==========================
    def _load_history(self) -> Dict[str, bool]:
        if self._history_file.exists():
            try: 
                return json.loads(self._history_file.read_text(encoding='utf-8'))
            except Exception: 
                return {}
        return {}

    def _save_history(self, item_name: str):
        with self._history_lock:
            history = self._load_history()
            history[item_name] = True
            self._history_file.write_text(json.dumps(history, ensure_ascii=False), encoding='utf-8')

    # ==========================
    #  表单页
    # ==========================
    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        site_options =[]
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
        except Exception as e:
            self._logger.error(f"获取站点列表失败: {e}", exc_info=True)

        downloader_options =[]
        try:
            downloaders = self.downloader_helper.get_configs()
            downloader_options =[{"title": name, "value": name} for name in downloaders.keys()]
        except Exception as e:
            self._logger.error(f"获取下载器列表失败: {e}", exc_info=True)
            
        elements =[{
            "component": "VForm",
            "content":[
                {
                    "component": "VRow",
                    "content":[
                        {"component": "VCol", "props": {"cols": 12, "xxl": 4, "xl": 4, "lg": 4, "md": 4, "sm": 6, "xs": 12}, "content":[{"component": "VSwitch", "props": {"model": "enabled", "label": "启用定时任务", "hint": "插件总开关：启动后根据设定的周期在后台自动执行找回任务。"}}] },
                        {"component": "VCol", "props": {"cols": 12, "xxl": 4, "xl": 4, "lg": 4, "md": 4, "sm": 6, "xs": 12}, "content":[{"component": "VTextField", "props": {"model": "cron", "label": "自动周期", "placeholder": "0 2 * * *", "hint": "设置后台全量自动化找回的周期（支持5位 Cron 表达式）。"}}] },
                        {"component": "VCol", "props": {"cols": 12, "xxl": 4, "xl": 4, "lg": 4, "md": 4, "sm": 6, "xs": 12}, "content":[{"component": "VTextField", "props": {"model": "max_depth", "label": "扫描深度", "type": "number", "hint": "从指定根目录向下扫描文件层级的最大深度（推荐为3）。"}}] }
                    ]
                },
                {
                    "component": "VRow",
                    "content":[
                        {"component": "VCol", "props": {"cols": 12, "xxl": 6, "xl": 6, "lg": 6, "md": 6, "sm": 12, "xs": 12}, "content":[{"component": "VTextField", "props": {"model": "scan_path", "label": "待扫描路径", "placeholder": "/media/movies", "hint": "必填。待找回资源的本地存储目录，多个路径请使用英文逗号分隔。"}}] },
                        {"component": "VCol", "props": {"cols": 12, "xxl": 6, "xl": 6, "lg": 6, "md": 6, "sm": 12, "xs": 12}, "content":[{"component": "VTextField", "props": {"model": "path_mapping", "label": "路径转换映射", "placeholder": "/media:/downloads", "hint": "选填。将容器内路径映射为下载器可视路径，格式为 `容器路径:下载器路径`。"}}] }
                    ]
                },
                {
                    "component": "VRow",
                    "content":[
                        {"component": "VCol", "props": {"cols": 12, "xxl": 6, "xl": 6, "lg": 6, "md": 6, "sm": 12, "xs": 12}, "content":[{"component": "VSelect", "props": {"model": "selected_sites", "label": "目标检索站点", "items": site_options, "multiple": True, "chips": True, "hint": "选择要进行补种/找回的站点，缺省将在所有站点检索。"}}] },
                        {"component": "VCol", "props": {"cols": 12, "xxl": 6, "xl": 6, "lg": 6, "md": 6, "sm": 12, "xs": 12}, "content":[{"component": "VSelect", "props": {"model": "downloader_name", "label": "推送下载器", "items": downloader_options, "hint": "找回到对应种子后，推送到哪一个下载器。"}}] }
                    ]
                },
                {
                    "component": "VRow",
                    "content":[
                        {"component": "VCol", "props": {"cols": 12, "xxl": 4, "xl": 4, "lg": 4, "md": 4, "sm": 6, "xs": 12}, "content":[{"component": "VTextField", "props": {"model": "sleep_min", "label": "检索最小延迟(秒)", "type": "number", "hint": "发起站点搜索前的随机等待时间下限，防止风控封号。"}}] },
                        {"component": "VCol", "props": {"cols": 12, "xxl": 4, "xl": 4, "lg": 4, "md": 4, "sm": 6, "xs": 12}, "content":[{"component": "VTextField", "props": {"model": "sleep_max", "label": "检索最大延迟(秒)", "type": "number", "hint": "发起站点搜索前的随机等待时间上限。"}}] },
                        {"component": "VCol", "props": {"cols": 12, "xxl": 4, "xl": 4, "lg": 4, "md": 4, "sm": 12, "xs": 12}, "content":[{"component": "VSwitch", "props": {"model": "only_paused", "label": "强行暂停添加", "hint": "推送到下载器后，强制保持暂停状态，不自动开始进行校验或下载。"}}] }
                    ]
                },
                {
                    "component": "VRow",
                    "content":[{
                        "component": "VCol",
                        "props": {"cols": 12},
                        "content":[{
                            "component": "VAlert",
                            "props": {"type": "info", "variant": "tonal", "class": "mt-2"},
                            "text": "配置完成后，您可以直接前往插件的专属操作面板，手动触发“磁盘扫描”与“找回测试”。所有自动化操作和进度均会在系统日志中留痕。"
                        }]
                    }]
                }
            ]
        }]
        
        return elements, {
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
    #  数据看板展示页面
    # ==========================
    def get_page(self) -> List[dict]:
        stats = self.cache.get("stats") or {"total": 0, "rescued": 0, "existing": 0, "failed": 0}
        status_msg = self.cache.get("status_msg") or "空闲中 (等待任务指令)"
        data_list = self.cache.get("items") or[]

        tbody_content =[]
        for item in data_list:
            # 根据状态着色
            status_text = str(item.get("status", ""))
            status_color = "text-grey"
            if "✨" in status_text:
                status_color = "text-success font-weight-bold"
            elif "❌" in status_text:
                status_color = "text-error font-weight-bold"
            elif "✅" in status_text:
                status_color = "text-info font-weight-bold"

            tbody_content.append({
                "component": "tr",
                "content":[
                    {"component": "td", "text": str(item.get("name", ""))},
                    {"component": "td", "text": str(item.get("size_str", ""))},
                    {"component": "td", "props": {"class": status_color}, "text": status_text},
                    {"component": "td", "text": str(item.get("confidence", ""))},
                    {"component": "td", "content":[
                        {
                            "component": "VBtn",
                            "props": {"color": "primary", "variant": "tonal", "size": "small", "prepend-icon": "mdi-download"},
                            "text": "下载",
                            "events": {"click": {"api": "plugin/SeedRescuer/download_item", "method": "get", "params": {"item_id": item["id"]}}}
                        }
                    ]}
                ]
            })

        if not tbody_content:
            tbody_content.append({
                "component": "tr",
                "content":[{"component": "td", "props": {"colspan": 5, "class": "text-center text-grey"}, "text": "暂无扫描数据"}]
            })

        return[
            {
                "component": "VAlert",
                "props": {"type": "info", "variant": "tonal", "class": "mb-4", "border": "start"},
                "text": f"状态监控: {status_msg}"
            },
            {
                "component": "VRow",
                "content":[
                    {"component": "VCol", "props": {"cols": 6, "md": 3, "xl": 3}, "content":[{"component": "VCard", "props": {"title": "待找回项目", "subtitle": str(stats.get("total", 0))}}] },
                    {"component": "VCol", "props": {"cols": 6, "md": 3, "xl": 3}, "content":[{"component": "VCard", "props": {"title": "成功找回", "subtitle": str(stats.get("rescued", 0))}}] },
                    {"component": "VCol", "props": {"cols": 6, "md": 3, "xl": 3}, "content":[{"component": "VCard", "props": {"title": "已在下载器", "subtitle": str(stats.get("existing", 0))}}] },
                    {"component": "VCol", "props": {"cols": 6, "md": 3, "xl": 3}, "content":[{"component": "VCard", "props": {"title": "匹配失败", "subtitle": str(stats.get("failed", 0))}}] }
                ]
            },
            {
                "component": "VRow",
                "props": {"class": "mt-4 mb-4"},
                "content":[
                    {"component": "VCol", "content":[
                        {"component": "VBtn", "props": {"color": "primary", "variant": "tonal", "class": "mr-3 mb-2", "prepend-icon": "mdi-magnify"}, "text": "扫描磁盘", "events": {"click": {"api": "plugin/SeedRescuer/scan_now", "method": "get"}}},
                        {"component": "VBtn", "props": {"color": "warning", "variant": "tonal", "class": "mr-3 mb-2", "prepend-icon": "mdi-test-tube"}, "text": "灰度测试", "events": {"click": {"api": "plugin/SeedRescuer/test_run", "method": "get"}}},
                        {"component": "VBtn", "props": {"color": "success", "variant": "tonal", "class": "mr-3 mb-2", "prepend-icon": "mdi-rocket"}, "text": "全量找回", "events": {"click": {"api": "plugin/SeedRescuer/download_all", "method": "get"}}},
                        {"component": "VBtn", "props": {"color": "error", "variant": "tonal", "class": "mb-2", "prepend-icon": "mdi-delete"}, "text": "重置记录", "events": {"click": {"api": "plugin/SeedRescuer/reset_history", "method": "get"}}}
                    ]}
                ]
            },
            {
                "component": "VCard",
                "props": {"title": "找回清单"},
                "content":[
                    {
                        "component": "VTable",
                        "props": {"hover": True, "fixed-header": True, "density": "comfortable"},
                        "content":[
                            {
                                "component": "thead",
                                "content":[{
                                    "component": "tr",
                                    "content":[
                                        {"component": "th", "text": "目录名"},
                                        {"component": "th", "text": "体积"},
                                        {"component": "th", "text": "状态"},
                                        {"component": "th", "text": "匹配率"},
                                        {"component": "th", "text": "操作"}
                                    ]
                                }]
                            },
                            {
                                "component": "tbody",
                                "content": tbody_content
                            }
                        ]
                    }
                ]
            }
        ]

    def get_data(self) -> Dict[str, Any]:
        return {}

    # ==========================
    #  核心 API 及逻辑
    # ==========================
    def get_api(self) -> List[Dict[str, Any]]:
        return[
            {"path": "/scan_now", "endpoint": self.scan_now, "methods":["GET"], "summary": "扫描磁盘", "auth": "bear"},
            {"path": "/test_run", "endpoint": self.test_run, "methods": ["GET"], "summary": "灰度测试", "auth": "bear"},
            {"path": "/download_all", "endpoint": self.download_all, "methods":["GET"], "summary": "全量自动化找回", "auth": "bear"},
            {"path": "/reset_history", "endpoint": self.reset_history, "methods": ["GET"], "summary": "重置找回历史记录", "auth": "bear"},
            {"path": "/download_item", "endpoint": self.download_item, "methods": ["GET"], "summary": "手动下载指定的丢失项", "auth": "bear"}
        ]

    def reset_history(self):
        with self._history_lock:
            if self._history_file.exists(): 
                self._history_file.unlink()
        self._logger.info("历史记录已被重置")
        self.cache.set("status_msg", "空闲中 (找回历史已重置)")
        return {"success": True, "message": "找回历史记录已清空重置"}

    def scan_now(self):
        if not self._task_lock.acquire(blocking=False):
            return {"success": False, "message": "已有后台任务正在运行，请稍候..."}
            
        try:
            self.cache.set("status_msg", "正在全盘扫描，请稍候...")
            if not self._scan_path: 
                self.cache.set("status_msg", "扫描中止: 未配置扫描路径")
                return {"success": False, "message": "未配置扫描路径，请先在底角⚙️设置中配置。"}
                
            all_items =[]
            with self._history_lock:
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
            self.cache.set("status_msg", f"空闲中 (上次扫描完毕，共发现 {len(all_items)} 个特征项目)")
            self._logger.info(f"磁盘扫描完成，共发现 {len(all_items)} 个符合特征的项")
            return {"success": True, "message": f"扫描完毕，共发现 {len(all_items)} 个符合特征的影视文件夹/文件。"}
        except Exception as e:
            self._logger.error(f"磁盘扫描时发生异常: {e}", exc_info=True)
            self.cache.set("status_msg", "空闲中 (上次扫描发生异常)")
            return {"success": False, "message": "扫描异常，请查看系统日志。"}
        finally:
            self._task_lock.release()

    def test_run(self):
        if not self._task_lock.acquire(blocking=False):
            return {"success": False, "message": "已有任务正在运行中，请稍后再试"}
            
        try:
            self.scan_now()
            cached_items = self.cache.get("items") or []
            items =[i for i in cached_items if "待找回" in i.get("status", "")] [:5]
            
            if not items: 
                self.cache.set("status_msg", "空闲中 (清单为空)")
                return {"success": False, "message": "清单中没有待找回的项目"}

            def run_test_background():
                self._logger.info(f"启动灰度测试，将尝试找回 {len(items)} 个项目")
                for idx, item in enumerate(items): 
                    if self._exit_event.is_set():
                        self._logger.warning("收到停止信号，中止测试任务")
                        self.cache.set("status_msg", "空闲中 (灰度测试已中止)")
                        break
                    
                    self.cache.set("status_msg", f"正在灰度测试: {item['name']} ({idx+1}/{len(items)})")
                    self.download_item(item_id=item["id"])
                    time.sleep(random.uniform(self._sleep_min, self._sleep_max))
                    
                self.cache.set("status_msg", "空闲中 (灰度测试结束)")
                self._logger.info("灰度测试运行结束")
                    
            threading.Thread(target=run_test_background, daemon=True).start()
            return {"success": True, "message": f"已在后台启动灰度测试，将尝试找回 {len(items)} 个项目，请随时刷新页面查看状态。"}
        finally:
            self._task_lock.release()

    def download_all(self):
        if not self._task_lock.acquire(blocking=False):
            return {"success": False, "message": "已有任务正在运行中，请稍后再试"}
            
        try:
            cached_items = self.cache.get("items") or[]
            to_do =[i for i in cached_items if "待找回" in i.get("status", "")]
            
            if not to_do: 
                return {"success": False, "message": "清单中没有待找回的项目，请先执行扫描！"}

            def run_all_background():
                self._logger.info(f"启动全量自动化找回，共计 {len(to_do)} 个项目")
                for idx, item in enumerate(to_do):
                    if self._exit_event.is_set():
                        self._logger.warning("收到停止信号，中止全量自动化找回任务")
                        self.cache.set("status_msg", "空闲中 (全量找回中止)")
                        break
                    
                    self.cache.set("status_msg", f"全量自动化找回中: {item['name']} ({idx+1}/{len(to_do)})")
                    self.download_item(item_id=item["id"])
                    time.sleep(random.uniform(self._sleep_min, self._sleep_max))
                    
                self.cache.set("status_msg", "空闲中 (全量找回任务结束)")
                self._logger.info("全量自动化找回运行结束")
                    
            threading.Thread(target=run_all_background, daemon=True).start()
            return {"success": True, "message": f"全量自动化作业已在后台启动，共计 {len(to_do)} 个任务，请随时刷新看板。"}
        finally:
            self._task_lock.release()

    def download_item(self, item_id: str):
        if not item_id:
            return {"success": False, "message": "缺少必要参数 item_id"}

        items = self.cache.get("items") or[]
        stats = self.cache.get("stats") or {"total": 0, "rescued": 0, "existing": 0, "failed": 0}
        
        target = next((i for i in items if i["id"] == str(item_id)), None)
        if not target: 
            return {"success": False, "message": "该记录已失效，请重新扫描"}

        self._logger.info(f"▶ 开始尝试找回: [{target['name']}] (原始体积: {self._format_size(target['size'])})")

        # 核心修复 2: 剔除干扰符号，提高提取纯净关键词成功率
        clean_name = re.sub(r'[\[\]\(\)\{\}\-\_\￡\@]', ' ', target["name"]).replace(".", " ")
        clean_name = re.sub(r'\s+', ' ', clean_name).strip()

        search_queries =[
            clean_name,
            target["name"].replace(".", " ")
        ]
        clean_title = self._parse_media_name(target["name"])
        if clean_title: 
            search_queries.append(clean_title)

        # 核心修复 1: 增加找回全景日志，让检索过程透明化
        search_queries = list(dict.fromkeys(search_queries))
        self._logger.info(f"  ├─ 生成检索关键词: {search_queries}")

        best_torrent = None
        best_diff = 1.0
        
        for query in search_queries: 
            if not query: continue
            if hasattr(self.sites_helper, 'search'):
                try:
                    self._logger.info(f"  ├─ 发起搜索: '{query}'")
                    results = self.sites_helper.search(keyword=query, site_ids=self._selected_sites)
                    self._logger.info(f"  ├─ 收到结果: {len(results) if results else 0} 条，进入二次校验...")
                    best_torrent, best_diff = self._match_torrent(results, target["size"], target["name"])
                    if best_torrent: 
                        break 
                except Exception as e:
                    self._logger.error(f"  ├─ 站点搜索抛出异常 [{query}]: {e}", exc_info=True)

        if best_torrent:
            success, msg = self._download_and_add(best_torrent, target["path"])
            if success:
                target["status"] = "✨ 找回成功"
                target["confidence"] = f"{100-best_diff*100:.1f}%"
                stats["rescued"] += 1
                self._save_history(target["name"])
                
                self.cache.set("items", items)
                self.cache.set("stats", stats)
                self._logger.info(f"  └─ ✔ 找回并推送成功: {target['name']}")
                return {"success": True, "message": f"找回成功！精准度: {100-best_diff*100:.1f}%"}
            else:
                self._logger.warning(f"  └─ ⚠ 找回成功但推送到下载器失败: {msg}")
                return {"success": False, "message": f"推送到下载器失败: {msg}"}
        
        # 核心修复 3: 正确写入匹配失败状态回 UI 并存储
        target["status"] = "❌ 匹配失败"
        target["confidence"] = f"{100-best_diff*100:.1f}%" if best_diff < 1.0 else "0%"
        stats["failed"] += 1
        
        self.cache.set("items", items)
        self.cache.set("stats", stats)
        self._logger.warning(f"  └─ ❌ 匹配失败: 所有站点的结果均被特征/体积校验过滤")
        return {"success": False, "message": "未匹配到体积或特征相符的种子"}

    # ==========================
    #  内部辅助方法
    # ==========================
    def _parse_media_name(self, name: str) -> str:
        # 优化 Title 提取正则，获取最核心片名与年份/季度作为强兜底搜索词
        year_match = re.search(r'[\.\s](19|20)\d{2}[\.\s]', name)
        season_match = re.search(r'[\.\s]S\d{2}[\.\s]', name, re.I)
        
        split_point = -1
        suffix = ""
        
        if year_match: 
            split_point = year_match.start()
            suffix = year_match.group(0).strip(" .")
        elif season_match: 
            split_point = season_match.start()
            suffix = season_match.group(0).strip(" .")
            
        if split_point > 0:
            title = name[:split_point].replace(".", " ").strip()
            # 同样清理一次特殊符号
            title = re.sub(r'[\[\]\(\)\{\}\-\_\￡\@]', ' ', title)
            title = re.sub(r'\s+', ' ', title).strip()
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
                    elif item.suffix.lower() in['.mp4', '.mkv', '.ts', '.iso']:
                        res.append((item.name, str(item.absolute()), item.stat().st_size))
                except Exception:
                    continue
                    
        scan_recursive(root, 1)
        return res

    def _get_existing_torrents(self) -> set:
        names = set()
        if not self._downloader_name:
            return names
            
        downloader = self.downloader_helper.get_service(name=self._downloader_name)
        if downloader and downloader.instance:
            is_inactive = getattr(downloader.instance, 'is_inactive', lambda: False)
            if not is_inactive():
                try:
                    res = downloader.instance.get_torrents()
                    torrents = res[0] if isinstance(res, tuple) else res
                    if torrents:
                        for t in torrents:
                            t_name = t.get('name') if isinstance(t, dict) else getattr(t, 'name', '')
                            if t_name:
                                names.add(t_name)
                except Exception as e:
                    self._logger.warning(f"获取下载器当前种子状态时出现问题: {e}")
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
        core_tags =[w for w in["iQIYI", "MWeb", "Netflix", "NF", "Tencent", "WEB-DL", "BluRay", "REMUX", "HFR", "CC"] if w.lower() in local_name.lower()]
        
        self._logger.info(f"    └─ 开始特征匹配... 候选数量: {len(sorted_res)} | 本地体积: {self._format_size(target_size)} | 核心要求标签: {core_tags}")

        best_torrent = None
        best_diff = 1.0
        
        for t in sorted_res:
            t_size = getattr(t, 'size', 0)
            t_title = getattr(t, 'title', getattr(t, 'name', ''))
            site_name = getattr(t, 'site_name', getattr(t, 'site', 'Unknown'))
            
            if not t_size: 
                continue
                
            diff = abs(t_size - target_size) / target_size
            if diff < best_diff:
                best_diff = diff

            # 核心修复 4: 宽容误差上调至 3% (0.03)，防止压制组算错体积或NFO丢失导致的一刀切拒绝
            if diff <= 0.03: 
                tag_match = True
                for tag in core_tags:
                    if tag.lower() not in t_title.lower():
                        tag_match = False
                        break
                if tag_match: 
                    self._logger.info(f"    └─ [✅ 完美命中] 站点: {site_name} | 种子: {t_title} | 远程体积: {self._format_size(t_size)} | 误差: {diff*100:.2f}%")
                    return t, diff
                else:
                    self._logger.info(f"    └─ [⏭ 跳过] 标签不符: {t_title}")
            else:
                self._logger.info(f"    └─[⏭ 跳过] 体积不符: {t_title} (远程体积: {self._format_size(t_size)} | 差距: {diff*100:.2f}%)")
                    
        self._logger.info(f"    └─ 无完全匹配项。最小体积误差: {best_diff*100:.2f}%")
        return None, best_diff

    def _download_and_add(self, torrent: Any, local_path: str) -> Tuple[bool, str]:
        if not self._downloader_name:
            return False, "未配置下载器"
            
        downloader = self.downloader_helper.get_service(name=self._downloader_name)
        if not downloader or not downloader.instance: 
            return False, "选定下载器配置不存在或服务未启动"
            
        is_inactive = getattr(downloader.instance, 'is_inactive', None)
        if callable(is_inactive) and is_inactive():
            return False, "选定下载器当前处于离线状态"
            
        save_path = str(Path(local_path).parent).replace("\\", "/")
        
        if self._path_mapping and ":" in self._path_mapping:
            internal, external = self._path_mapping.split(":", 1)
            internal = internal.replace("\\", "/")
            external = external.replace("\\", "/")
            
            if save_path.startswith(internal):
                save_path = external + save_path[len(internal):]

        torrent_url = getattr(torrent, 'enclosure', getattr(torrent, 'url', ''))
        
        try:
            res = downloader.instance.add_torrent(
                torrent_url=torrent_url, 
                save_path=save_path.rstrip("/"), 
                is_paused=self._only_paused, 
                tag="SeedRescuer"
            )
            success = res[0] if isinstance(res, tuple) else bool(res)
            return success, ("添加成功" if success else "下载器拒绝接受任务")
        except Exception as e:
            self._logger.error(f"种子提交到下载器时发生异常: {e}", exc_info=True)
            return False, str(e)

    def _format_size(self, size: int) -> str:
        for unit in['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024: 
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} PB"