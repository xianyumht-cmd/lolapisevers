# LOLDataSystem 定向文件推送接口端交接 — 2026-08-08

更新时间：2026-08-08 04:36 +08:00  
仓库：`xianyumht-cmd/lolapisevers`  
接口端功能分支：`feat/target-file-push-20260807`  
接口端 PR：`#57`（Draft，未合并）  
6178 运维页分支：`feat/target-file-watch-webui-20260808`  
6178 PR：`#58`（Draft，未合并）

## 当前暂停点

定向文件推送的 5001 ↔ 6108 内部通信、配置同步、首次 baseline 建立已经成功；现在卡在“检测到新增文件后，为该具体文件取得可下载直链”这一步。

当前不要重新部署 5001/6178/6108，也不要重新建立 baseline。下一聊天直接从“把定向文件直链解析链从旧蓝奏监控 Provider 语义中独立出来”开始修。

## 已确认运行状态

### GroupGuard 6108

- 接口端在线。
- 接口监控运行中。
- 接口端当前配置：已启用，检查间隔 300 秒。
- 本地临时目录：`/app/data/target-file-push-temp`。
- 当前目录基线：1 个历史文件。
- 当前出现 1 个待推送文件：`U13LKcQg2.7z`。
- 本地已完成事件：0。
- 最近群文件上传成功：暂无。
- 最近错误：`未取得可下载直链；请确认现有蓝奏直链 Provider/API Key 配置可用`。

### LOLDataSystem 6178 / 5001

此前已确认：

- 功能状态：已启用。
- 后台循环：运行中。
- baseline 已建立成功。
- baseline 建立时没有上传历史文件，符合业务规则。
- 当前 baseline Provider 曾显示 `lanzou_web`。
- GroupGuard 回调 Token 已配置。
- 6108 保存并同步到 5001 已成功。
- 5001 与 6108 的网络和内部鉴权链路已打通。

当前接口端日志错误：

```text
最近错误
未取得可下载直链；请确认现有蓝奏直链 Provider/API Key 配置可用
2026/8/8 04:28:53
```

## 已排除的问题

本轮问题不是：

- 6108 无法访问 5001；
- 5001 与 6108 的接口写 Token 不匹配；
- baseline 没建立；
- 定向监控没启用；
- GroupGuard 回调地址没配置。

前面曾遇到 `管理员凭据无效`，根因是把第三方 WER Token 和 5001 内部写入 Token 混淆。已通过只读 Token Finder 找回/验证正确的 5001 内部 Token，并完成 6108 → 5001 配置同步。真实 Token 不得写入文档或聊天。

## 当前确认的代码问题

定向文件推送业务状态本身已经独立，没有接入旧 `lanzou_update_push_api_server` 的 watcher/event/state 业务层；但解析层仍直接复用了旧蓝奏监控的：

```text
load_lanzou_provider_config()
ProviderChain
WerApiProvider
```

当前 `services/target_file_watch_directory.py` 的逻辑：

1. `resolve_snapshot(source_url)` 使用 `ProviderChain(...).fetch(watcher)` 读取整个蓝奏目录；
2. 这一步能成功，说明目录枚举和 baseline 没问题；
3. 检测到新增文件后，`resolve_for_delivery()` 再次创建 `watcher = self._watcher(source_url)`；
4. 然后直接调用 `WerApiProvider().fetch(watcher, provider_config)`；
5. 此时传给 WER 的 `watcher.url` 仍是整个目录 URL，而不是新增文件自身的 `share_link`；
6. 接着再试图从 WER 返回结果中按 `canonical_file_key()` 唯一匹配目标文件；
7. 当前生产实测在这里拿不到 direct URL，最终抛出：

```text
未取得可下载直链；请确认现有蓝奏直链 Provider/API Key 配置可用
```

因此当前错误提示并不能证明 WER API Key 有问题；从代码和现场状态看，更大的问题是“目录解析”和“单文件直链解析”复用了同一套旧 Provider 语义。

## 已达成的修复方向

不要继续围绕现有 Provider 顺序或 WER Token 反复试配置。

把定向文件推送的解析链真正独立出来，但底层通用能力可以复用。

推荐拆成两个职责：

### 1. TargetFileDirectoryResolver

只负责：

```text
指定蓝奏目录 URL
-> 列出当前目录文件
-> 生成稳定 key / canonical fingerprint / provider fingerprint
-> 与 baseline 比较
```

目录枚举可以继续复用经过验证的底层 Lanzou Web 抓取能力，但不要直接继承旧蓝奏监控的 watcher/event/state 业务行为。

### 2. TargetFileDirectResolver

只负责：

```text
一个已经确定的具体文件 share_link
-> 解析为可下载 direct_url
```

正确投递链应改成：

```text
目录 URL
-> 读取目录
-> 对比 baseline
-> 找到新增/替换文件
-> 取得该文件自己的 share_link
-> TargetFileDirectResolver 解析这个单文件分享链接
-> 得到 direct_url
-> 5001 回调 6108
-> 6108 下载临时文件
-> 上传 QQ 原生群文件
```

