# lolapisevers

一个基于 `FastAPI + MySQL + Playwright + LCU API` 的英雄联盟战绩查询服务。

项目同时提供两类能力：

1. `LCU` 本地采集与常规查询。
2. `so1` 站点驱动的跨区查询与快照回退。

## 环境要求

- Python 3.10+
- Windows
- MySQL 8+
- 已安装 Playwright Chromium
- 如需 `LCU` 采集：本机需运行并登录 `LeagueClientUx.exe`

## 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

## 环境变量

### MySQL

```bash
set MYSQL_HOST=127.0.0.1
set MYSQL_PORT=3306
set MYSQL_USER=root
set MYSQL_PASSWORD=123456
set MYSQL_DATABASE=lol_data
```

### so1 账号

```bash
set SO1_USERNAME=mengxin1
set SO1_PASSWORD=mengxin
set SO1_HEADLESS=1
set SO1_TIMEOUT_MS=20000
set SO1_MAX_CONCURRENT_PAGES=2
set APP_PORT=5001
```

说明：

- `SO1_HEADLESS=1` 表示后台无头运行。
- `SO1_MAX_CONCURRENT_PAGES` 用于限制并发页面数，建议从 `2` 或 `3` 起步。
- `APP_PORT` 用于指定监听端口，默认 `5001`。

## 启动服务

```bash
python app.py
```

默认监听：

- `http://127.0.0.1:5001`

后台静默启动：

- 双击 `start_hidden.vbs`
- 启动日志会写入 `logs/server.log`

开机自动运行：

- 把 `start_hidden.vbs` 的快捷方式放入 `shell:startup` 打开的启动目录。

## 健康检查

```bash
curl "http://127.0.0.1:5001/health"
```

正常返回示例：

```json
{
  "status": "ok",
  "mysql": "up",
  "mysql_error": "",
  "so1_browser": "up",
  "so1_max_concurrent_pages": 2
}
```

## 接口说明

### 1. 常规查询

`GET /query?name=召唤师名`

### 2. 隐藏战绩碎片还原

`GET /hidden_query?name=召唤师名`

### 3. 跨区查询

`GET /cross_query?name=召唤师名&region=大区`

示例：

```bash
curl "http://127.0.0.1:5001/cross_query?name=如初见vzk%2342675&region=艾欧尼亚"
```

### 4. 人工初始化会话

`POST /cross_session_init?wait_seconds=180`

说明：

- 当目标站点弹出验证码或自动登录失效时使用。
- 调用后会打开一个可视浏览器，人工完成登录和验证，程序会自动保存会话。

## 服务不可用时的修复方法

### 1. `/health` 不通

现象：

- 浏览器访问或 curl 请求直接失败。

处理：

```bash
python app.py
```

如果提示端口占用：

```bash
netstat -ano | findstr :5001
taskkill /F /PID <PID>
python app.py
```

### 2. `mysql=down`

现象：

- `/health` 返回 `mysql: down`
- 查询接口返回 `MySQL不可用`

处理：

- 确认 MySQL 服务已启动。
- 检查环境变量中的账号密码和库名。
- 确认 `3306` 端口可达。

### 3. `so1_browser=down`

现象：

- `/health` 返回 `so1_browser: down`
- `cross_query` 报浏览器已关闭或未初始化

处理：

- 直接重启服务：

```bash
python app.py
```

- 当前版本已内置浏览器自动重建逻辑；若仍持续失败，多数是系统环境或 Playwright 内核损坏。
- 可重新执行：

```bash
playwright install chromium
```

### 4. `cross_query` 返回 `source=snapshot`

现象：

- 接口还能返回数据，但 `source` 是 `snapshot`
- `is_stale` 为 `true`

说明：

- 这代表实时抓取失败，系统自动回退到了数据库中的最近一次成功快照。
- 服务未完全坏掉，但实时链路需要修复。

处理顺序：

1. 先查看 `fallback_reason`
2. 再检查 `logs` 目录下最新截图和 `logs/server.log`
3. 若为验证码问题，调用：

```bash
curl -X POST "http://127.0.0.1:5001/cross_session_init?wait_seconds=180"
```

4. 若为页面结构变化，需要更新 [so1_client.py](file:///d:/project2/lolapisevers/so1_client.py) 中的登录按钮、输入框或查询触发器选择器。

### 5. 中文输出乱码

现象：

- 终端里中文显示乱码，但接口内容本身正常。

处理：

- 先确认 HTTP 客户端按 UTF-8 解码。
- PowerShell 调试时可设置：

```bash
$env:PYTHONIOENCODING="utf-8"
```

### 6. 并发高时变慢

处理：

- 适当提高 `SO1_MAX_CONCURRENT_PAGES`，但建议小步增加。
- 如果机器内存不足，不要盲目调大。
- 生产场景建议优先让高频查询命中缓存，必要时引入账号池和任务队列。
