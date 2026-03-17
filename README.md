# MoviePilot-Plugins
MoviePilot官方插件市场：https://github.com/jxxghp/MoviePilot-Plugins

## 第三方插件-种子找回助手

**SeedRescuer (种子找回助手) v6.1.2** 是一款专为极客玩家打造的超净版辅种与灾备恢复扫描仪。

当你经历了服务器重构、硬盘迁移或下载器数据丢失的灾难后，面对满硬盘的孤儿影视文件却无从保种时，本插件就是你的终极救生圈。它彻底剥离了常规的系统搜索链路，通过 Prowlarr API 直连和底层内存注入，实现 100% 精准的自动化“盲眼辅种”。

### ✨ 核心亮点
- **🚀 内存级直写推送**：智能探测 TR/QB 下载器，将匹配到的 `.torrent` 字节流直接强行喂给底层接口，绝对绕过任何后置整理或重命名逻辑，确保本地原文件完美校验。
- **🛡️ 骨灰级防封流控**：专治 M-Team 等严苛站点的 503 限流。内置变种词 15 秒强制冷却与全局 45~90 秒随机休眠双重限流机制，挂机全量找回安全无忧。
- **⚖️ 极精匹配与兜底过滤**：支持 0.1% 级高精度体积比对与 `WEB-DL`, `REMUX`, `iQIYI` 等压制组特征词强校验，拒绝“李鬼”种子覆盖本地文件。
- **孤儿资源极速提取**：支持一键全盘扫描并导出绝对路径与纯净片名清单，即刻化身为纯净的本地灾备扫描工具。

详细的部署说明（含 Docker Compose 与 Prowlarr 极速对接防封指南），请在安装插件后前往插件内部的设置说明中查看。

---

