# PingCode MCP 说明

## 认证模型

脚本使用企业 Client ID / Client Secret 换取 access token。凭据来源顺序：

1. `PINGCODE_CLIENT_ID` / `PINGCODE_CLIENT_SECRET`
2. `-CredentialsFile` 指定的本地 JSON

`PINGCODE_BASE_URL` 或本地文件中的 `baseUrl` 指定服务地址。默认使用 PingCode 公有云的官方开放接口地址。

## 用户身份

企业令牌不代表具体个人。“我”来自用户级设置 `~/.pingcode-mcp/settings.json` 的 `me`，默认项目来自 `default_project`。这是用户级本地设置，不应写入共享仓库。

## 截图和证据

`view_work_item` 会把附件原图返回给模型，并缓存到 `~/.pingcode-mcp/cache/<工作项>/`。修复证据默认放在 `~/.pingcode-mcp/evidence/<工作项>/`。

常见命名：

- `修改前-<场景>.png`
- `修改后-<场景>.png`

## 写操作

写工具在不带确认参数时应返回预览。看到预览后：

- 用户已明确授权回写：确认预览，再执行正式写入。
- 只是排查或分析：不写入。
- 需求不确定、应该由产品或其他人判断：只加说明评论，不改状态。

## 排错

- 找不到工具：确认安装完成并重启客户端。
- `401`：Client ID/Secret 失效或 Base URL 错误。
- JSON 解析失败：用户设置或认证文件需要无 BOM 的 UTF-8。
- 截图为空：使用 `view_work_item`，不要依赖原始 HTML。
- 写入出现预览：这是预期的防误操作行为。
