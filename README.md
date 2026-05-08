# MoviePilot 115sub 订阅联动

这是一个 MoviePilot v2 插件仓库，用于把 MoviePilot 的订阅、下载和整理事件实时推送给 115sub，并接收 115sub 的占位/完成态回写。

## 目录结构

- `package.v2.json`
- `plugins.v2/plugin115sub/__init__.py`
- `plugins.v2/plugin115sub/requirements.txt`

## 安装

1. 将这个仓库推到 GitHub。
2. 在 MoviePilot 的插件市场里把你的仓库地址加入 `PLUGIN_MARKET`。
3. 刷新插件市场，安装 `115sub`。
4. 在插件配置里填写 `115sub 地址`。
5. 在 115sub 设置页开启 MoviePilot 联动，并填写 MoviePilot 的 `API_TOKEN`。

插件会直接复用 MoviePilot 自身的 `API_TOKEN` 与 115sub 对接，不需要额外维护 Webhook Secret。

## 说明

- `subscribe.added / subscribe.modified / subscribe.deleted`
- `download.added / download.deleted`
- `transfer.complete`
- `resource.download` 下载前拦截：如果 115sub 已占位或 Emby 已确认入库，MoviePilot 会跳过该集下载。

这些事件都会被转发到 115sub 的联动接口。

115sub 也会在转存成功后向插件写入 `processing`，并在 Emby 影子库确认入库后写入 `completed`。

插件不再声明空详情页，MoviePilot 插件列表点击会直接走配置入口。