## 目录
- [第三方插件库开发说明](#第三方插件库开发说明)
  - [1. 目录结构](#1-目录结构)
  - [2. 插件图标](#2-插件图标)
  - [3. 插件命名](#3-插件命名)
  - [4. 依赖](#4-依赖)
  - [5. 界面开发](#5-界面开发)
- [常见问题](#常见问题)
  - [1. 如何扩展消息推送渠道？](#1-如何扩展消息推送渠道)
  - [2. 如何在插件中实现远程命令响应？](#2-如何在插件中实现远程命令响应)
  - [3. 如何在插件中对外暴露API？](#3-如何在插件中对外暴露api)
  - [4. 如何在插件中注册公共定时服务？](#4-如何在插件中注册公共定时服务)
  - [5. 如何通过插件增强MoviePilot的识别功能？](#5-如何通过插件增强moviepilot的识别功能)
  - [6. 如何扩展内建索引器的索引站点？](#6-如何扩展内建索引器的索引站点)
  - [7. 如何在插件中调用API接口？](#7-如何在插件中调用api接口)
  - [8. 如何将插件内容显示到仪表板？](#8-如何将插件内容显示到仪表板)
  - [9. 如何扩展探索功能的媒体数据源？](#9-如何扩展探索功能的媒体数据源)
  - [10. 如何扩展推荐功能的媒体数据源？](#10-如何扩展推荐功能的媒体数据源)
  - [11. 如何通过插件重载实现系统模块功能？](#11-如何通过插件重载实现系统模块功能)
  - [12. 如何通过插件扩展支持的存储类型？](#12-如何通过插件扩展支持的存储类型)
  - [13. 如何将插件功能集成到工作流？](#13-如何将插件功能集成到工作流)
  - [14. 如何在插件中通过消息持续与用户交互？](#14-如何在插件中通过消息持续与用户交互)
  - [15. 如何在插件中使用系统级统一缓存？](#15-如何在插件中使用系统级统一缓存)
  - [16. 如何在插件中注册智能体工具？](#16-如何在插件中注册智能体工具)
- [版本发布](#版本发布)
  - [1. 如何发布插件版本？](#1-如何发布插件版本)
  - [2. 如何开发V2版本的插件以及实现插件多版本兼容？](#2-如何开发v2版本的插件以及实现插件多版本兼容)

## 第三方插件库开发说明
> 请不要开发用于破解MoviePilot用户认证、色情、赌博等违法违规内容的插件，共同维护健康的开发环境！


### 1. 目录结构
- 插件仓库需要保持与本项目一致的目录结构（建议fork后修改），仅支持Github仓库，`plugins`存放插件代码，一个插件一个子目录，**子目录名必须为插件类名的小写**，插件主类在`__init__.py`中编写。
- `package.json`为插件仓库中所有插件概要信息，用于在MoviePilot的插件市场显示，其中版本号等需与插件代码保持一致，通过修改版本号可触发MoviePilot显示插件更新。 

### 2. 插件图标
- 插件图标可复用官方插件库中`icons`下已有图标，否则需使用完整的http格式的url图片链接（包括package.json中的icon和插件代码中的plugin_icon）。
- 插件的背景颜色会自动提取使用图标的主色调。

### 3. 插件命名
- 插件命名请勿与官方库插件中的插件冲突，否则会在MoviePilot版本升级时被官方插件覆盖。

### 4. 依赖
- 可在插件目录中放置`requirements.txt`文件，用于指定插件依赖的第三方库，MoviePilot会在插件安装时自动安装依赖库。

### 5. 界面开发
- 插件支持`插件配置`、`详情展示`、`仪表板Widget`三个展示页面，支持两种方式开发：
  1. 通过配置化的方式组装，使用 [Vuetify](https://vuetifyjs.com/) 组件库，所有该组件库有的组件都可以通过Json配置使用，详情参考已有插件。
  - `props`中`model`属性等效于v-model，`show`等效于v-show，其它属于会直接绑定到元素上。
  - 插件配置页面props属性支持表达式，使用`{{}}`概起来；支持事件，以`on`开头，比如：onclick。
  - 详情展示页面支持API调用,在`events`属性中定义。
  2. 通过Vue编写联邦远程组件，参考：[模块联邦开发指南](https://github.com/jxxghp/MoviePilot-Frontend/blob/v2/docs/module-federation-guide.md)


## 常见问题

### 1. 如何扩展消息推送渠道？
- 注册 `NoticeMessage` 事件响应，`event_data` 包含消息中的所有数据，参考 `IYUU消息通知` 插件：

    注册事件：
    ```python
    @eventmanager.register(EventType.NoticeMessage)
    ```

- 事件对象：
    ```json
    {
         "channel": MessageChannel|None,
         "type": NotificationType|None,
         "title": str,
         "text": str,
         "image": str,
         "userid": str|int,
    }
    ```
  
- MoviePilot中所有事件清单（V2版本），可以通过实现这些事情来扩展功能，同时插件之前也可以通过发送和监听事件实现联动（V1、V2事件清单有差异，且可能会变化，最新请参考源代码）。
```python
# 异步广播事件
class EventType(Enum):
    # 插件需要重载
    PluginReload = "plugin.reload"
    # 触发插件动作
    PluginAction = "plugin.action"
    # 插件触发事件
    PluginTriggered = "plugin.triggered"
    # 执行命令
    CommandExcute = "command.excute"
    # 站点已删除
    SiteDeleted = "site.deleted"
    # 站点已更新
    SiteUpdated = "site.updated"
    # 站点已刷新
    SiteRefreshed = "site.refreshed"
    # 转移完成
    TransferComplete = "transfer.complete"
    # 下载已添加
    DownloadAdded = "download.added"
    # 删除历史记录
    HistoryDeleted = "history.deleted"
    # 删除下载源文件
    DownloadFileDeleted = "downloadfile.deleted"
    # 删除下载任务
    DownloadDeleted = "download.deleted"
    # 收到用户外来消息
    UserMessage = "user.message"
    # 收到Webhook消息
    WebhookMessage = "webhook.message"
    # 发送消息通知
    NoticeMessage = "notice.message"
    # 订阅已添加
    SubscribeAdded = "subscribe.added"
    # 订阅已调整
    SubscribeModified = "subscribe.modified"
    # 订阅已删除
    SubscribeDeleted = "subscribe.deleted"
    # 订阅已完成
    SubscribeComplete = "subscribe.complete"
    # 系统错误
    SystemError = "system.error"
    # 刮削元数据
    MetadataScrape = "metadata.scrape"
    # 模块需要重载
    ModuleReload = "module.reload"


# 同步链式事件
class ChainEventType(Enum):
    # 名称识别
    NameRecognize = "name.recognize"
    # 认证验证
    AuthVerification = "auth.verification"
    # 认证拦截
    AuthIntercept = "auth.intercept"
    # 命令注册
    CommandRegister = "command.register"
    # 整理重命名
    TransferRename = "transfer.rename"
    # 整理拦截
    TransferIntercept = "transfer.intercept"
    # 资源选择
    ResourceSelection = "resource.selection"
    # 资源下载
    ResourceDownload = "resource.download"
    # 发现数据源
    DiscoverSource = "discover.source"
    # 媒体识别转换
    MediaRecognizeConvert = "media.recognize.convert"
    # 推荐数据源
    RecommendSource = "recommend.source"
    # 工作流执行
    WorkflowExecution = "workflow.execution"
    # 存储操作选择
    StorageOperSelection = "storage.operation"
```
  
### 2. 如何在插件中实现远程命令响应？
- 实现 `get_command()` 方法，按以下格式返回命令列表：
    ```json
    [{
        "cmd": "/douban_sync", // 动作ID，必须以/开始
        "event": EventType.PluginAction,// 事件类型，固定值
        "desc": "命令名称",
        "category": "命令菜单（微信）",
        "data": {
            "action": "douban_sync" // 动作标识
        }
    }]
    ```

- 注册 `PluginAction` 事件响应，根据 `event_data.action` 是否为插件设定的动作标识来判断是否为本插件事件：

    注册事件：
    ```python
    @eventmanager.register(EventType.PluginAction)
    ```
    
    事件判定：
    ```python
    event_data = event.event_data
    if not event_data or event_data.get("action") != "douban_sync":
        return
    ```
  
### 3. 如何在插件中对外暴露API？
- 实现 `get_api()` 方法，按以下格式返回API列表：
    ```json
    [{
        "path": "/refresh_by_domain", // API路径，必须以/开始
        "endpoint": self.refresh_by_domain, // API响应方法
        "methods": ["GET"], // 请求方式：GET/POST/PUT/DELETE
        "summary": "刷新站点数据", // API名称
        "description": "刷新对应域名的站点数据", // API描述
    }]
    ```
  注意：在插件中暴露API接口时注意安全控制，推荐使用`settings.API_TOKEN`进行身份验证。
  
- 在对应的方法中实现API响应方法逻辑，通过 `http://localhost:3001/docs` 查看API文档和调试

### 4. 如何在插件中注册公共定时服务？
- 注册公共定时服务后，可以在`设定-服务`中查看运行状态和手动启动，更加便捷。
- 实现 `get_service()` 方法，按以下格式返回服务注册信息：
    ```json
    [{
        "id": "服务ID", // 不能与其它服务ID重复
        "name": "服务名称", // 显示在服务列表中的名称
        "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
        "func": self.xxx, // 服务方法
        "kwargs": {} // 定时器参数，参考APScheduler
    }]
    ```

### 5. 如何通过插件增强MoviePilot的识别功能？
- V1按如下步骤实现，V2版本直接实现对应链式事件即可，参考ChatGPT插件。注意：只有主程序无法识别时才会触发。
- 注册 `NameRecognize` 事件，实现识别逻辑。
    ```python
    @eventmanager.register(EventType.NameRecognize)
    ```
  
- 完成识别后发送 `NameRecognizeResult` 事件，将识别结果注入主程序
    ```python
    eventmanager.send_event(
        EventType.NameRecognizeResult,
        {
            'title': title, # 原传入标题
            'name': str, # 识别的名称
            'year': str, # 识别的年份
            'season': int, # 识别的季号
            'episode': int, # 识别的集号
        }
    )
    ```
  
- 注意：识别请求需要在15秒内响应，否则结果会被丢弃；**插件未启用或参数不完整时应立即回复空结果事件，避免主程序等待；** 多个插件开启识别功能时，以先收到的识别结果事件为准。
    ```python
    eventmanager.send_event(
        EventType.NameRecognizeResult,
        {
            'title': title # 结果只含原标题，代表空识别结果事件
        }
    )
    ```
  
### 6. 如何扩展内建索引器的索引站点？
- 通过调用 `SitesHelper().add_indexer(domain: str, indexer: dict)` 方法，新增或修改内建索引器的支持范围，其中`indexer`为站点配置Json，格式示例如下：

  示例一：
  ```json
  {
    "id": "nyaa",
    "name": "Nyaa",
    "domain": "https://nyaa.si/",
    "encoding": "UTF-8",
    "public": true,
    "proxy": true,
    "result_num": 100,
    "timeout": 30,
    "search": {
      "paths": [
        {
          "path": "?f=0&c=0_0&q={keyword}",
          "method": "get"
        }
      ]
    },
    "browse": {
      "path": "?p={page}",
      "start": 1
    },
    "torrents": {
      "list": {
        "selector": "table.torrent-list > tbody > tr"
      },
      "fields": {
        "id": {
          "selector": "a[href*=\"/view/\"]",
          "attribute": "href",
          "filters": [
            {
              "name": "re_search",
              "args": [
                "\\d+",
                0
              ]
            }
          ]
        },
        "title": {
          "selector": "td:nth-child(2) > a"
        },
        "details": {
          "selector": "td:nth-child(2) > a",
          "attribute": "href"
        },
        "download": {
          "selector": "td:nth-child(3) > a[href*=\"/download/\"]",
          "attribute": "href"
        },
        "date_added": {
          "selector": "td:nth-child(5)"
        },
        "size": {
          "selector": "td:nth-child(4)"
        },
        "seeders": {
          "selector": "td:nth-child(6)"
        },
        "leechers": {
          "selector": "td:nth-child(7)"
        },
        "grabs": {
          "selector": "td:nth-child(8)"
        },
        "downloadvolumefactor": {
          "case": {
            "*": 0
          }
        },
        "uploadvolumefactor": {
          "case": {
            "*": 1
          }
        }
      }
    }
  }
  ```

  示例二：
  ```json
  {
      "id": "xxx",
      "name": "站点名称",
      "domain": "https://www.xxx.com/",
      "ext_domains": [
        "https://www.xxx1.com/",
        "https://www.xxx2.com/"
      ],
      "encoding": "UTF-8",
      "public": false,
      "search": {
        "paths": [
          {
            "path": "torrents.php",
            "method": "get"
          }
        ],
        "params": {
          "search": "{keyword}",
          "search_area": 4
        },
        "batch": {
          "delimiter": " ",
          "space_replace": "_"
        }
      },
      "category": {
        "movie": [
          {
            "id": 401,
            "cat": "Movies",
            "desc": "Movies电影"
          },
          {
            "id": 405,
            "cat": "Anime",
            "desc": "Animations动漫"
          },
          {
            "id": 404,
            "cat": "Documentary",
            "desc": "Documentaries纪录片"
          }
        ],
        "tv": [
          {
            "id": 402,
            "cat": "TV",
            "desc": "TV Series电视剧"
          },
          {
            "id": 403,
            "cat": "TV",
            "desc": "TV Shows综艺"
          },
          {
            "id": 404,
            "cat": "Documentary",
            "desc": "Documentaries纪录片"
          },
          {
            "id": 405,
            "cat": "Anime",
            "desc": "Animations动漫"
          }
        ]
      },
      "torrents": {
        "list": {
          "selector": "table.torrents > tr:has(\"table.torrentname\")"
        },
        "fields": {
          "id": {
            "selector": "a[href*=\"details.php?id=\"]",
            "attribute": "href",
            "filters": [
              {
                "name": "re_search",
                "args": [
                  "\\d+",
                  0
                ]
              }
            ]
          },
          "title_default": {
            "selector": "a[href*=\"details.php?id=\"]"
          },
          "title_optional": {
            "optional": true,
            "selector": "a[title][href*=\"details.php?id=\"]",
            "attribute": "title"
          },
          "title": {
            "text": "{% if fields['title_optional'] %}{{ fields['title_optional'] }}{% else %}{{ fields['title_default'] }}{% endif %}"
          },
          "details": {
            "selector": "a[href*=\"details.php?id=\"]",
            "attribute": "href"
          },
          "download": {
            "selector": "a[href*=\"download.php?id=\"]",
            "attribute": "href"
          },
          "imdbid": {
            "selector": "div.imdb_100 > a",
            "attribute": "href",
            "filters": [
              {
                "name": "re_search",
                "args": [
                  "tt\\d+",
                  0
                ]
              }
            ]
          },
          "date_elapsed": {
            "selector": "td:nth-child(4) > span",
            "optional": true
          },
          "date_added": {
            "selector": "td:nth-child(4) > span",
            "attribute": "title",
            "optional": true
          },
          "size": {
            "selector": "td:nth-child(5)"
          },
          "seeders": {
            "selector": "td:nth-child(6)"
          },
          "leechers": {
            "selector": "td:nth-child(7)"
          },
          "grabs": {
            "selector": "td:nth-child(8)"
          },
          "downloadvolumefactor": {
            "case": {
              "img.pro_free": 0,
              "img.pro_free2up": 0,
              "img.pro_50pctdown": 0.5,
              "img.pro_50pctdown2up": 0.5,
              "img.pro_30pctdown": 0.3,
              "*": 1
            }
          },
          "uploadvolumefactor": {
            "case": {
              "img.pro_50pctdown2up": 2,
              "img.pro_free2up": 2,
              "img.pro_2up": 2,
              "*": 1
            }
          },
          "description": {
            "selector": "td:nth-child(2) > table > tr > td.embedded > span[style]",
            "contents": -1
          },
          "labels": {
            "selector": "td:nth-child(2) > table > tr > td.embedded > span.tags"
          }
        }
      }
    }
  ```
- 需要注意的是，如果你没有完成用户认证，通过插件配置进去的索引站点也是无法正常使用的。
- **请不要添加对黄赌毒站点的支持，否则随时封闭接口。** 

### 7. 如何在插件中调用API接口？
**（仅支持 `v1.8.4+` 版本）**
- 在插件的数据页面支持`GET/POST`API接口调用，可调用插件自身、主程序或其它插件的API。
- 在`get_page`中定义好元素的事件，以及相应的API参数，具体可参考插件`豆瓣想看`：
```json
{
  "component": "VDialogCloseBtn", // 触发事件的元素
  "events": {
    "click": { // 点击事件
      "api": "plugin/DoubanSync/delete_history", // API的相对路径
      "method": "get", // GET/POST
      "params": {
        // API上送参数
        "doubanid": ""
      }
    }
  }
}
```
- 每次API调用完成后，均会自动刷新一次插件数据页。

### 8. 如何将插件内容显示到仪表板？
**（仅支持 `v1.8.7+` 版本）**
- 将插件的内容显示到仪表盘，并支持定义占据的单元格大小，插件产生的仪表板仅管理员可见。
- 1. 根据插件需要展示的Widget内容规划展示内容的样式和规格，也可设计多个规格样式并提供配置项供用户选择。
- 2. 实现 `get_dashboard_meta` 方法，定义仪表板key及名称，支持一个插件有多个仪表板：
```python
def get_dashboard_meta(self) -> Optional[List[Dict[str, str]]]:
    """
    获取插件仪表盘元信息
    返回示例：
        [{
            "key": "dashboard1", // 仪表盘的key，在当前插件范围唯一
            "name": "仪表盘1" // 仪表盘的名称
        }, {
            "key": "dashboard2",
            "name": "仪表盘2"
        }]
    """
    pass
```
- 3. 实现 `get_dashboard` 方法，根据key返回仪表盘的详细配置信息，包括仪表盘的cols列配置（适配不同屏幕），以及仪表盘的页面配置json，具体可参考插件`站点数据统计`：
```python
def get_dashboard(self, key: str, **kwargs) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]]:
    """
    获取插件仪表盘页面，需要返回：1、仪表板col配置字典；2、全局配置（自动刷新等）；3、仪表板页面元素配置json（含数据）
    1、col配置参考：
    {
        "cols": 12, "md": 6
    }
    2、全局配置参考：
    {
        "refresh": 10, // 自动刷新时间，单位秒
        "border": True, // 是否显示边框，默认True，为False时取消组件边框和边距，由插件自行控制
        "title": "组件标题", // 组件标题，如有将显示该标题，否则显示插件名称
        "subtitle": "组件子标题", // 组件子标题，缺省时不展示子标题
    }
    3、页面配置使用Vuetify组件拼装，参考：https://vuetifyjs.com/

    kwargs参数可获取的值：1、user_agent：浏览器UA

    :param key: 仪表盘key，根据指定的key返回相应的仪表盘数据，缺省时返回一个固定的仪表盘数据（兼容旧版）
    """
    pass
```

### 9. 如何扩展探索功能的媒体数据源？
**（仅支持 `v2.2.7+` 版本）**
- 探索功能仅内置`TheMovieDb`、`豆瓣`和`Bangumi`数据源，可通过插件扩展探索功能的数据源范围，按以下方法开发插件（参考`TheTVDB探索`插件）：
- 1. 实现`ChainEventType.DiscoverSource`链式事件响应，将额外的媒体数据源塞入事件数据`extra_sources`数组中（注意：如果事件中已经有其它数据源，需要叠加而不是替换，避免影响其它插件塞入的数据）
  
  - `name`：数据源名称
  - `mediaid_prefix`：数据源的唯一ID
  - `api_path`：数据获取API相对路径，需要在插件中实现API接口功能，GET模式接收过滤参数（注意：page参数默认需要有），返回`List[schemas.MediaInfo])`格式数据（注意：mediaid_prefix和media_id需要赋值，用于唯一索引媒体详细信息和转换媒体数据）。
  - `filter_params`：数据源过滤参数名的字典，相关参数会传入插件API的GET请求中
  - `filter_ui`：数据过滤选项的UI配置json，与插件配置表单方式一致
  - `depends`: UI依赖关系字典Dict[str, list]，关过滤条件存在依赖关系时需要设置，以便上级条件变化时清空下级条件值

```python
class DiscoverMediaSource(BaseModel):
    """
    探索媒体数据源的基类
    """
    name: str = Field(..., description="数据源名称")
    mediaid_prefix: str = Field(..., description="媒体ID的前缀，不含:")
    api_path: str = Field(..., description="媒体数据源API地址")
    filter_params: Optional[Dict[str, Any]] = Field(default=None, description="过滤参数")
    filter_ui: Optional[List[dict]] = Field(default=[], description="过滤参数UI配置")

class DiscoverSourceEventData(ChainEventData):
    """
    DiscoverSource 事件的数据模型
    Attributes:
        # 输出参数
        extra_sources (List[DiscoverMediaSource]): 额外媒体数据源
    """
    # 输出参数
    extra_sources: List[DiscoverMediaSource] = Field(default_factory=list, description="额外媒体数据源")
```

- 2. 实现`ChainEventType.MediaRecognizeConvert`链式事件响应（**可选**，如不实现则默认按标题重新识别媒体信息），根据媒体ID和转换类型，返回TheMovieDb或豆瓣的媒体数据，将转换后的数据注入事件数据`media_dict`中，可参考`app/chain/media.py`中的`get_tmdbinfo_by_bangumiid`。

  - `mediaid`：媒体ID，格式为`mediaid_prefix:media_id`，如 tmdb:12345、douban:1234567
  - `convert_type`：转换类型，仅支持：themoviedb/douban，需要转换为对应的媒体数据并返回
  - `media_dict`：转换后的媒体数据，格式为`TheMovieDb/豆瓣`的媒体数据

```python
class MediaRecognizeConvertEventData(ChainEventData):
    """
    MediaRecognizeConvert 事件的数据模型
    Attributes:
        # 输入参数
        mediaid (str): 媒体ID，格式为`前缀:ID值`，如 tmdb:12345、douban:1234567
        convert_type (str): 转换类型 仅支持：themoviedb/douban，需要转换为对应的媒体数据并返回
        # 输出参数
        media_dict (dict): TheMovieDb/豆瓣的媒体数据
    """
    # 输入参数
    mediaid: str = Field(..., description="媒体ID")
    convert_type: str = Field(..., description="转换类型（themoviedb/douban）")
    # 输出参数
    media_dict: dict = Field(default=dict, description="转换后的媒体信息（TheMovieDb/豆瓣）")
```
- 3. 启用插件后，点击探索功能将自动生成额外的数据源标签及页面，页面中选择不同的过滤条件时会重新触发API请求。

### 10. 如何扩展推荐功能的媒体数据源？
**（仅支持 `v2.2.8+` 版本）**
- 实现`ChainEventType.RecommendSource`链式事件响应，将额外的媒体数据源塞入事件数据`extra_sources`数组中（注意：如果事件中已经有其它数据源，需要叠加而不是替换，避免影响其它插件塞入的数据）

  - `name`：数据源名称
  - `api_path`：数据获取API相对路径，需要在插件中实现API接口功能，GET模式接收过滤参数（注意：page参数默认需要有），返回`List[schemas.MediaInfo])`格式数据，参考`app/api/endpoints/recommend.py` 中的 `tmdb_trending`。

```python
class RecommendMediaSource(BaseModel):
    """
    推荐媒体数据源的基类
    """
    name: str = Field(..., description="数据源名称")
    api_path: str = Field(..., description="媒体数据源API地址")

class RecommendSourceEventData(ChainEventData):
    """
    RecommendSource 事件的数据模型
    Attributes:
        # 输出参数
        extra_sources (List[RecommendMediaSource]): 额外媒体数据源
    """
    # 输出参数
    extra_sources: List[RecommendMediaSource] = Field(default_factory=list, description="额外媒体数据源")
```

### 11. 如何通过插件重载实现系统模块功能？
**（仅支持 `v2.4.4+` 版本）**
- MoviePilot中通过`chain`层实现业务逻辑，在`modules`中实现各自独立的功能模块。`chain`处理链通过查找`modules`中实现了所需方法（比如: post_message）的所有模块并按一定的规则执行，从而编排各模块能力来实现复杂的业务功能。v2.4.4+版本中赋于插件胁持系统模块的能力，可以通过插件来重新实现系统所有内置模块的功能，比如支持新的下载器、媒体服务器等（在用户界面中配合新增自定义下载器和媒体服务器）。
- 1. 在插件中实现`get_module`方法，申明插件要重载的模块方法。所有可用的模块方法名参考`chain`目录下的处理链文件（run_module方法的第一个参数），公共处理在`chain/__init__.py`中，方法入参和出参需要保持一致。
```python
def get_module(self) -> Dict[str, Any]:
    """
    获取插件模块声明，用于胁持系统模块实现（方法名：方法实现）
    {
        "id1": self.xxx1,
        "id2": self.xxx2,
    }
    """
    pass
```
- 2. 在插件中实现声名的方法逻辑，处理链执行时，会优先处理插件声明的方法。如果插件方法未实现或者返回`None`，将继续执行下一个插件或者系统模块的相同声明方法；如果对应的方法需要返回是的列表对象，则会执行所有插件和系统模块的方法后将结果组合返回。

### 12. 如何通过插件扩展支持的存储类型？
**（仅支持 `v2.4.4+` 版本）**
- 1. 用户在系统设定存储中新增自定义存储，并设定一个自定义类型和名称，该类型与插件绑定，用于插件判断使用。或者在插件启动时直接注册自定义存储。
```python
# 检查是否有xxx网盘选项，如没有则自动添加
storage_helper = StorageHelper()
storages = StorageHelper().get_storagies()
if not any(s.type == "xxx" for s in storages):
    # 添加存储配置
    storage_helper.add_storage("xxx", name="xxx网盘", conf={})
```
- 2. 在插件的存储操作类中，实现以下对应的文件操作（具体可参考：app/modules/filemanager/storages/\__init__.py），不支持的可跳过
```python
class XxxApi:

    def list(self, fileitem: schemas.FileItem) -> List[schemas.FileItem]:
        """
        浏览文件
        """
        pass

    def create_folder(self, fileitem: schemas.FileItem, name: str) -> Optional[schemas.FileItem]:
        """
        创建目录
        :param fileitem: 父目录
        :param name: 目录名
        """
        pass

    def get_folder(self, path: Path) -> Optional[schemas.FileItem]:
        """
        获取目录，如目录不存在则创建
        """
        pass

    def get_item(self, path: Path) -> Optional[schemas.FileItem]:
        """
        获取文件或目录，不存在返回None
        """
        pass

    def get_parent(self, fileitem: schemas.FileItem) -> Optional[schemas.FileItem]:
        """
        获取父目录
        """
        return self.get_item(Path(fileitem.path).parent)

    def delete(self, fileitem: schemas.FileItem) -> bool:
        """
        删除文件
        """
        pass

    def rename(self, fileitem: schemas.FileItem, name: str) -> bool:
        """
        重命名文件
        """
        pass

    def download(self, fileitem: schemas.FileItem, path: Path = None) -> Path:
        """
        下载文件，保存到本地，返回本地临时文件地址
        :param fileitem: 文件项
        :param path: 文件保存路径
        """
        pass

    def upload(self, fileitem: schemas.FileItem, path: Path, new_name: Optional[str] = None) -> Optional[schemas.FileItem]:
        """
        上传文件
        :param fileitem: 上传目录项
        :param path: 本地文件路径
        :param new_name: 上传后文件名
        """
        pass

    def detail(self, fileitem: schemas.FileItem) -> Optional[schemas.FileItem]:
        """
        获取文件详情
        """
        pass

    def copy(self, fileitem: schemas.FileItem, path: Path, new_name: str) -> bool:
        """
        复制文件
        :param fileitem: 文件项
        :param path: 目标目录
        :param new_name: 新文件名
        """
        pass

    def move(self, fileitem: schemas.FileItem, path: Path, new_name: str) -> bool:
        """
        移动文件
        :param fileitem: 文件项
        :param path: 目标目录
        :param new_name: 新文件名
        """
        pass

    def link(self, fileitem: schemas.FileItem, target_file: Path) -> bool:
        """
        硬链接文件
        """
        pass

    def softlink(self, fileitem: schemas.FileItem, target_file: Path) -> bool:
        """
        软链接文件
        """
        pass

    def usage(self) -> Optional[schemas.StorageUsage]:
        """
        存储使用情况
        """
        pass
```
- 3. 实现 `ChainEventType.StorageOperSelection`链式事件响应，根据传入的存储对象名称判断是否为该插件支持的存储，如是则返回存储操作对象
```python
@eventmanager.register(ChainEventType.StorageOperSelection)
def storage_oper_selection(self, event: Event):
    """
    监听存储选择事件，返回当前类为操作对象
    """
    if not self._enabled:
        return
    event_data: StorageOperSelectionEventData = event.event_data
    if event_data.storage == "xxx":
        event_data.storage_oper = self.api # api为插件的存储操作对象
```

- 4. 参考 11 实现`get_module`在插件中声明和实现以下模块方法（具体可参考：app/modules/filemanager/\__init__.py），其实就是对上一步的方法再做一下封装：
```python
def get_module(self) -> Dict[str, Any]:
    """
    获取插件模块声明，用于胁持系统模块实现（方法名：方法实现）
    {
        "id1": self.xxx1,
        "id2": self.xxx2,
    }
    """
    return {
        "list_files": self.list_files,
        "any_files": self.any_files,
        "download_file": self.download_file,
        "upload_file": self.upload_file,
        "delete_file": self.delete_file,
        "rename_file": self.rename_file,
        "get_file_item": self.get_file_item,
        "get_parent_item": self.get_parent_item,
        "snapshot_storage": self.snapshot_storage,
        "storage_usage": self.storage_usage,
        "support_transtype": self.support_transtype
    }

def list_files(self, fileitem: schemas.FileItem, recursion: bool = False) -> Optional[List[schemas.FileItem]]:
    """
    查询当前目录下所有目录和文件
    """
    
    if fileitem.storage != "xxx":
        return None

    def __get_files(_item: FileItem, _r: Optional[bool] = False):
        """
        递归处理
        """
        _items = self.api.list(_item)
        if _items:
            if _r:
                for t in _items:
                    if t.type == "dir":
                        __get_files(t, _r)
                    else:
                        result.append(t)
            else:
                result.extend(_items)

    # 返回结果
    result = []
    __get_files(fileitem, recursion)

    return result

def any_files(self, fileitem: schemas.FileItem, extensions: list = None) -> Optional[bool]:
    """
    查询当前目录下是否存在指定扩展名任意文件
    """
    if fileitem.storage != "xxx":
        return None
    
    def __any_file(_item: FileItem):
        """
        递归处理
        """
        _items = self.api.list(_item)
        if _items:
            if not extensions:
                return True
            for t in _items:
                if (t.type == "file"
                        and t.extension
                        and f".{t.extension.lower()}" in extensions):
                    return True
                elif t.type == "dir":
                    if __any_file(t):
                        return True
        return False

    # 返回结果
    return __any_file(fileitem)

def download_file(self, fileitem: schemas.FileItem, path: Path = None) -> Optional[Path]:
    """
    下载文件
    :param fileitem: 文件项
    :param path: 本地保存路径
    """
    if fileitem.storage != "xxx":
        return None
    
    return self.api.download(fileitem, path)

def upload_file(self, fileitem: schemas.FileItem, path: Path,
                new_name: Optional[str] = None) -> Optional[schemas.FileItem]:
    """
    上传文件
    :param fileitem: 保存目录项
    :param path: 本地文件路径
    :param new_name: 新文件名
    """
    if fileitem.storage != "xxx":
        return None
    
    return self.api.upload(fileitem, path, new_name)

def delete_file(self, fileitem: schemas.FileItem) -> Optional[bool]:
    """
    删除文件或目录
    """
    if fileitem.storage != "xxx":
        return None
    
    return self.api.delete(fileitem)

def rename_file(self, fileitem: schemas.FileItem, name: str) -> Optional[bool]:
    """
    重命名文件或目录
    """
    if fileitem.storage != "xxx":
        return None
    
    return self.api.rename(fileitem, name)

def get_file_item(self, storage: str, path: Path) -> Optional[schemas.FileItem]:
    """
    根据路径获取文件项
    """
    if storage != "xxx":
        return None
    
    return self.api.get_item(path)

def get_parent_item(self, fileitem: schemas.FileItem) -> Optional[schemas.FileItem]:
    """
    获取上级目录项
    """
    if fileitem.storage != "xxx":
        return None
    
    return self.api.get_parent(fileitem)

def snapshot_storage(self, storage: str, path: Path) -> Optional[Dict[str, float]]:
    """
    快照存储
    """
    if storage != "xxx":
        return None
    
    files_info = {}

    def __snapshot_file(_fileitm: schemas.FileItem):
        """
        递归获取文件信息
        """
        if _fileitm.type == "dir":
            for sub_file in self.api.list(_fileitm):
                __snapshot_file(sub_file)
        else:
            files_info[_fileitm.path] = _fileitm.size

    fileitem = self.api.get_item(path)
    if not fileitem:
        return {}

    __snapshot_file(fileitem)

    return files_info

def storage_usage(self, storage: str) -> Optional[schemas.StorageUsage]:
    """
    存储使用情况
    """
    return self.api.usage()

@staticmethod
def support_transtype(storage: str) -> Optional[dict]:
    """
    获取支持的整理方式
    """
    return {
        "move": "移动",
        "copy": "复制"
    }
```

### 13. 如何将插件功能集成到工作流？
**（仅支持 v2.4.8+ 版本）**
- 插件实现以下接口，声明插件支持的动作实现
```python
def get_actions(self) -> List[Dict[str, Any]]:
    """
    获取插件工作流动作
    [{
        "id": "动作ID",
        "name": "动作名称",
        "func": self.xxx,
        "kwargs": {} # 需要附加传递的参数
    }]

    对实现函数的要求：
    1、函数的第一个参数固定为 ActionContent 实例，如需要传递额外参数，在kwargs中定义
    2、函数的返回：执行状态 True / False，更新后的 ActionContent 实例
    """
    pass
```
- 编辑工作流流程，添加`调用插件`组件，选择该插件的对应动作，将插件的功能串接到工作流程中

### 14. 如何在插件中通过消息持续与用户交互？
**（仅支持 v2.5.7+ 版本）**
- 插件可以通过实现命令响应和消息按钮回调实现与用户的持续交互对话，支持多轮对话和菜单式操作，适用于支持按钮回调的通知渠道（如Telegram、Slack等）。

- 1. 实现远程命令响应，参考第2个常见问题实现 `get_command()` 方法和 `PluginAction` 事件响应：
    ```python
    def get_command(self) -> List[Dict[str, Any]]:
        """
        注册插件远程命令
        """
        return [{
            "cmd": "/interactive_demo",
            "event": EventType.PluginAction,
            "desc": "交互演示",
            "category": "插件交互",
            "data": {
                "action": "interactive_demo"
            }
        }]

    @eventmanager.register(EventType.PluginAction)
    def command_action(self, event: Event):
        """
        远程命令响应
        """
        event_data = event.event_data
        if not event_data or event_data.get("action") != "interactive_demo":
            return
        
        # 获取用户信息
        channel = event_data.get("channel")
        source = event_data.get("source")
        user = event_data.get("user")
        
        # 发送带有交互按钮的消息
        self._send_main_menu(channel, source, user)
    ```

- 2. 注册 `MessageAction` 事件响应，处理用户的按钮回调：
    ```python
    @eventmanager.register(EventType.MessageAction)
    def message_action(self, event: Event):
        """
        处理消息按钮回调
        """
        event_data = event.event_data
        if not event_data:
            return
            
        # 检查是否为本插件的回调
        plugin_id = event_data.get("plugin_id")
        if plugin_id != self.__class__.__name__:
            return
            
        # 获取回调数据
        text = event_data.get("text", "")
        channel = event_data.get("channel")
        source = event_data.get("source")
        userid = event_data.get("userid")
        # 获取原始消息ID和聊天ID（用于直接更新原消息）
        original_message_id = event_data.get("original_message_id")
        original_chat_id = event_data.get("original_chat_id")
        
        # 根据回调内容处理不同的交互
        if text == "menu1":
            self._handle_menu1(channel, source, userid, original_message_id, original_chat_id)
        elif text == "menu2":
            self._handle_menu2(channel, source, userid, original_message_id, original_chat_id)
        elif text == "back":
            self._send_main_menu(channel, source, userid, original_message_id, original_chat_id)
        elif text.startswith("action_"):
            action_id = text.replace("action_", "")
            self._handle_action(action_id, channel, source, userid, original_message_id, original_chat_id)
    ```

- 3. 实现具体的交互处理方法，在消息中使用 `[PLUGIN]插件ID|内容` 格式的按钮：
    ```python
    def _send_main_menu(self, channel, source, userid, original_message_id=None, original_chat_id=None):
        """
        发送主菜单
        """
        buttons = [
            [
                {"text": "🎬 媒体管理", "callback_data": f"[PLUGIN]{self.__class__.__name__}|menu1"},
                {"text": "⚙️ 系统设置", "callback_data": f"[PLUGIN]{self.__class__.__name__}|menu2"}
            ],
            [
                {"text": "📊 查看状态", "callback_data": f"[PLUGIN]{self.__class__.__name__}|status"}
            ]
        ]
        
        self.post_message(
            channel=channel,
            title="🤖 插件交互演示",
            text="请选择要执行的操作：",
            userid=userid,
            buttons=buttons,
            original_message_id=original_message_id,
            original_chat_id=original_chat_id
        )

    def _handle_menu1(self, channel, source, userid, original_message_id, original_chat_id):
        """
        处理媒体管理菜单
        """
        buttons = [
            [
                {"text": "🔍 搜索媒体", "callback_data": f"[PLUGIN]{self.__class__.__name__}|action_search"},
                {"text": "📥 下载管理", "callback_data": f"[PLUGIN]{self.__class__.__name__}|action_download"}
            ],
            [
                {"text": "🔙 返回主菜单", "callback_data": f"[PLUGIN]{self.__class__.__name__}|back"}
            ]
        ]
        
        self.post_message(
            channel=channel,
            title="🎬 媒体管理",
            text="选择媒体管理功能：",
            userid=userid,
            buttons=buttons,
            original_message_id=original_message_id,
            original_chat_id=original_chat_id
        )

    def _handle_action(self, action_id, channel, source, userid, original_message_id, original_chat_id):
        """
        处理具体动作
        """
        if action_id == "search":
            # 执行搜索逻辑
            result = "搜索功能已执行"
        elif action_id == "download":
            # 执行下载逻辑
            result = "下载管理已开启"
        else:
            result = "未知操作"
            
        # 发送执行结果并提供返回按钮
        buttons = [
            [{"text": "🔙 返回主菜单", "callback_data": f"[PLUGIN]{self.__class__.__name__}|back"}]
        ]
        
        self.post_message(
            channel=channel,
            title="✅ 操作完成",
            text=result,
            userid=userid,
            buttons=buttons,
            original_message_id=original_message_id,
            original_chat_id=original_chat_id
        )
    ```

- 注意事项：
  - 回调按钮的 `callback_data` 必须使用 `[PLUGIN]插件ID|内容` 格式，其中插件ID为插件类名
  - 只有支持按钮回调的通知渠道（如Telegram、Slack）才能使用此功能
  - 建议在交互中保存用户状态数据，以支持复杂的多步骤操作
  - 可以结合插件数据存储功能保存用户的交互历史和偏好设置

### 15. 如何在插件中使用系统级统一缓存？
**（仅支持 `v2.7.4+` 版本）**
- MoviePilot提供了统一的缓存系统，支持内存缓存、文件系统缓存和Redis缓存自动管理，当有Redis时优先使用Redis，否则使用内存或文件系统。插件可以通过系统提供的缓存接口实现高效的缓存管理，无需关心系统设置。

- 1. 使用缓存装饰器：
    ```python
    from app.core.cache import cached
    
    class MyPlugin(_PluginBase):
        @cached(region="my_plugin", ttl=3600)
        def get_data(self, key: str):
            """
            使用缓存装饰器，缓存结果1小时
            """
            # 复杂的计算或网络请求
            return expensive_operation(key)
        
        @cached(region="my_plugin_async", ttl=1800, skip_none=True)
        async def get_async_data(self, key: str):
            """
            异步函数缓存，跳过None值
            """
            return await async_expensive_operation(key)
    ```

- 2. 使用TTLCache类：
    ```python
    from app.core.cache import TTLCache
    
    class MyPlugin(_PluginBase):
        def __init__(self):
            super().__init__()
            # 创建缓存实例，最大128项，TTL 30分钟
            self.cache = TTLCache(region="my_plugin", maxsize=128, ttl=1800)
        
        def process_data(self, key: str):
            # 检查缓存
            if key in self.cache:
                return self.cache[key]
            
            # 计算并缓存结果
            result = expensive_operation(key)
            self.cache[key] = result
            return result
        
        def clear_cache(self):
            """
            清理插件缓存
            """
            self.cache.clear()
    ```

- 3. 使用文件缓存后端（适用于大文件缓存）：
    ```python
    from app.core.cache import FileCache, AsyncFileCache
    from pathlib import Path
    
    class MyPlugin(_PluginBase):
        def __init__(self):
            super().__init__()
            # 获取文件缓存后端，支持Redis和文件系统
            self.file_cache = FileCache(
                base=Path("/tmp/my_plugin_cache"),
                ttl=86400  # 24小时
            )
        
        def cache_large_file(self, key: str, data: bytes):
            """
            缓存大文件数据
            """
            self.file_cache.set(key, data, region="large_files")
        
        def get_cached_file(self, key: str) -> Optional[bytes]:
            """
            获取缓存的文件数据
            """
            return self.file_cache.get(key, region="large_files")
        
        async def async_cache_operations(self):
            """
            异步文件缓存操作
            """
            async_cache = AsyncFileCache(
                base=Path("/tmp/my_plugin_async_cache"),
                ttl=3600
            )
            
            # 异步设置缓存
            await async_cache.set("async_key", b"async_data", region="async_files")
            
            # 异步获取缓存
            data = await async_cache.get("async_key", region="async_files")
            
            await async_cache.close()
    ```

- 4. 直接使用缓存后端（高级用法）：
    ```python
    from app.core.cache import Cache
    
    class MyPlugin(_PluginBase):
        def __init__(self):
            super().__init__()
            # 直接获取缓存后端实例，系统自动选择Redis或内存缓存
            self.cache_backend = Cache(maxsize=256, ttl=3600)
        
        def custom_cache_operation(self, key: str, value: Any):
            """
            自定义缓存操作
            """
            # 设置缓存
            self.cache_backend.set(key, value, region="custom_region")
            
            # 检查缓存是否存在
            if self.cache_backend.exists(key, region="custom_region"):
                # 获取缓存
                cached_value = self.cache_backend.get(key, region="custom_region")
                return cached_value
            
            return None
        
        def iterate_cache_items(self):
            """
            遍历缓存项
            """
            for key, value in self.cache_backend.items(region="custom_region"):
                print(f"缓存键: {key}, 值: {value}")
        
        def cleanup(self):
            """
            清理缓存
            """
            self.cache_backend.clear(region="custom_region")
            self.cache_backend.close()
    ```

- 5. 缓存装饰器参数说明：
    ```python
    @cached(
        region="my_plugin",           # 缓存区域，用于隔离不同插件的缓存
        maxsize=512,                  # 最大缓存条目数（仅内存缓存有效）
        ttl=1800,                     # 缓存存活时间（秒）
        skip_none=True,               # 是否跳过None值缓存
        skip_empty=False              # 是否跳过空值缓存（空列表、空字典等）
    )
    def my_function(self, param):
        pass
    ```

- 6. 缓存管理功能：
    ```python
    class MyPlugin(_PluginBase):
        @cached(region="my_plugin")
        def cached_function(self, param):
            return expensive_operation(param)
        
        def clear_my_cache(self):
            """
            清理指定区域的缓存
            """
            self.cached_function.cache_clear()
        
        def get_cache_info(self):
            """
            获取缓存信息
            """
            cache_region = self.cached_function.cache_region
            return f"缓存区域: {cache_region}"
    ```

- 7. 缓存后端自动选择：
    - 系统会根据配置自动选择缓存后端：
        - `CACHE_BACKEND_TYPE=redis`：使用Redis作为缓存后端
        - `CACHE_BACKEND_TYPE=memory`：使用内存缓存（cachetools）
    - 插件代码无需修改，系统会自动处理缓存后端的切换

- 8. 最佳实践：
    - 为每个插件使用独立的缓存区域（region），避免缓存键冲突
    - 合理设置TTL，避免缓存过期时间过长导致数据过期
    - 对于频繁访问的数据使用较长的TTL，对于实时性要求高的数据使用较短的TTL
    - 使用`skip_none=True`避免缓存无意义的None值
    - 大文件或二进制数据建议使用文件缓存后端
    - 在插件卸载时清理相关缓存，避免内存泄漏

### 16. 如何在插件中注册智能体工具？
**（仅支持 `v2.8.0+` 版本）**
- MoviePilot的AI智能体功能支持通过插件扩展工具能力，插件可以注册自定义工具供智能体调用，实现更丰富的功能扩展。
- 1. 实现 `get_agent_tools()` 方法，返回工具类列表：
    ```python
    def get_agent_tools(self) -> List[Type]:
        """
        获取插件智能体工具
        返回工具类列表，每个工具类必须继承自 MoviePilotTool
        """
        return [MyCustomTool, AnotherTool]
    ```

- 2. 创建工具类，必须继承自 `MoviePilotTool` 并实现相关要求：
    ```python
    from typing import Optional, Type
    from pydantic import BaseModel, Field
    from app.agent.tools.base import MoviePilotTool
    from app.chain import ToolChain
    
    class MyToolInput(BaseModel):
        """工具输入参数模型"""
        explanation: str = Field(..., description="工具使用说明")
        query: str = Field(..., description="查询内容")
        limit: Optional[int] = Field(10, description="返回结果数量限制")
    
    class MyCustomTool(MoviePilotTool):
        """自定义工具示例"""
        # 工具名称，用于智能体识别和调用
        name: str = "my_custom_tool"
        
        # 工具描述，用于智能体理解工具功能，建议详细描述工具用途和使用场景
        description: str = "This tool is used to perform custom operations. Use it when you need to query or process specific data."
        
        # 输入参数模型，定义工具接收的参数及其类型和说明
        args_schema: Type[BaseModel] = MyToolInput

        def get_tool_message(self, **kwargs) -> Optional[str]:
          """根据订阅参数生成友好的提示消息"""
          pass
        
        async def run(self, query: str, limit: Optional[int] = None, **kwargs) -> str:
            """
            实现工具的核心逻辑（异步方法）
            :param query: 查询内容
            :param limit: 结果数量限制
            :param kwargs: 其他参数，包含 explanation（工具使用说明）
            :return: 工具执行结果，返回字符串格式
            """
            try:
                # 获取上下文信息（系统自动注入）
                session_id = self._session_id
                user_id = self._user_id
                channel = self._channel
                source = self._source
                username = self._username
                
                # 执行工具逻辑
                result = await self._perform_operation(query, limit)
                
                # 可以通过 send_tool_message 发送消息给用户
                await self.send_tool_message(f"操作完成: {result}", title="工具执行")
                
                # 返回执行结果
                return f"成功处理查询 '{query}'，返回 {len(result)} 条结果"
            except Exception as e:
                return f"执行失败: {str(e)}"
        
        async def _perform_operation(self, query: str, limit: int):
            """内部方法，执行具体操作"""
            # 实现具体业务逻辑
            pass
    ```

- 3. 工具类可用的上下文属性和方法：
    - `self._session_id`: 当前会话ID
    - `self._user_id`: 用户ID
    - `self._channel`: 消息渠道（如 Telegram、Slack 等）
    - `self._source`: 消息来源
    - `self._username`: 用户名
    - `self.send_tool_message(message: str, title: str = "")`: 发送消息给用户
    - `ToolChain()`: 访问处理链功能，可调用系统其他功能

- 4. 工具类实现要求：
    - **必须继承自 `app.agent.tools.base.MoviePilotTool`**
    - **必须实现 `run` 方法**（异步方法），接收参数并返回字符串结果
    - **必须实现 `get_tool_message` 方法**，以显示友好的工具执行提示给用户
    - **必须定义 `name` 属性**（字符串），工具的唯一标识
    - **必须定义 `description` 属性**（字符串），详细描述工具功能，帮助智能体理解何时使用该工具
    - **可选定义 `args_schema` 属性**（Pydantic模型类），用于定义输入参数的结构和验证

- 5. 注意事项：
    - 工具的描述（`description`）应该清晰明确，帮助智能体理解工具的功能和使用场景
    - 工具的参数模型（`args_schema`）应该包含详细的字段描述，帮助智能体正确构造参数
    - 工具执行结果应该返回有意义的字符串，便于智能体理解和向用户展示
    - 工具可以通过 `send_tool_message` 方法向用户发送实时消息，提升交互体验
    - 工具类在初始化时会自动注入会话和用户信息，可以通过私有属性访问
    - 如果工具需要访问插件实例，需要自行通过 `PluginManager` 获取
    - 工具执行时间应该尽量短，避免阻塞智能体的响应
    - 建议在工具执行过程中添加适当的错误处理和日志记录


## 版本发布

### 1. 如何发布插件版本？
- 修改插件代码后，需要修改`package.json`中的`version`版本号，MoviePilot才会提示用户有更新，注意版本号需要与`__init__.py`文件中的`plugin_version`保持一致。
- `package.json`中的`level`用于定义插件用户可见权限，`1`为所有用户可见，`2`为仅认证用户可见，`3`为需要密钥才可见（一般用于测试）。如果插件功能需要使用到站点则应该为2，否则即使插件对用户可见但因为用户未认证相关功能也无法正常使用。
- `package.json`中的`history`用于记录插件更新日志，格式如下：
```json
{
  "history": {
    "v1.8": "修复空目录删除逻辑",
    "v1.7": "增加定时清理空目录功能"
  }
}
```
- 新增加的插件请配置在`package.json`中的末尾，这样可被识别为最新增加，可用于用户排序。
- 默认通过遍历下载项目文件的方式安装插件，如果插件文件较多，可以使用release的方式发布插件，package对应的插件描述中增加`release`字段并设置为`true`，此时插件安装时会直接下载tag为`插件ID_v插件版本号`的release包，release打包脚本参照插件仓库中的`release.yml`脚本。
```json
{
  "release": true
}
```

### 2. 如何开发V2版本的插件以及实现插件多版本兼容？

- 请参阅 [V2版本插件开发指南](./docs/V2_Plugin_Development.md)
