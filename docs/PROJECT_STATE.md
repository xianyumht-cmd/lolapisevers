# Project state

更新时间：2026-08-25 +08:00

## Canonical development

- 默认开发分支：`master`；GitHub 实际 `master` 提交是开发状态最终依据。
- 生产目录 `D:\project2\lolapisevers` 在普通开发中保持只读；仓库改动、CI 和本地引导包不等于生产已部署。
- PR #80 建立 Release 多镜像测速、断点续传与实时进度。
- Issue #81 / PR #82 建立后台 worker、低速熔断、暂停/继续/重连/重下与服务重启 PID 验证。
- Issue #83 / PR #84 完成 OP.GG 海符榜百分比规范化和部署终态跟踪。
- Issue #85 / PR #87 完成 Release freshness、GitHub Compare 前向升级守卫与禁止降级。
- Issue #88 / PR #89 将 Release 部署 helper 的生命周期交给 Windows Task Scheduler / SYSTEM。
- Issue #90 / PR #91 强化 Task Scheduler 的 PID/started/exitcode 持久化证据与服务重启后的部署状态恢复；`master` 合并提交为 `57050d1d8d7ca52c63d073805bbb964c014515e4`。
- 当前开发任务：Issue #92，扩充中国区 Release 加速源，并为私有 Release 增加 GitHub 官方签名 CDN 并发 Range 下载。

## 已验证生产状态

- 2026-08-25 用户已通过 PR90 本地 V3 引导包把生产升级到 `252cc8342391d11ac1bd9c0c4ae46f072fca25b3`。
- WebUI 正确发现最新 Release `57050d1d8d7ca52c63d073805bbb964c014515e4`，状态为可安全前向升级。
- 实际下载时现有公共代理 `gh-proxy.com`、`ghproxy.net`、`ghfast.top`、`gh.ddlc.top` 均测速失败；回退 `github-api` 后下载速度约 `15.6 KB/s` / `0.02 MB/s`，因此 Issue #92 处理下载吞吐问题。

## Release 更新安全边界

- GitHub Release Token 只发送到 GitHub 官方 API；第三方公共镜像永不携带 Token。
- 私有仓库的公共 GitHub 代理通常无法直接读取私有 Release，这类镜像只是无凭据的 best-effort 候选，不能作为唯一提速方案。
- Release metadata 继续通过 GitHub 官方认证链获取；最终 ZIP 必须通过 metadata SHA-256、路径安全检查、V3 manifest 安全标志与 target commit 校验。
- GitHub Compare 只有 `current...target = ahead` 才允许自动前向升级；`behind`、`diverged` 或关系未知均 fail-closed。
- 部署继续由 Task Scheduler / SYSTEM 托管，并由 V3 deployer 执行候选测试、备份、基线健康检查、生产切换、后置验证和失败回滚。

## Issue #92 设计

- 扩充中国区常用 GitHub 文件代理候选；每次升级仍并行测速并自动按可用性/延迟排序，不假定某个公益镜像永久可用。
- 第三方镜像请求只使用公开下载头，不发送 GitHub Token，也不把任何私有凭据写入镜像 URL。
- 对私有 Release，先向 GitHub 官方 asset API 发送认证请求并只读取 30x `Location`，得到 GitHub 官方 `release-assets.githubusercontent.com` / `objects.githubusercontent.com` 临时签名直链；该签名 URL 只在本机内存中使用，不写日志，不经过第三方代理。
- 官方签名 CDN 候选默认最多 6 路 Range 并发（`LOLAPI_UPDATE_CDN_CONNECTIONS` 可调，范围 2~8），支持从现有连续 `.part` 前缀继续下载；分片完成后按顺序拼接并仍由最终 SHA-256 做完整性裁决。
- 若 CDN 不支持 Range、分片失败或网络异常，自动回退同一官方 URL 的单连接断点续传，再按既有候选链继续故障切换。
- 暂停、重新连接、重置事件在并发下载期间仍被检测；暂停时只提交可证明连续的前缀到 `.part`，不会把乱序分片冒充有效断点。

## 下一步

1. Issue #92 在临时分支完成实现与回归测试。
2. tests、Parser Center CI、普通安全包、V3 安全部署包全部通过后合并。
3. 生成一次性 V3 本地过渡包，让当前 `252cc834...` 生产直接获得新下载器。
4. 生产再次从 WebUI 发起一键升级，观察镜像测速、`github-cdn-Nx` 吞吐、断点恢复和最终 Task Scheduler 部署闭环。
