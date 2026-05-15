# MoviePilot 115sub 订阅联动

这是一个 MoviePilot v2 插件仓库，用于把 MoviePilot 的订阅、下载和整理事件实时推送给 115sub，并接收 115sub 的占位/完成态回写。


## 说明

- `subscribe.added / subscribe.modified / subscribe.deleted`
- `download.added / download.deleted`
- `transfer.complete`
- `resource.download` 下载前拦截：如果 115sub 已占位或 Emby 已确认入库，MoviePilot 会跳过该集下载。

这些事件都会被转发到 115sub 的联动接口。

115sub 也会在转存成功后向插件写入 `processing`，并在 Emby 影子库确认入库后写入 `completed`。
