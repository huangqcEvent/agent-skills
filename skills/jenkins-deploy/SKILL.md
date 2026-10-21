---
name: jenkins-deploy
description: 通过 Jenkins Remote Access API 检查、规划、构建、发布、回滚和查询项目。用户说“Jenkins 发布”“部署”“看看线上版本”“只构建”或“回滚发布”时使用；项目 Job、模块、分支、迁移和健康检查均从项目配置读取。
metadata:
  short-description: 配置驱动的 Jenkins 构建、发布、回滚与状态查询
---

# Jenkins 部署

使用 `scripts/jenkins_deploy.py`，只依赖 Python 标准库。脚本读取项目根目录 `.agent-skills.json` 的 `jenkins` 章节；项目没有该文件时，先复制并填写仓库的 `config/agent-skills.example.json`。

## 前置检查

1. 阅读项目自己的发布文档和 `AGENTS.md`，确认分支、审批、数据库迁移和回滚口径。
2. 运行 `check`，确认 Jenkins 身份、组件 Job、最近构建和线上版本。
3. 发布只使用已经推送到远端目标分支的提交。工作区未提交或未推送的代码不会被 Jenkins 发布。
4. Jenkins 凭据只放环境变量，变量名由配置指定。不要把 Token 写入命令、配置或聊天。

## 标准流程

```bash
S=.agents/skills/jenkins-deploy/scripts/jenkins_deploy.py
python "$S" check
python "$S" plan
```

把 `plan` 的目标分支、提交、需要发布的组件、迁移和风险原样给用户看。用户明确确认后执行：

```bash
python "$S" deploy backend web --commit <plan 给出的提交号> --yes
```

规则：

- 没有 `--yes` 时只显示发布预览。
- 有新增迁移且配置了迁移目录时，先执行迁移并登记，再给 `deploy` 加 `--migrations-done`。
- 按 `deploymentOrder` 顺序发布；任一组件失败立即停止，不自动回滚。
- 每个成功发布都核对构建提交和配置的健康检查。失败时给出 Console、日志路径和回滚命令。
- 用户只要求验证流水线时用 `build`；它只构建，不执行生产阶段。
- 回滚必须先展示发布 ID与影响，再使用 `rollback <组件> --release <ID> --yes`。

## 命令

```text
check                         身份、Job、线上版本和最近构建
plan [--ref REF]              目标提交、模块变化和待执行迁移
deploy <组件...> --commit SHA [--ref REF] [--yes]
build <组件...> [--ref REF]   只构建，不发布
rollback <组件> --release ID [--yes]
status <组件> [--build N] [--tail N]
```

默认配置文件和 profile 可被 `--config`、`--profile` 覆盖。配置字段见 [配置说明](references/configuration.md)。

## 故障处理

- `401`：核对用户名和 API Token 的变量是否正确。
- `403 crumb`：脚本会尝试自动获取 CSRF crumb；仍失败时检查 Jenkins CSRF 策略。
- 内网连接失败：先连 VPN，再确认配置中的代理策略。
- 分支最新提交与 `--commit` 不一致：重新运行 `plan`，禁止直接沿用旧提交发布。
- 构建成功但健康检查失败：停止后续组件，保留日志；由用户决定修复或回滚。
