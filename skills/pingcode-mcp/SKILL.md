---
name: pingcode-mcp
description: 安装、更新和排错 PingCode MCP，并使用 pingcode__ 工具读取工作项、原图附件、预览修改和提交评论。用户提到 PingCode、工作项编号、MCP 缺失、认证过期或需要修复回写时使用；凭据只从环境变量或本地凭据文件读取。
metadata:
  short-description: 配置驱动、凭据隔离的 PingCode MCP 安装与操作
---

# PingCode MCP

技能基于开源的 PingCode MCP，并带有锁定提交对应的增强补丁。安装脚本不会内置企业令牌，也不会假设用户名、项目编号或域名。

依赖 `pingcode__*` 工具。工具不存在、认证过期或连接失败时，先完成下面的安装与排错。

## 安装与更新

PowerShell：

```powershell
$env:PINGCODE_CLIENT_ID = '<client-id>'
$env:PINGCODE_CLIENT_SECRET = '<client-secret>'
$env:PINGCODE_BASE_URL = 'https://open.pingcode.com'

powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1 `
  -Me '<PingCode-display-name>' `
  -Project '<project-key>'
```

也支持 `-CredentialsFile <local-json>`；文件结构为：

```json
{
  "baseUrl": "https://open.pingcode.com",
  "clientId": "<client-id>",
  "clientSecret": "<client-secret>"
}
```

凭据文件必须放在 Git 忽略目录。脚本拒绝内置凭据，也不会把 Client Secret 写入仓库或日志。第一次可以加 `-DryRun` 检查参数和安装位置。

脚本会拉取锁定的上游版本、应用增强补丁、构建、换取企业令牌、保存用户级设置，并注册到 Codex；检测到 Claude Code 时也会注册。完成后重启客户端。

## 工具使用

1. `pingcode__list_my_work_items`：列出“我”的未完成工作项；“图”列表示附件图片数量。
2. `pingcode__view_work_item`：读取描述、评论并返回原图。看缺陷必须用它，不要只看 `get_work_item` 的 HTML。
3. `pingcode__submit_fix`：写修复评论、上传修改前后截图、设置“已修复”。企业令牌可能具有写权限，先查看预览，再按用户授权加 `confirm=true`。
4. `pingcode__add_work_item_comment`：只加评论、不改状态，适合需求待确认或非本模块问题。

“我”的身份和默认项目保存在 `~/.pingcode-mcp/settings.json`。改变身份或默认项目时重跑脚本并传入 `-Me`、`-Project`。

## 写操作边界

- 读取和分类可以直接做。
- 用户明确要求“修复后回写”时，可以在完成代码修复与截图后提交预览并写入。
- 用户只要求查看或分析时，不修改工作项状态。
- 不推断测试意见与当前需求一致；存在需求冲突时写评论说明并保留原状态。
- 评论只写已验证事实。未推送、未合并、未部署的代码要明确写出当前状态。

详细字段和排错见 [技术说明](references/pingcode-notes.md)。缺陷处理流程见 `pingcode-bugfix`。
