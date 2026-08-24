# 生产提交谱系桥接交接（2026-08-24）

## 背景

Windows 生产目录当前 HEAD 为：

`438d2c2c2400de623a43e9a58436d46fc7037e4d`

而海符榜富信息 + WebUI Release 一键升级首次 V3 包目标为：

`826d72c5a93190054c4ae4391b1f3f804a40d22c`

二者在 Git 历史上已经分叉，因此 V3 部署器按设计拒绝切换，并明确输出：

`Current production commit is not an ancestor of the package target.`

生产服务未停止、生产源码未修改。

## 处理

创建谱系桥接提交：

`9bc0beac34b025a6d73aae569b5f71e5d16f8769`

该提交以生产 HEAD `438d2c2...` 为第一父提交，以当时 `master` `62ab9f9...` 为第二父提交，文件树与 `62ab9f9...` 完全一致。

这样新的部署目标同时满足：

- 当前生产 `438d2c2...` 是新目标的祖先；
- 当前 `master` `62ab9f9...` 也是新目标的祖先；
- 代码内容不退回生产分叉上的旧实现；
- 后续 `master` 重新回到包含生产谱系的单一路径，避免同类 V3 ancestry gate 再次拒绝正常升级。

## 部署原则

- 不使用 `--force` 绕过 V3 ancestry gate。
- 不手工 `git reset --hard` 生产目录。
- 不删除生产目录中的未跟踪运行态配置和 diagnostics。
- 只使用基于桥接后提交重新构建并通过 CI 的 V3 不可变部署包。

## 当前生产现场

生产检查时还存在以下未跟踪运行态文件：

- `config/dynamic-query-providers.json`
- `config/interface-parser-center.json.bak.*`
- `diagnostics/`

它们不是此次 ancestry 失败的原因，部署时继续按现有 V3 运行态保护规则处理。
