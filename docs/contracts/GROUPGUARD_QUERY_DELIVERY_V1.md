# GroupGuard 查询最终下发协议 v1

## 协议目的

`groupguard-query-delivery.v1` 用于固定 `lolapisevers` 与 GroupGuard 之间的职责边界：

- GroupGuard 只提交查询功能、参数和自己支持的消息能力；
- `lolapisevers` 完成公网访问、业务解析、排序、绘图、缓存、快照、故障降级和最终消息选择；
- GroupGuard 只验证协议并按顺序发送 `delivery.segments`；
- GroupGuard 不读取 `rows`、`data`、`source_url`、英雄列表或任何第三方原始字段；
- 接口失败时，用户可见文字和是否重试均由接口端决定。

正式 JSON Schema：

```text
contracts/groupguard-query-delivery.v1.schema.json
```

## 入口

```http
POST /api/v1/groupguard/query
Content-Type: application/json
```

该入口是新增的兼容接口。以下旧接口保持不变：

```text
/shard_query
/aram_augments
/lolban
/api/v2/lolban
```

## 请求

```json
{
  "feature": "shard",
  "parameters": {
    "hero": "滑板鞋"
  },
  "preferred": "auto",
  "capabilities": {
    "text": true,
    "image": true,
    "forward": true
  },
  "request_id": "group-message-123"
}
```

### feature

当前支持：

- `shard`：查合集；
- `aram`：海符榜；
- `lolban`：查封号。

兼容别名只用于迁移期，插件正式实现必须发送以上三个稳定值。

### parameters

查合集和海符榜：

```json
{"hero": "阿狸"}
```

查封号：

```json
{"qq": "2621735529"}
```

### preferred

- `auto`：由接口根据功能和能力自动决定；
- `image`：优先图片，绘图失败时可回退文字或转发；
- `text`：优先普通文字；
- `forward`：优先合并转发。

`preferred` 是偏好，不是允许插件自行重构内容的授权。

### capabilities

插件声明自己实际可以下发的消息类型：

```json
{
  "text": true,
  "image": true,
  "forward": true
}
```

三项均未提供时默认视为支持。三项都为 `false` 时返回 HTTP 406。

## 成功响应

### 图片

```json
{
  "protocol": "groupguard-query-delivery.v1",
  "ok": true,
  "feature": "shard",
  "request_id": "服务端生成的ID",
  "client_request_id": "group-message-123",
  "delivery": {
    "kind": "segments",
    "segments": [
      {
        "type": "image",
        "mime_type": "image/png",
        "encoding": "base64",
        "data": "iVBORw0KGgo...",
        "filename": "shard-Kalista.png",
        "bytes": 123456,
        "sha256": "64位小写十六进制"
      }
    ]
  },
  "error": null,
  "retry": {
    "allowed": false,
    "after_seconds": 0
  },
  "meta": {
    "source": "live",
    "provider": "badspacebar",
    "stale": false,
    "snapshot_age_seconds": 0,
    "hero": {
      "alias": "Kalista",
      "name": "卡莉丝塔",
      "title": "复仇之矛"
    }
  }
}
```

插件处理图片时必须：

1. Base64 解码；
2. 可选校验 `bytes` 和 `sha256`；
3. 作为图片消息发送；
4. 不再次压缩、解析或绘图。

### 普通文字

```json
{
  "delivery": {
    "kind": "segments",
    "segments": [
      {
        "type": "text",
        "text": "接口端已经排版完成的最终文字"
      }
    ]
  }
}
```

插件必须原样发送，不得重新排序、补充第三方链接或拼接业务字段。

### 合并转发

```json
{
  "delivery": {
    "kind": "forward",
    "segments": [
      {
        "type": "forward",
        "nodes": [
          {
            "segments": [
              {
                "type": "text",
                "text": "第一段最终内容"
              }
            ]
          }
        ]
      }
    ]
  }
}
```

接口只提供节点内容。发送者 QQ 和显示名称由插件使用当前机器人身份填充，不得修改节点正文。

## 错误响应

错误同样带有可直接发送的 `delivery`：

```json
{
  "protocol": "groupguard-query-delivery.v1",
  "ok": false,
  "feature": "shard",
  "request_id": "服务端生成的ID",
  "client_request_id": "group-message-123",
  "delivery": {
    "kind": "segments",
    "segments": [
      {
        "type": "text",
        "text": "查询服务暂不可用，请稍后再试"
      }
    ]
  },
  "error": {
    "code": "temporarily_unavailable",
    "user_message": "查询服务暂不可用，请稍后再试",
    "retryable": true
  },
  "retry": {
    "allowed": true,
    "after_seconds": 30
  },
  "meta": {}
}
```

错误分类：

- `invalid_query`：参数错误，不应自动重试；
- `not_found`：目标不存在，不应自动重试；
- `temporarily_unavailable`：上游或服务暂不可用，可按建议时间重试；
- `request_failed`：其他不可重试错误。

插件不得把异常对象、HTTP 响应正文或底层 URL 发到群里。

## 接口端选择规则

### 查合集、海符榜

`preferred=auto` 时：

1. 插件支持图片：优先返回接口端生成的图片；
2. 图片生成失败：接口端改为最终文字；
3. 文字过长且插件支持合并转发：接口端返回转发节点；
4. 无可用下发能力：HTTP 406。

### 查封号

默认返回接口端排版的最终文字。插件不读取 `data.status`、封禁时间或剩余时间字段。

## 安全要求

响应不得包含：

- 公网上游完整 URL；
- Cookie、Token、密码或请求头；
- 第三方原始异常正文；
- 本地文件路径；
- 未经清洗的广告或联系方式；
- 为插件继续处理而暴露的完整业务数据集。

`meta` 只能用于日志、状态展示和故障定位，不能作为消息正文的二次数据源。

## 发布顺序

1. 服务端发布并保持旧接口兼容；
2. 在 Windows 内网电脑验证三类 delivery 请求；
3. 验证图片、文字、转发和错误响应；
4. 验证断网、重启和快照回退；
5. GroupGuard 再切换到新协议；
6. 观察稳定后，才考虑删除插件端旧业务解析代码。
