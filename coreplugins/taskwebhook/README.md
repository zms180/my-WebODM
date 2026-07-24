# Task Webhook 插件

任务在 WebODM 中成功完成或进入失败状态后，插件向固定地址发送 HTTP Webhook：

- 成功：`event=task.completed`、`task.status=40`
- 失败或 WebODM 捕获到处理异常：`event=task.failed`、`task.status=30`

取消任务（`status=50`）不会触发 Webhook。

## 配置

修改 `config.py`：

```python
WEBHOOK_ENABLED = True
WEBHOOK_URL = "http://host.docker.internal:9000/webodm/task-completed"
WEBHOOK_SECRET = "replace-with-a-random-secret"
```

`WEBHOOK_URL` 是宿主机接收服务地址。Windows 和 macOS Docker Desktop 可以使用 `host.docker.internal`。接收服务必须监听宿主机可访问的地址，例如 `0.0.0.0:9000`，不能只监听容器内的 `localhost`。

其他配置参数：

| 参数 | 默认值 | 说明 |
| --- | ---: | --- |
| `WEBHOOK_CONNECT_TIMEOUT` | `5` | 建立连接的超时秒数 |
| `WEBHOOK_READ_TIMEOUT` | `15` | 等待响应的超时秒数 |
| `WEBHOOK_MAX_ATTEMPTS` | `5` | 包含首次请求在内的最大投递次数 |
| `WEBHOOK_RETRY_BASE_SECONDS` | `2` | 指数退避的基础秒数 |

## HTTP 请求

- 方法：`POST`
- Content-Type：`application/json; charset=utf-8`
- 成功条件：接收端返回任意 `2xx`
- 自动重试：连接错误、请求超时、`408`、`429` 和 `5xx`
- 不自动重试：其他 `3xx` 和 `4xx`

请求头：

| 请求头 | 说明 |
| --- | --- |
| `X-WebODM-Event` | 事件类型：`task.completed` 或 `task.failed` |
| `X-WebODM-Event-Id` | 本次事件的唯一 UUID |
| `X-WebODM-Timestamp` | 发送时的 Unix 秒时间戳 |
| `X-WebODM-Signature` | 配置密钥后发送，格式为 `sha256=<hex>` |

签名原文为：

```text
X-WebODM-Timestamp + "." + 原始 HTTP 请求体字节
```

使用 `WEBHOOK_SECRET` 对签名原文计算 HMAC-SHA256。接收端应使用原始请求体校验签名，不要先解析 JSON 再重新序列化。

## 推送参数

成功事件示例：

```json
{
  "event": "task.completed",
  "event_id": "3df49198-a1a8-4433-9354-e2b95d1f5a73",
  "payload_version": 1,
  "sent_at": "2026-07-17T10:30:00.123456+00:00",
  "task": {
    "api_path": "/api/projects/12/tasks/af3fd9c1-a575-41d4-a20d-bc9ae771abf7/",
    "available_assets": [
      "orthophoto.tif",
      "georeferenced_model.laz"
    ],
    "created_at": "2026-07-17T09:15:00.000000+00:00",
    "id": "af3fd9c1-a575-41d4-a20d-bc9ae771abf7",
    "name": "survey-2026-07-17",
    "processing_time": 4378123,
    "project_id": 12,
    "project_name": "示例项目",
    "status": 40
  }
}
```

失败或处理异常事件示例：

```json
{
  "event": "task.failed",
  "event_id": "f120749b-7b8c-4ed0-abf6-4ecbdeaf01cc",
  "payload_version": 1,
  "sent_at": "2026-07-22T07:30:00.123456+00:00",
  "task": {
    "api_path": "/api/projects/12/tasks/af3fd9c1-a575-41d4-a20d-bc9ae771abf7/",
    "available_assets": [],
    "created_at": "2026-07-22T07:15:00.000000+00:00",
    "id": "af3fd9c1-a575-41d4-a20d-bc9ae771abf7",
    "last_error": "Invalid zip file",
    "name": "survey-2026-07-22",
    "processing_time": 4378123,
    "project_id": 12,
    "project_name": "示例项目",
    "status": 30
  }
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `payload_version` | integer | 请求体结构版本，当前为 `1` |
| `event` | string | 事件类型：`task.completed` 或 `task.failed` |
| `event_id` | string | 事件唯一 UUID；重试时保持不变 |
| `sent_at` | string | ISO 8601 入队时间 |
| `task.id` | string | WebODM 任务 UUID |
| `task.project_id` | integer | WebODM 项目 ID |
| `task.project_name` | string | 项目名称 |
| `task.name` | string | 任务名称，未设置时为空字符串 |
| `task.status` | integer | 成功为 `40`，失败为 `30` |
| `task.last_error` | string | 仅 `task.failed` 提供；NodeODM 返回或 WebODM 捕获到的错误文本，无错误文本时为空字符串 |
| `task.processing_time` | integer | NodeODM 报告的处理耗时，单位为毫秒 |
| `task.created_at` | string | 任务创建时间，ISO 8601 格式 |
| `task.available_assets` | array[string] | WebODM 已登记的可下载成果 |
| `task.api_path` | string | 查询任务详情的相对 API 路径 |

同一个事件可能因为响应丢失而被重复投递。接收端必须以 `event_id` 做幂等去重，并尽快返回 `2xx`；耗时业务应在接收端异步处理。

NodeODM 报告任务失败，以及 WebODM 在任务处理期间捕获 `NodeServerError` 或 `NodeResponseError` 并将任务标记为失败，都会发送 `task.failed`。未被 WebODM 转换为任务失败状态的进程崩溃或强制终止无法保证发送回调。

## 复制到运行容器

将插件同时复制到 `webapp` 和 `worker` 容器，然后重启两个容器：

```powershell
docker cp .\coreplugins\taskwebhook webapp:/webodm/coreplugins/
docker cp .\coreplugins\taskwebhook worker:/webodm/coreplugins/
docker restart webapp worker
```

如果实际容器名称不同，先用 `docker ps` 查看名称。插件目录没有 `disabled` 文件，WebODM 首次发现时会默认启用；如果数据库中已有同名但被禁用的插件记录，需要在管理后台的 Plugins 页面重新启用。

直接复制到容器的文件会保留到普通重启之后，但删除、重建或升级容器会丢失，需要再次复制。
