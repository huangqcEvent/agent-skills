# PingCode MCP Skill

## 文件

- `SKILL.md`：Codex 使用规则。
- `scripts/setup.ps1`：安装、认证、更新与注册脚本。
- `assets/upstream-fixes.patch`：锁定上游提交的增强补丁。
- `references/pingcode-notes.md`：工具行为与排错说明。

## 凭据

优先使用：

```text
PINGCODE_CLIENT_ID
PINGCODE_CLIENT_SECRET
PINGCODE_BASE_URL
```

也可以使用 `-CredentialsFile` 指向本地 JSON。仓库不包含任何企业或个人凭据。

## 常用命令

```powershell
# 只检查环境和参数
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -DryRun

# 完整安装或更新
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -Me "Your Name" -Project "PROJ"

# 只刷新认证
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -AuthOnly -Me "Your Name" -Project "PROJ"
```
