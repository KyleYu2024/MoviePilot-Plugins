# MoviePilot 115sub 订阅联动

这是一个 MoviePilot v2 插件仓库，用于把 MoviePilot 的订阅、下载和整理事件实时推送给 115sub。

## 目录结构

- `package.v2.json`
- `plugins.v2/plugin115sublinkage/__init__.py`
- `plugins.v2/plugin115sublinkage/requirements.txt`

## 安装

1. 将这个仓库推到 GitHub。
2. 在 MoviePilot 的插件市场里把你的仓库地址加入 `PLUGIN_MARKET`。
3. 刷新插件市场，安装 `115sub 订阅联动`。
4. 在插件配置里填写：
   - `115sub 地址`
   - `Webhook Secret`
5. 在 115sub 设置页开启 MoviePilot 联动，并保存 secret。

## 说明

- `subscribe.added / subscribe.modified / subscribe.deleted`
- `download.added / download.deleted`
- `transfer.complete`

这些事件都会被转发到 115sub 的联动接口。
