# WEBUI-CONTROL-PANEL-003 P3B 基线感知 readiness 交接

更新时间：2026-08-06 02:43 +08:00

## 当前断点

P3B 新 V3 目标已经在 Windows 生产机部署成功，验证报告为完整 `pass`。代码、打包和生产切换均无阻塞，当前进入五个 P3B 页面与实际操作验收。

继续任务时先读取：

1. `docs/HANDOFF_LATEST.md`
2. 本文档
3. `docs/HANDOFF_WEBUI_CONTROL_PANEL_003_P3B_20260805.md`

## 当前生产

- 仓库：`xianyumht-cmd/lolapisevers`
- Issue：#40，保持打开
- Draft PR：#41，保持 Draft
- 功能分支：`feat/webui-control-panel-003-20260805`
- 当前生产：`7524a5ea36b53a4186a1934edb69b691af56ac09`
- 服务：`LOLDataSystem`
- 生产验证：`pass`
- `degraded=false`
- `inherited_so1_session_degradation=false`

备份目录：

- `D:\project2\lolapisevers.deploy-backups\20260806-023757-full-bug-repair-7524a5ea36b5`

## P3B 页面

- `/main-config`
- `/lanzou/config`
- `/lanzou/watchers`
- `/lanzou/targets`
- `/api-debugger`

对应旧 `?tab=` 地址保留 307 兼容重定向。共享控制台 Shell、Secret 脱敏、Watcher 密码掩码往返、通知 Header 掩码往返、本机回环或 `WEBUI_ADMIN_TOKEN` 保护均已实现。

## Windows 部署记录

部署目标：

- `7524a5ea36b53a4186a1934edb69b691af56ac09`

部署时间：

- 候选目录时间戳：`20260806-023757`
- verification generated_at：`2026-08-05T18:39:20.1378100Z`

部署过程：

- release.bundle 验证：PASS
- Python 3.14 离线依赖安装：PASS
- 无破损依赖：PASS
- 343 项候选测试：PASS
- WebUI JavaScript：PASS
- 停服前健康基线：PASS
- 生产源码切换：PASS
- build-info 写入：PASS
- 服务启动：PASS
- 后置生产验证：PASS
- 自动回滚：未触发

验证报告：

- `status=pass`
- Windows 服务：Running
- `/livez`：HTTP 200
- MySQL：up
- SO1 Chromium：up
- SO1 session：authenticated
- `/readyz`：HTTP 200
- build-info：目标提交
- Git HEAD：目标提交
- shard：`kind=segments`
- ARAM：`kind=segments`
- observability 检查：pass，detail 为 `status=degraded`

`observability status=degraded` 是业务观测摘要，验证器已确认它不构成本次部署失败条件；服务、必需依赖、Git、构建信息和两条正式交付链路均通过。

## 停服前基线说明

`pre-switch-health.json` 记录的是切换前旧生产：

- commit：`7d637b90ac2b177de86bae024713ac9172bb26fa`
- `ready=true`
- MySQL：up
- SO1 Chromium：up
- SO1 session：authenticated

因此本次部署没有使用 inherited degradation 例外；新生产直接以完整健康状态通过。

## SO1 readiness 修复结论

此前目标 `292b43ef...` 因原始 `reason|error_class` 文字漂移误回滚。最终版本保留以下规则：

- 浏览器在线、会话不可用时使用稳定状态指纹
- 原始失败原因保留在报告 detail
- 部署前已认证、部署后失效仍强制回滚
- MySQL、Chromium、服务、Git、build-info 和正式链路回归仍强制回滚

本次实际部署时 SO1 session 已恢复 authenticated，所以归一化 warning 路径没有被使用。

## 下一步验收

1. Ctrl + F5 刷新 6178 页面。
2. 提交五个独立页面截图。
3. 验收旧 `?tab=` 地址 307 跳转。
4. 主接口页：读取、修改、保存、备份、重启提示。
5. 蓝奏全局配置：环境覆盖状态、保存和热刷新。
6. Watcher：新增、编辑、启停、删除、扫描和密码保留。
7. 通知目标：Header 脱敏、保留、启停、删除和测试推送。
8. 接口调试器：Path、Query、Header、JSON Body 和响应显示。
9. 页面操作验收通过后标记 P3B 完成。
10. 再进入旧运行面板、旧导航注入和 `/legacy-ui` 退休审查。
11. 整体迁移完成前不合并 PR #41，不关闭 Issue #40。

## 禁止再次部署

- `f9e00b505dc549f3d761348dc741535f4294e352`
- `954f7748d41da9c3264441d33d60b7c9273fd946`
- `292b43ef439b6102fd34b3c7b198cc7671b65eab`
