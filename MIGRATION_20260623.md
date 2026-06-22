# API 模块化与 LCU 移除说明

本分支 `full-api-split-exec` 已完成完整模块化拆分，目标是让 `app.py` 不再负重，并彻底移除旧 LCU 本地客户端查询链路。

## 已完成

- `app.py` 已变为纯入口：创建 FastAPI、初始化上下文、挂载 routers、启动服务。
- 已移除 `app.py` 对 `legacy_app.py` 的依赖。
- 已删除 `legacy_app.py`。
- 已删除废弃 LCU 文件：`collector.py`、`lcu_client.py`。
- 已保留端口、启动方式、URL、参数和返回格式。

## 当前接口

- `GET /health`
- `POST /cross_session_init?wait_seconds=180`
- `GET /cross_query?name={name}&region={region}&output=pretty|raw|image|svg`
- `GET /shard_query?hero={hero}&output=image|json`
- `GET /aram_augments?hero={hero}&output=image|json`
- `GET /api/v2/lolban?qq={qq}`
- `GET /lolban?qq={qq}`

## 已废弃且不恢复

- `GET /query`
- `GET /hidden_query`

## 新目录职责

- `core/`：配置、运行上下文、生命周期。
- `routers/`：HTTP 路由、参数校验、响应分发。
- `services/`：业务逻辑、上游请求、数据清洗、缓存、快照。
- `renderers/`：PNG/SVG 图片渲染。
- `utils/`：通用转换、时间、文本、HTTP、格式化工具。
