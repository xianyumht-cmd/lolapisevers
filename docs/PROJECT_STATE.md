# Project state

更新时间：2026-08-27 +08:00

## Canonical development

- 默认开发分支：`master`；GitHub 实际 `master` 提交是开发状态最终依据。
- 生产目录 `D:\project2\lolapisevers` 在普通开发中保持只读；仓库改动、CI 和本地引导包不等于生产已部署。
- PR #80 建立 Release 多镜像测速、断点续传与实时进度。
- Issue #81 / PR #82 建立后台 worker、低速熔断、暂停/继续/重连/重下与服务重启 PID 验证。
- Issue #83 / PR #84 完成 OP.GG 海符榜百分比规范化和部署终态跟踪。
- Issue #85 / PR #87 完成 Release freshness、GitHub Compare 前向升级守卫与禁止降级。
- Issue #88 / PR #89 将 Release 部署 helper 的生命周期交给 Windows Task Scheduler / SYSTEM。
- Issue #90 / PR #91 强化 Task Scheduler 的 PID/started/exitcode 持久化证据与服务重启后的部署状态恢复。
- Issue #92 / PR #93 已完成中国区 Release 加速源扩充、GitHub 官方签名 CDN 与并发 Range 下载。
- 本轮任务开始时 `master` 为 `2135a13a23b96fe2455d3a53311b35bd93dd22da`。
- 当前开发任务：Issue #94 / PR #95，降低查询图片生成延迟，同时保持业务数据的新鲜度边界不变。

## 查询图片延迟 P0

- 战绩、段位、海符统计等业务数据仍走既有第三方 upstream / snapshot 策略；图片优化不把实时业务数据替换成长 TTL 结果。
- 图片素材 CDN 从正常用户查询关键路径移除：本地已有素材直接使用，本地缺失时立即使用占位继续渲染，并由进程内小型后台线程池补资源。
- 后台图片下载按 URL single-flight，失败有短冷却；后台失败不写入长时间 negative cache，避免临时 CDN 故障长期隐藏素材。
- 显式设置 `IMAGE_ASSET_BLOCKING_FETCH_ENABLED=1` 才恢复同步图片下载，定位为维护/诊断逃生开关，不是生产默认路径。
- 字体加载改为进程内 LRU；`fit_text` 从逐字符回退改为二分测量。
- PNG 在线编码从 `optimize=True + compress_level=9 + 多轮 palette/resize` 改为低延迟压缩等级和更少编码轮次，同时继续执行最大尺寸与最大字节硬上限。
- 战绩 PNG 增加 120 秒服务端最终图缓存，key 绑定所有可见业务字段、renderer version 和 footer；业务数据一变即 miss。
- 如果本次战绩图仍有缺失素材，响应标记 `X-Image-Cache: warming` / `X-Image-Assets: warming`，该占位版本不写最终图缓存；资源补齐后的下一次查询会重新渲染完整版本。
- HTTP 仍保持 `Cache-Control: no-store`，服务端最终图缓存只用于减少重复 Pillow/PNG 工作。

## Release 更新安全边界

- GitHub Release Token 只发送到 GitHub 官方 API；第三方公共镜像永不携带 Token。
- Release metadata 继续通过 GitHub 官方认证链获取；最终 ZIP 必须通过 metadata SHA-256、路径安全检查、V3 manifest 安全标志与 target commit 校验。
- GitHub Compare 只有 `current...target = ahead` 才允许自动前向升级；`behind`、`diverged` 或关系未知均 fail-closed。
- 部署继续由 Task Scheduler / SYSTEM 托管，并由 V3 deployer 执行候选测试、备份、基线健康检查、生产切换、后置验证和失败回滚。
- 生产升级继续以经过 CI/V3 打包并发布到 GitHub Release 的 `master` 为输入；用户从 6178 WebUI 点击一键升级，不在普通开发阶段直接覆盖生产目录。

## 当前完成门

1. PR #95 的单元/集成 tests、Parser Center CI、普通安全包、V3 安全部署包全部通过。
2. 检查 PR diff，确认业务 upstream 路径、图片 fallback、PNG byte ceiling 和 Release 部署边界没有回归。
3. 合并 PR #95 到 `master`，确认 `master` 包含结果并删除临时分支。
4. 确认 master push 的 V3 Release 工作流完成并发布新的 verified Release。
5. 关闭 Issue #94；之后生产机器只需要从 WebUI 发起一键升级。