不要再采用：

```text
整个目录 URL
-> WerApiProvider
-> 再从 WER 返回目录结果里找目标文件
```

## 配置隔离建议

建议新增定向文件解析自己的配置对象，例如：

```text
TargetFileWatchProviderConfig
```

代码层不要再直接依赖旧蓝奏监控完整 `AppConfig` / `ProviderChain`。

第三方 WER Key 可以默认继续读取现有：

```text
LANZOU_API_KEY
```

这样用户不需要维护两份相同 Secret，但定向文件业务的解析策略、超时、参数和未来 Provider 顺序应有独立边界。

如果后续需要独立环境变量，可考虑：

```text
TARGET_FILE_WATCH_WER_ENDPOINT
TARGET_FILE_WATCH_WER_KEY
```

但不要为了“代码独立”强迫用户现在立刻维护第二份真实 Token。

## 必须新增的回归测试

当前 `tests/test_target_file_watch_directory.py` 大部分使用 `FakeDirectoryResolver`，能证明 baseline、替换、删除、批量投递、失败不推进 baseline 等业务状态正确，但没有覆盖“真实目录条目的 share_link 被用于单文件直链解析”。

修复时至少新增：

1. 目录新增文件时，direct resolver 收到的是新增文件自身 `share_link`，不是 `source_url`；
2. 单文件直链解析成功后才调用 callback；
3. direct resolver 失败时 baseline 不推进，pending 保留；
4. 同名替换继续解析新版本的最新 `share_link`；
5. 删除-only 不调用 direct resolver；
6. 多新增文件逐个使用各自 `share_link`；
7. 旧蓝奏监控 Provider 顺序变化不能改变定向文件业务的独立解析策略；
8. 不把 source folder URL 误当成 direct URL；
9. Secret 不出现在日志、状态 JSON、6178 页面或测试快照中。

## 现场测试文件与 baseline 注意事项

当前测试已经进入“新增文件待投递”状态，6108 显示：

```text
待推送文件：1 个 · U13LKcQg2.7z
```

因此：

- 不要点“重新建立基线”；
- 不要为了修代码把这个新增文件吞进 baseline；
- 修好接口端并部署后，优先保留当前 baseline，再执行一次“立即检查”；
- 预期该 pending 新文件应继续走完整投递链；
- 如果状态兼容性无法保证，必须先备份 `target-file-watch-state.json` 再做显式迁移，不能静默重建 baseline。

## 仍然必须保持的业务规则

1. 首次启用/首次检查只建立 baseline，历史文件上传数量必须为 0。
2. 后续新增文件逐个上传。
3. 同名替换必须能识别并上传。
4. 仅删除上游文件时不向 QQ 投递。
5. callback 失败绝不推进 baseline。
6. 空上游快照不能覆盖正常非空 baseline。
7. Provider 切换不能制造误上传。
8. 新 QQ 群文件必须上传成功后，才能删除上一份目标群文件。
9. 旧群文件删除失败不能让新上传失败；进入 `pendingCleanup`。
10. 最终目标群只保留本规则最新一份文件。
11. 本地临时文件只有拿到成功上传的 `fileId` 后才删除。
12. `eventId` 必须持久化去重。

## 不要做

- 不要重部署已经正常工作的 GroupGuard 6108 页面和上传逻辑。
- 不要重做 6178 定向文件监控页面。
- 不要重新建立 baseline。
- 不要把 WER API Token 填到 GroupGuard 的“接口写入 Token”。
- 不要把 6178 做成第二套业务配置中心；6108 仍是业务配置权威源。
- 不要让旧蓝奏 watcher/event/state 接管本功能。
- 不要为了修 direct URL 破坏当前 pending/baseline 的 fail-safe 语义。
- 不要在日志/文档/PR 中写任何真实 Token。

## 下一聊天第一步

新聊天直接执行：

1. 读取本文件；
2. 读取 `services/target_file_watch_directory.py`；
3. 读取 `tests/test_target_file_watch_directory.py`；
4. 将“目录枚举”和“单文件 direct URL 解析”拆成独立职责；
5. 让 direct resolver 使用 `metadata.share_link` / 当前文件自己的 share link；
6. 补上述回归测试；
7. 先跑接口端专项测试，再跑完整 CI；
8. 生成接口端安全部署候选；
9. 部署后不要 rebaseline，直接对当前待投递文件执行一次检查；
10. 验证 5001 -> 6108 -> QQ 群文件完整链路。

## 当前相关代码

```text
services/target_file_watch_directory.py
services/target_file_watch_runtime.py
services/target_file_watch_service.py
routers/target_file_watch.py
tests/test_target_file_watch_directory.py
tests/test_target_file_watch_runtime.py
tests/test_target_file_watch.py
```

## 当前相关 PR

```text
lolapisevers #57  接口端定向文件监控/投递
lolapisevers #58  6178 定向文件监控运维页
groupguard-system #37  GroupGuard 6108 定向文件推送/QQ群文件上传
```
