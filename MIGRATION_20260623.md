# API 模块化与 LCU 移除说明

本文件保留第一阶段迁移说明。下一阶段彻底拆分工作在独立分支进行，不直接影响当前 master 可用版本。

当前 master 已完成：

- `app.py` 作为轻入口运行。
- `legacy_app.py` 暂时承载旧跨区、合集、海符榜逻辑。
- `routers/lolban.py` 已承载封号查询。
- `/query` 与 `/hidden_query` 已移除。
- `collector.py` 与 `lcu_client.py` 已变为废弃兼容桩。

下一阶段目标：

- 删除 `legacy_app.py`。
- 将 `/health`、`/cross_query`、`/cross_session_init`、`/shard_query`、`/aram_augments`、`/lolban` 分别拆入 router/service/renderer 模块。
- 保持端口、启动方式、URL、参数和返回格式不变。
