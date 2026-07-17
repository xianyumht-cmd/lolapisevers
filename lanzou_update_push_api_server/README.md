# Lanzou Update Push API Server

本项目是一个 Windows/Linux 双端可运行的本地蓝奏云更新监听服务。

它会先读取每个蓝奏云分享链接的文件列表作为基线，之后按配置间隔扫描。发现新增、删除或文件信息变化时，会记录事件，并向配置的 localhost 回调地址主动 POST：

```text
hello，{title}网盘检测到更新
```

## 配置

复制示例配置：

```powershell
Copy-Item .\lanzou_update_push_api_server\config.example.json .\lanzou_update_push_api_server\config.json
```

常用字段：

- `host` / `port`：本地接口监听地址和端口，默认 `127.0.0.1:6178`。
- `scan_interval_seconds`：定期扫描间隔，单位秒。
- `scan_batch_size` / `scan_batch_pause_seconds`：定时巡检的分批扫描设置，用来避免一次性请求全部链接。
- `scan_on_start`：启动后是否立刻扫描一次。
- `watchers`：要监控的蓝奏云分享链接列表，想监控多少个就在这里放多少个。
- `notify_targets`：文件变化后主动 POST 的 localhost 回调目标。
- `notification_template`：推送文案模板，支持 `{title}`、`{name}`、`{watcher_id}`、`{url}`。
- `provider_order`：文件列表获取顺序，默认先直读蓝奏页面，再尝试镜芯 API。
- `wer_api_endpoint`：镜芯接口地址，默认使用优享版 `https://api2.wer.plus/api/lanzpro`。

第三方镜芯 API key 不建议写入 Git。需要使用时设置环境变量：

```powershell
$env:LANZOU_API_KEY="你的 key"
```

Linux:

```bash
export LANZOU_API_KEY="你的 key"
```

## 启动

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_lanzou_monitor_windows.ps1
```

Linux:

```bash
bash ./scripts/run_lanzou_monitor_linux.sh
```

或直接运行：

```bash
python -m lanzou_update_push_api_server
```

默认地址：

```text
http://127.0.0.1:6178
```

## 本地接口

- `GET /health`：运行状态。
- `GET /watchers`：监控列表和最近快照。
- `GET /events`：最近更新事件。
- `POST /scan`：立即扫描全部网盘。
- `POST /scan?watcher_id=s17`：立即扫描指定网盘。
- `POST /notify/test`：发送测试通知到配置的回调目标。

如果监控链接很多，日常建议依靠定时巡检的 `scan_batch_size` 和 `scan_batch_pause_seconds` 分散扫描；手动测试时优先使用 `POST /scan?watcher_id=某个ID`。

变化事件的回调体是 JSON，核心字段包括：

- `type`：`lanzou_update` 或 `lanzou_update_test`。
- `message`：按 `notification_template` 渲染后的通知文案。
- `watcher_id` / `title` / `url`：对应监控项信息。
- `diff.added` / `diff.removed` / `diff.changed`：新增、删除、信息变化的文件。
- `files`：当前文件列表快照。

## SnowLuma 对接

1. 启动 SnowLuma WebUI，打开 `http://192.168.3.89:6108/lanzou-update.html?token=你的WebUIToken`。
2. 开启蓝奏更新推送，配置目标群或私聊账号。
3. 在本服务的 `notify_targets` 中配置：

```json
{
  "name": "snowluma",
  "enabled": true,
  "url": "http://192.168.3.89:6108/api/lanzou-update/event?token=你的WebUIToken",
  "headers": {
    "x-groupguard-token": "可选WebUIToken"
  }
}
```

## 说明

服务默认优先直接读取蓝奏分享页的文件列表；如果配置了 `LANZOU_API_KEY`，也可按 `provider_order` 尝试镜芯 API。

镜芯 API 文档入口：

- 普通版：https://api2.wer.plus/doc/19
- 优享版：https://api2.wer.plus/doc/41
