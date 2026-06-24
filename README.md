# MoviePilot 联动插件

这是一个 MoviePilot v2 插件仓库。

## FlowLink 上传联动

`PluginFlowLink` 用于在 MoviePilot 整理完成后，把本次新增文件精准通知给 FlowLink 上传。

核心配置：

- FlowLink 地址：例如 `http://flowlink:6118`。
- FlowLink API Token：对应 FlowLink 设置里的 `security.api_token`。
- FlowLink 上传任务名：可留空，由 FlowLink 按文件路径匹配启用的上传任务。
- MoviePilot 整理后目录：只通知这些目录下的文件。
- 路径映射：每行一个前缀映射，例如 `/media=/data/media`，用于把 MoviePilot 看到的路径转换成 FlowLink 容器可访问的路径。

精准通知依赖 FlowLink 的 `POST /api/transfer/upload/files` 接口。旧版 FlowLink 只有 `/api/transfer/upload/scan` 时，只能回退为上传任务目录扫描。

## 115sub 订阅联动

`Plugin115Sub` 用于把 MoviePilot 的订阅、下载和整理事件实时推送给 115sub，并接收 115sub 的占位/完成态回写。


## 说明

- `subscribe.added / subscribe.modified / subscribe.deleted`
- `download.added / download.deleted`
- `transfer.complete`
- `resource.download` 下载前拦截：如果 115sub 已占位或 Emby 已确认入库，MoviePilot 会跳过该集下载。

这些事件都会被转发到 115sub 的联动接口。

115sub 也会在转存成功后向插件写入 `processing`，并在 Emby 影子库确认入库后写入 `completed`。
