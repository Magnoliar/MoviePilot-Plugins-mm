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
from app.core.cache import TTLCache
from app.utils.http import RequestUtils
from app.schemas import NotificationType

from apscheduler.triggers.cron import CronTrigger

class SeedRescuer(_PluginBase):
    plugin_name = "种子找回助手"
    plugin_desc = "超净版辅种扫描仪。(v6.1.3 流控限制)"
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/mediasyncdel.png"
    plugin_version = "6.1.1"  # 核心升级：智能探测下载器类型 (TR/QB)，下发对应的底层专属参数组合 (download_dir / labels)
    plugin_author = "Gemini"
    
    auth_level = 1

    _enabled = False
    _notify = True
    _prowlarr_url = ""  
    _prowlarr_api = ""
    _scan_path = ""
    _downloader_name = ""
    _cron = ""
    _only_paused = True
    _hide_existing = True
    _max_depth = 3
    _path_mapping = ""
    _sleep_min = 45
    _sleep_max = 90
    
    _history_file = Path(settings.PLUGIN_DATA_PATH) / "seed_rescuer_history.json"
    
    _history_lock = threading.Lock()
    _task_lock = threading.RLock()
    _exit_event = threading.Event()

    def init_plugin(self, config: dict = None):
        self.stop_service()
        self._exit_event.clear()

        self._setup_logger()

        self.downloader_helper = DownloaderHelper()
        self.cache = TTLCache(region="SeedRescuer", maxsize=1000, ttl=86400)
        
        if not self.cache.get("stats"):
            self.cache.set("stats", {"total": 0, "rescued": 0, "existing": 0, "failed": 0})
        if not self.cache.get("status_msg"):
            self.cache.set("status_msg", "空闲中 (等待任务指令)")

        if config:
            self._enabled = config.get("enabled", False)
            self._notify = config.get("notify", True)
            self._prowlarr_url = config.get("prowlarr_url", "")
            self._prowlarr_api = config.get("prowlarr_api", "")
            self._scan_path = config.get("scan_path", "")
            self._downloader_name = config.get("downloader_name", "")
            self._cron = config.get("cron", "")
            self._only_paused = config.get("only_paused", True)
            self._hide_existing = config.get("hide_existing", True)
            self._path_mapping = config.get("path_mapping", "")
            
            def safe_int(val, default):
                try:
                    return int(val) if val not in[None, ""] else default
                except (ValueError, TypeError):
                    return default

            self._max_depth = safe_int(config.get("max_depth"), 3)
            self._sleep_min = safe_int(config.get("sleep_min"), 45)
            self._sleep_max = safe_int(config.get("sleep_max"), 90)

    def _setup_logger(self):
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

    @property
    def service_info(self) -> Optional[Any]:
        if not self._downloader_name:
            return None
        service = self.downloader_helper.get_service(name=self._downloader_name)
        if not service:
            return None
        if hasattr(service.instance, 'is_inactive') and service.instance.is_inactive():
            return None
        return service

    @property
    def downloader(self) -> Optional[Any]:
        return self.service_info.instance if self.service_info else None

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
            return[]

        return[{
            "id": "seed_rescuer_auto_task",
            "name": "种子自动找回",
            "trigger": trigger, 
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
        with self._history_lock:
            history = self._load_history()
            history[item_name] = True
            self._history_file.write_text(json.dumps(history, ensure_ascii=False), encoding='utf-8')

    def _send_notify(self, title: str, text: str):
        if self._notify:
            self.post_message(mtype=NotificationType.Plugin, title=title, text=text)

    # ==========================
    #  表单页
    # ==========================
    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
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
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content":[{"component": "VSwitch", "props": {"model": "enabled", "label": "启用定时扫描任务", "hint": "开启后根据周期在后台自动执行磁盘与下载器比对扫描。"}}] },
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content":[{"component": "VTextField", "props": {"model": "cron", "label": "自动周期", "placeholder": "0 2 * * *", "hint": "支持5位 Cron 表达式。"}}] },
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content":[{"component": "VSwitch", "props": {"model": "notify", "label": "发送通知", "hint": "开启后将在扫描/找回完成时发送通知。"}}] }
                    ]
                },
                {
                    "component": "VRow",
                    "content":[
                        {"component": "VCol", "props": {"cols": 12, "md": 6}, "content":[{"component": "VTextField", "props": {"model": "prowlarr_url", "label": "Prowlarr 检索源 URL (选填)", "placeholder": "http://192.168.1.100:9696", "hint": "若填写，将彻底绕过 MoviePilot 限制，由插件以标准 HTTP 协议直连 Prowlarr 发起自动找回。"}}] },
                        {"component": "VCol", "props": {"cols": 12, "md": 6}, "content":[{"component": "VTextField", "props": {"model": "prowlarr_api", "label": "Prowlarr API Key (选填)", "placeholder": "获取自 Prowlarr 设置", "hint": "Prowlarr 的专属 API 密钥。"}}] }
                    ]
                },
                {
                    "component": "VRow",
                    "content":[
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content":[{"component": "VTextField", "props": {"model": "scan_path", "label": "待扫描路径", "placeholder": "/media/movies", "hint": "必填。待辅种资源的本地目录，多路径用逗号分隔。"}}] },
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content":[{"component": "VTextField", "props": {"model": "path_mapping", "label": "路径转换映射", "placeholder": "/media:/downloads", "hint": "格式 `容器路径:下载器路径`。"}}] },
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content":[{"component": "VTextField", "props": {"model": "max_depth", "label": "扫描深度", "type": "number", "hint": "扫描文件层级的最大深度（推荐为3）。"}}] }
                    ]
                },
                {
                    "component": "VRow",
                    "content":[
                        {"component": "VCol", "props": {"cols": 12, "md": 3}, "content":[{"component": "VSelect", "props": {"model": "downloader_name", "label": "比对/推送 下载器", "items": downloader_options, "hint": "必须选择！用于比对跳过已有种子，及接收推送。"}}] },
                        {"component": "VCol", "props": {"cols": 12, "md": 3}, "content":[{"component": "VTextField", "props": {"model": "sleep_max", "label": "检索最大延迟(秒)", "type": "number", "hint": "Prowlarr 检索请求防封延迟。"}}] },
                        {"component": "VCol", "props": {"cols": 12, "md": 3}, "content":[{"component": "VSwitch", "props": {"model": "only_paused", "label": "强行暂停添加", "hint": "推送到下载器后强制暂停状态。"}}] },
                        {"component": "VCol", "props": {"cols": 12, "md": 3}, "content":[{"component": "VSwitch", "props": {"model": "hide_existing", "label": "过滤已在下载器的资源", "hint": "开启后，将彻底隐藏那些已在下载器中做种的健康资源。"}}] }
                    ]
                },
                {
                    "component": "VRow",
                    "content":[{
                        "component": "VCol",
                        "props": {"cols": 12},
                        "content":[{
                            "component": "VAlert",
                            "props": {"type": "success", "variant": "tonal", "class": "mt-2"},
                            "text": "🚀 独立引擎已就绪：本插件已彻底剥离系统搜索。若不配置 Prowlarr，插件将作为一个极致纯净的【孤儿种子扫描仪】，提取出绝对路径和片名列表供手工辅种；若配置 Prowlarr，则激活【自动化找回引擎】直接通过内存向 TR/QB 发起协议直写！"
                        }]
                    }]
                }
            ]
        }]
        
        return elements, {
            "enabled": self._enabled,
            "notify": self._notify,
            "prowlarr_url": self._prowlarr_url,
            "prowlarr_api": self._prowlarr_api,
            "scan_path": self._scan_path,
            "downloader_name": self._downloader_name,
            "cron": self._cron,
            "only_paused": self._only_paused,
            "hide_existing": self._hide_existing,
            "max_depth": self._max_depth,
            "path_mapping": self._path_mapping,
            "sleep_max": self._sleep_max,
            "sleep_min": self._sleep_min
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
            status_text = str(item.get("status", ""))
            # 🔥 新增：如果在页面刷新时发现开启了隐藏，直接过滤掉这些健康/已找回的种子
            if self._hide_existing and status_text in ["✅ 已存在", "✨ 已找回", "✨ 找回成功"]:
                continue
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
                    {"component": "td", "content":[
                        {"component": "div", "props": {"class": "font-weight-bold"}, "text": str(item.get("name", ""))},
                        {"component": "div", "props": {"class": "text-caption text-grey", "style": "user-select: all; cursor: pointer;"}, "text": str(item.get("path", ""))}
                    ]},
                    {"component": "td", "text": str(item.get("size_str", ""))},
                    {"component": "td", "props": {"class": status_color}, "text": status_text},
                    {"component": "td", "text": str(item.get("confidence", ""))},
                    {"component": "td", "content":[
                        {
                            "component": "VBtn",
                            "props": {"color": "primary", "variant": "tonal", "size": "small", "prepend-icon": "mdi-download"},
                            "text": "自动找回",
                            "events": {"click": {"api": "plugin/SeedRescuer/download_item", "method": "get", "params": {"item_id": item["id"]}}}
                        }
                    ]}
                ]
            })

        if not tbody_content:
            text_hint = "暂无扫描数据" if not self._hide_existing else "暂无数据 (100%匹配的已存在项已被过滤隐藏)"
            tbody_content.append({
                "component": "tr",
                "content":[{"component": "td", "props": {"colspan": 5, "class": "text-center text-grey"}, "text": text_hint}]
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
                    {"component": "VCol", "props": {"cols": 6, "md": 3, "xl": 3}, "content":[{"component": "VCard", "props": {"title": "盘内资源总计", "subtitle": str(stats.get("total", 0))}}] },
                    {"component": "VCol", "props": {"cols": 6, "md": 3, "xl": 3}, "content":[{"component": "VCard", "props": {"title": "成功辅种/找回", "subtitle": str(stats.get("rescued", 0))}}] },
                    {"component": "VCol", "props": {"cols": 6, "md": 3, "xl": 3}, "content":[{"component": "VCard", "props": {"title": "健康做种中", "subtitle": str(stats.get("existing", 0))}}] },
                    {"component": "VCol", "props": {"cols": 6, "md": 3, "xl": 3}, "content":[{"component": "VCard", "props": {"title": "需手动辅种", "subtitle": str(stats.get("failed", 0))}}] }
                ]
            },
            {
                "component": "VRow",
                "props": {"class": "mt-4 mb-4"},
                "content":[
                    {"component": "VCol", "content":[
                        {"component": "VBtn", "props": {"color": "primary", "variant": "tonal", "class": "mr-3 mb-2", "prepend-icon": "mdi-magnify"}, "text": "全盘扫描", "events": {"click": {"api": "plugin/SeedRescuer/scan_now", "method": "get"}}},
                        {"component": "VBtn", "props": {"color": "warning", "variant": "tonal", "class": "mr-3 mb-2", "prepend-icon": "mdi-test-tube"}, "text": "灰度测试", "events": {"click": {"api": "plugin/SeedRescuer/test_run", "method": "get"}}},
                        {"component": "VBtn", "props": {"color": "success", "variant": "tonal", "class": "mr-3 mb-2", "prepend-icon": "mdi-rocket"}, "text": "全量自动找回", "events": {"click": {"api": "plugin/SeedRescuer/download_all", "method": "get"}}},
                        {"component": "VBtn", "props": {"color": "error", "variant": "flat", "class": "mr-3 mb-2", "prepend-icon": "mdi-stop-circle-outline"}, "text": "强制停止任务", "events": {"click": {"api": "plugin/SeedRescuer/stop_task", "method": "get"}}},
                        {"component": "VBtn", "props": {"color": "error", "variant": "tonal", "class": "mb-2", "prepend-icon": "mdi-delete"}, "text": "重置记录", "events": {"click": {"api": "plugin/SeedRescuer/reset_history", "method": "get"}}}
                    ]}
                ]
            },
            {
                "component": "VCard",
                "props": {"title": "孤儿种子与辅助清单"},
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
                                        {"component": "th", "text": "项目详情 (包含底层绝对路径)"},
                                        {"component": "th", "text": "精准体积"},
                                        {"component": "th", "text": "辅种状态"},
                                        {"component": "th", "text": "自动匹配率"},
                                        {"component": "th", "text": "自动化"}
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
            },
            {
                "component": "VCard",
                "props": {"title": "待处理片名提取区 (供手工去 PT 站检索，复制后手动推给 qBittorrent)", "class": "mt-6", "variant": "outlined", "color": "warning"},
                "content":[
                    {
                        "component": "VTextarea",
                        "props": {
                            "modelvalue": "{{failed_list_text}}",
                            "rows": 12,
                            "readonly": True,
                            "no-resize": False,
                            "variant": "solo-filled"
                        }
                    }
                ]
            }
        ]

    def get_data(self) -> Dict[str, Any]:
        data_list = self.cache.get("items") or[]
        
        failed_names = [item['name'] for item in data_list if item.get("status") in["⏳ 待找回", "❌ 匹配失败", "❌ 需手动辅种"]]
        failed_list_text = "\n".join(failed_names)
        if not failed_list_text:
            failed_list_text = "✨ 太棒了！硬盘扫描完毕，目前没有任何待辅种的孤儿文件夹。"
            
        try:
            list_file_path = Path(getattr(settings, "LOG_PATH", "/moviepilot/logs")) / "plugins" / "seedrescuer_list.txt"
            list_file_path.write_text(failed_list_text, encoding='utf-8')
        except Exception:
            pass
        
        return {
            "failed_list_text": failed_list_text
        }

    # ==========================
    #  核心 API 及逻辑
    # ==========================
    def get_api(self) -> List[Dict[str, Any]]:
        return[
            {"path": "/scan_now", "endpoint": self.scan_now, "methods":["GET"], "summary": "扫描磁盘", "auth": "bear"},
            {"path": "/test_run", "endpoint": self.test_run, "methods": ["GET"], "summary": "灰度测试", "auth": "bear"},
            {"path": "/download_all", "endpoint": self.download_all, "methods":["GET"], "summary": "全量自动化找回", "auth": "bear"},
            {"path": "/reset_history", "endpoint": self.reset_history, "methods":["GET"], "summary": "重置找回历史记录", "auth": "bear"},
            {"path": "/download_item", "endpoint": self.download_item, "methods": ["GET"], "summary": "手动下载指定的丢失项", "auth": "bear"},
            {"path": "/stop_task", "endpoint": self.stop_task, "methods": ["GET"], "summary": "手动停止正在运行的后台任务", "auth": "bear"}
        ]
    
    def stop_task(self):
        """手动触发停止信号"""
        if not self._exit_event.is_set():
            self._exit_event.set()
            self._logger.info("收到手动中止指令，正在紧急制动后台任务...")
            self.cache.set("status_msg", "空闲中 (任务已被手动中止)")
            return {"success": True, "message": "已发送中止指令，后台任务将在当前种子处理完毕后立即停止。"}
        return {"success": False, "message": "当前没有正在运行的后台任务。"}

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
            self.cache.set("status_msg", "正在全盘精细扫描，提取孤儿文件夹...")
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
                    
                    stats["total"] += 1  # 🔥 修复：无论是否隐藏，先给总数+1，保证顶部数据看板永远准确
                    
                    if name in history:
                        status = "✨ 已找回"
                        stats["rescued"] += 1
                        conf = "100%"
                        if self._hide_existing:  # 🔥 新增：判断隐藏开关
                            continue
                    elif name in existing_torrents:
                        status = "✅ 已存在"
                        stats["existing"] += 1
                        conf = "100%"
                        if self._hide_existing:  # 原有的隐藏判断
                            continue
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
            
            msg_suffix = " (已过滤已存在项目)" if self._hide_existing else ""
            self.cache.set("status_msg", f"空闲中 (上次扫描完毕，共渲染 {len(all_items)} 个项目{msg_suffix})")
            self._logger.info(f"磁盘扫描完成，共处理 {len(items)} 个文件，展示 {len(all_items)} 项")
            return {"success": True, "message": f"扫描完毕，共发现 {len(items)} 个影视资源。"}
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
            self._exit_event.clear()  # 🔥 新增：每次启动新任务前，先把刹车松开
            self.scan_now()
            cached_items = self.cache.get("items") or []
            items =[i for i in cached_items if "待找回" in i.get("status", "")][:5]
            
            if not items: 
                self.cache.set("status_msg", "空闲中 (清单为空)")
                return {"success": False, "message": "清单中没有待找回的项目"}

            def run_test_background():
                self._logger.info(f"启动灰度测试，将尝试找回 {len(items)} 个项目")
                success_count = 0
                for idx, item in enumerate(items): 
                    if self._exit_event.is_set():
                        self._logger.warning("收到停止信号，中止测试任务")
                        self.cache.set("status_msg", "空闲中 (灰度测试已中止)")
                        break
                    
                    self.cache.set("status_msg", f"正在灰度测试: {item['name']} ({idx+1}/{len(items)})")
                    res = self.download_item(item_id=item["id"])
                    if res and res.get("success"):
                        success_count += 1
                        
                    time.sleep(random.uniform(self._sleep_min, self._sleep_max))
                    
                self.cache.set("status_msg", "空闲中 (灰度测试结束)")
                self._send_notify("灰度测试运行结束", f"测试计划共 {len(items)} 项，成功找回 {success_count} 项。")
                self._logger.info("灰度测试运行结束")
                    
            threading.Thread(target=run_test_background, daemon=True).start()
            return {"success": True, "message": f"已在后台启动灰度测试，将尝试找回 {len(items)} 个项目，请随时刷新页面查看状态。"}
        finally:
            self._task_lock.release()

    def download_all(self):
        if not self._task_lock.acquire(blocking=False):
            return {"success": False, "message": "已有任务正在运行中，请稍后再试"}
            
        try:
            self._exit_event.clear()  # 🔥 新增：每次启动新任务前，先把刹车松开
            cached_items = self.cache.get("items") or[]
            to_do =[i for i in cached_items if "待找回" in i.get("status", "")]
            
            if not to_do: 
                return {"success": False, "message": "清单中没有待找回的项目，请先执行扫描！"}

            def run_all_background():
                self._logger.info(f"启动全量自动化找回，共计 {len(to_do)} 个项目")
                success_count = 0
                for idx, item in enumerate(to_do):
                    if self._exit_event.is_set():
                        self._logger.warning("收到停止信号，中止全量自动化找回任务")
                        self.cache.set("status_msg", "空闲中 (全量找回中止)")
                        break
                    
                    self.cache.set("status_msg", f"全量自动化找回中: {item['name']} ({idx+1}/{len(to_do)})")
                    res = self.download_item(item_id=item["id"])
                    if res and res.get("success"):
                        success_count += 1
                        
                    time.sleep(random.uniform(self._sleep_min, self._sleep_max))
                    
                self.cache.set("status_msg", "空闲中 (全量找回任务结束)")
                self._send_notify("全量自动化找回结束", f"全量自动化找回计划执行完毕。共处理 {len(to_do)} 个孤儿项，自动找回 {success_count} 个。")
                self._logger.info("全量自动化找回运行结束")
                    
            threading.Thread(target=run_all_background, daemon=True).start()
            return {"success": True, "message": f"全量自动化作业已在后台启动，共计 {len(to_do)} 个任务，请随时刷新看板。"}
        finally:
            self._task_lock.release()

    def _search_prowlarr(self, query: str) -> List[dict]:
        if not self._prowlarr_url or not self._prowlarr_api:
            return[]
            
        try:
            url = f"{self._prowlarr_url.rstrip('/')}/api/v1/search"
            headers = {"X-Api-Key": self._prowlarr_api}
            params = {"query": query}
            
            res = RequestUtils().get_res(url, headers=headers, params=params)
            if res and res.status_code == 200:
                data = res.json()
                results =[]
                for item in data:
                    results.append({
                        "title": item.get("title", ""),
                        "size": item.get("size", 0),
                        "enclosure": item.get("downloadUrl", ""),
                        "site_name": item.get("indexer", "Prowlarr")
                    })
                return results
            else:
                self._logger.warning(f"  ├─ ⚠ Prowlarr 响应异常，HTTP 状态码: {res.status_code if res else 'None'}")
        except Exception as e:
            self._logger.error(f"  ├─ ❌ 连接 Prowlarr 失败: {e}", exc_info=True)
            
        return[]

    def download_item(self, item_id: str):
        if not item_id:
            return {"success": False, "message": "缺少必要参数 item_id"}

        items = self.cache.get("items") or[]
        stats = self.cache.get("stats") or {"total": 0, "rescued": 0, "existing": 0, "failed": 0}
        
        target = next((i for i in items if i["id"] == str(item_id)), None)
        if not target: 
            return {"success": False, "message": "该记录已失效，请重新扫描"}

        self._logger.info(f"▶ 开始尝试处理: [{target['name']}] (原始精准体积: {self._format_size(target['size'])})")

        if not self._prowlarr_url or not self._prowlarr_api:
            target["status"] = "❌ 需手动辅种"
            target["confidence"] = "-"
            stats["failed"] += 1
            self.cache.set("items", items)
            self.cache.set("stats", stats)
            self._logger.info(f"  └─ 🚫 Prowlarr 检索未配置。保留本地绝对路径供手工去下载器粘贴补种。")
            return {"success": False, "message": "未配置 Prowlarr 直连引擎，自动化找回已禁用。请复制界面左侧提供的绝对路径手工添加种子！"}

        clean_name = re.sub(r'[\[\]\(\)\{\}\-\_\￡\@]', ' ', target["name"]).replace(".", " ")
        clean_name = re.sub(r'\s+', ' ', clean_name).strip()

        search_queries =[
            clean_name,
            target["name"].replace(".", " ")
        ]
        clean_title = self._parse_media_name(target["name"])
        if clean_title: 
            search_queries.append(clean_title)

        search_queries = list(dict.fromkeys(search_queries))
        self._logger.info(f"  ├─ 剥离干扰符号生成检索池: {search_queries}")

        best_torrent = None
        best_diff = 1.0
        
        for idx, query in enumerate(search_queries): 
            if not query: continue
            
            # 🔥 核心修复：如果不是第一次查询（即尝试变种词），强制冷却 15 秒，规避馒头并发限制
            if idx > 0:
                self._logger.info("  ├─ [API 限流保护] 冷却中：等待 15 秒后发起变种词检索...")
                time.sleep(15)
                
            try:
                self._logger.info(f"  ├─ 直连 Prowlarr 引擎发起纯净搜索: '{query}'")
                results = self._search_prowlarr(query)
                self._logger.info(f"  ├─ Prowlarr 极速返回无过滤 Raw 数据: {len(results)} 条，进入底层比对器...")
                
                if results:
                    best_torrent, best_diff = self._match_torrent(results, target["size"], target["name"])
                    if best_torrent: 
                        break 
            except Exception as e:
                self._logger.error(f"  ├─ 引擎搜索或内部计算崩溃 [{query}]: {e}", exc_info=True)

        if best_torrent:
            success, msg = self._download_and_add(best_torrent, target["path"])
            if success:
                target["status"] = "✨ 找回成功"
                target["confidence"] = f"{100-best_diff*100:.1f}%"
                stats["rescued"] += 1
                self._save_history(target["name"])
                
                self.cache.set("items", items)
                self.cache.set("stats", stats)
                self._logger.info(f"  └─ ✔ 直写下载器成功: {target['name']}")
                return {"success": True, "message": f"找回成功！体积匹配度: {100-best_diff*100:.1f}%"}
            else:
                self._logger.warning(f"  └─ ⚠ 种子匹配成功但直写被拒: {msg}")
                return {"success": False, "message": f"直写下载器被拒: {msg}"}
        
        target["status"] = "❌ 需手动辅种"
        target["confidence"] = f"{100-best_diff*100:.1f}%" if best_diff < 1.0 else "0%"
        stats["failed"] += 1
        
        self.cache.set("items", items)
        self.cache.set("stats", stats)
        self._logger.warning(f"  └─ ❌ 匹配失败: 当前 Prowlarr 返回结果池中无可容忍误差内的匹配项，建议手工辅助。")
        return {"success": False, "message": "Prowlarr 结果池中无体积相符的种子。"}

    # ==========================
    #  内部辅助方法
    # ==========================
    def _parse_media_name(self, name: str) -> str:
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
        downloader = self.downloader
        if downloader:
            try:
                res = downloader.get_torrents()
                torrents = res[0] if isinstance(res, tuple) else res
                if torrents:
                    for t in torrents:
                        t_name = t.get('name') if isinstance(t, dict) else getattr(t, 'name', '')
                        if t_name:
                            names.add(t_name)
            except Exception as e:
                self._logger.warning(f"连接下载器比对时出错: {e}")
        return names

    def _match_torrent(self, search_results: List[dict], target_size: int, local_name: str) -> Tuple[Optional[dict], float]:
        if not search_results: 
            return None, 1.0
                
        core_tags =[w for w in["iQIYI", "MWeb", "Netflix", "NF", "Tencent", "WEB-DL", "BluRay", "REMUX", "HFR", "CC"] if w.lower() in local_name.lower()]
        
        self._logger.info(f"    └─ Prowlarr 数据流清洗... 候选数量: {len(search_results)} | 目标精准体积: {self._format_size(target_size)}")

        best_torrent = None
        best_diff = 1.0
        
        for t in search_results:
            t_size = t.get('size', 0)
            t_title = t.get('title', '')
            site_name = t.get('site_name', 'Prowlarr')
            
            if not t_size: 
                continue
                
            diff = abs(float(t_size) - target_size) / target_size
            if diff < best_diff:
                best_diff = diff

            if diff <= 0.03: 
                tag_match = True
                for tag in core_tags:
                    if tag.lower() not in t_title.lower():
                        tag_match = False
                        break
                if tag_match: 
                    self._logger.info(f"    └─[✅ 匹配器锁定] 数据源: {site_name} | Torrent源名称: {t_title} | Torrent源体积: {self._format_size(t_size)} | 误差: {diff*100:.2f}%")
                    return t, diff
                else:
                    self._logger.info(f"    └─[⏭ 跳过] 高危特征不符: {t_title}")
            else:
                self._logger.info(f"    └─[⏭ 跳过] 致命体积不符: {t_title} (Torrent体积: {self._format_size(t_size)} | 差距达: {diff*100:.2f}%)")
                    
        self._logger.info(f"    └─ 未找到绝对吻合的资源。本批次最小体积差距为: {best_diff*100:.2f}%")
        return None, best_diff

    # 核心降维打击：智能分辨 TR 与 QB，并将种子字节流强行喂给底层接口！
    def _download_and_add(self, torrent: dict, local_path: str) -> Tuple[bool, str]:
        downloader = self.downloader
        if not downloader: 
            return False, "选定下载器配置不存在或服务离线"
            
        save_dir = str(Path(local_path).parent).replace("\\", "/")
        
        if self._path_mapping and ":" in self._path_mapping:
            internal, external = self._path_mapping.split(":", 1)
            internal = internal.replace("\\", "/")
            external = external.replace("\\", "/")
            if save_dir.startswith(internal):
                save_dir = external + save_dir[len(internal):]

        torrent_url = torrent.get('enclosure', '')
        torrent_content = None

        if self._prowlarr_url and self._prowlarr_api and torrent_url.startswith('http'):
            try:
                headers = {"X-Api-Key": self._prowlarr_api}
                res = RequestUtils().get_res(torrent_url, headers=headers)
                if res and res.status_code == 200 and res.content:
                    torrent_content = res.content
                    self._logger.info("  ├─ 🚀 已成功利用 Prowlarr 引擎将真实的 .torrent 种子文件流拉取至系统内存")
                else:
                    self._logger.warning(f"  ├─ ⚠ 从 Prowlarr 拉取种子文件流失败，状态码: {res.status_code if res else 'None'}")
            except Exception as e:
                self._logger.error(f"  ├─ ❌ Prowlarr 文件流拉取异常: {e}")

        is_qb = self.downloader_helper.is_downloader("qbittorrent", service=self.service_info)
        is_tr = self.downloader_helper.is_downloader("transmission", service=self.service_info)

        try:
            # 智能构造针对不同下载器的底层参数字典 (TR 只能接受 download_dir 和 labels，QB 接收 tag)
            add_kwargs = {
                "download_dir": save_dir.rstrip("/"),
                "is_paused": self._only_paused
            }
            if torrent_content:
                add_kwargs["content"] = torrent_content
            else:
                add_kwargs["torrent_url"] = torrent_url
                
            if is_qb:
                add_kwargs["tag"] = ["SeedRescuer"]
            elif is_tr:
                add_kwargs["labels"] = ["SeedRescuer"]
                
            # 直写：此时由于绕过了所有的上层链，下载器内部将只执行最基础的接受动作，不会触发任何后置整理或重命名！
            res = downloader.add_torrent(**add_kwargs)
            success = res[0] if isinstance(res, tuple) else bool(res)
            return success, ("内存直写成功" if success else "下载器底层协议拒载")
        except Exception as e:
            self._logger.error(f"指令下发到底层下载器时遇到阻断: {e}", exc_info=True)
            return False, str(e)

    def _format_size(self, size: int) -> str:
        for unit in['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024: 
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} PB"
