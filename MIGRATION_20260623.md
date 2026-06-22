# API 模块化与 LCU 移除说明

本次调整目标：保持 `app.py` 作为正式启动入口，继续监听 `5001`，同时把新增封号查询放入独立 router，并从运行链路中移除废弃的本地 LCU 查询能力。

## 已完成

- `app.py` 改为轻入口，继续由 `python app.py` 启动。
- 原大型入口保留为 `legacy_app.py`，用于继续承载当前稳定的跨区战绩、合集、海符榜和会话初始化逻辑。
- 新增 `routers/lolban.py`：
  - `GET /api/v2/lolban?qq={qq}` 默认返回纯文本。
  - `GET /api/v2/lolban?qq={qq}&output=json` 返回清洗后的 JSON。
  - 非 5-11 位数字 QQ 会在本地拦截，不请求上游。
  - 只允许输出“正常 / 封禁 / 接口繁忙 / QQ格式错误”这类固定模板。
  - 上游未知提示、广告、官网、联系方式等内容不会原样发给机器人。
- `/query` 与 `/hidden_query` 已从当前 FastAPI 路由表移除。
- `lcu_client.py` 与 `collector.py` 已替换为兼容桩，避免继续维护本地客户端查询链路。
- `requirements.txt` 已移除不再需要的 `psutil`。

## 当前保留接口

```text
GET  /health
GET  /cross_query?name={name}&region={region}&output=pretty
POST /cross_session_init?wait_seconds=180
GET  /shard_query?hero={hero}&output=image
GET  /aram_augments?hero={hero}&output=image
GET  /api/v2/lolban?qq={qq}
GET  /lolban?qq={qq}
```

## 已移除接口

```text
GET /query
GET /hidden_query
```

## 本地重启

```powershell
cd /d D:\project2\lolapisevers
git fetch origin
git checkout api-modules-work
.\.venv\Scripts\python.exe -m compileall app.py routers legacy_app.py so1_client.py db.py
Restart-Service LOLDataSystem
```

## 验证命令

```powershell
curl http://127.0.0.1:5001/health
curl "http://127.0.0.1:5001/api/v2/lolban?qq=447677756"
curl "http://127.0.0.1:5001/api/v2/lolban?qq=447677756&output=json"
curl "http://127.0.0.1:5001/cross_query?name=如初见vzk%2342675&region=艾欧尼亚"
```
