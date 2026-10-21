# Agent Skills

可复用的 Codex 操作技能集合，当前包含：

- `jenkins-deploy`：通过 Jenkins Remote Access API 执行检查、计划、构建、发布、回滚和状态查询。
- `mobile-pack`：通过 HBuilderX CLI 构建并下载 Android APK 或 iOS IPA。
- `pingcode-mcp`：安装、更新和排错 PingCode MCP，凭据只从环境变量或本地文件读取。
- `pingcode-bugfix`：盘点、阅读、修复 PingCode 缺陷，并生成修改前后证据和回写评论。

仓库只保存通用流程与脚本。项目地址、Job 名、模块名、域名、签名文件和账号不进入仓库。

## 安装到项目

```bash
python scripts/install.py --target ../your-project
```

默认安装全部技能到 `<project>/.agents/skills/`，同时生成不覆盖已有文件的配置示例：

- `<project>/.agent-skills.example.json`
- `<project>/.agent-skills.env.example`

安装单个技能：

```bash
python scripts/install.py --target ../your-project --skills jenkins-deploy mobile-pack
```

更新已有技能时加 `--force`。安装器只复制技能目录，不会复制配置或凭据。

## 项目配置

在项目根目录创建 `.agent-skills.json`。可以从 [配置示例](config/agent-skills.example.json) 开始，并按实际项目填写。脚本会从当前目录向上查找该文件，也可用 `--config` 显式指定。

凭据使用环境变量：

```bash
export JENKINS_URL=https://jenkins.example.internal
export JENKINS_USER_ID=your-id
export JENKINS_API_TOKEN=your-token
export PINGCODE_CLIENT_ID=your-client-id
export PINGCODE_CLIENT_SECRET=your-client-secret
export MOBILE_ANDROID_STORE_PASSWORD=your-store-password
export MOBILE_ANDROID_KEY_PASSWORD=your-key-password
export MOBILE_IOS_CERT_PASSWORD=your-cert-password
```

Windows PowerShell 使用 `$env:NAME = 'value'`。不要把真实 Token、密码、证书、描述文件或含真实配置的 `.agent-skills.json` 提交到 Git。

## 使用

技能触发词、发布确认规则和故障处理见各技能自己的 `SKILL.md`。常用脚本：

```bash
python .agents/skills/jenkins-deploy/scripts/jenkins_deploy.py plan
python .agents/skills/mobile-pack/scripts/mobile_pack.py --platform android --dry-run
powershell -ExecutionPolicy Bypass -File .agents/skills/pingcode-mcp/scripts/setup.ps1 -Me "Your Name" -Project "PROJ"
python .agents/skills/pingcode-bugfix/scripts/shot.py app --route / --login default --out ./tmp/home.png
```

`jenkins_deploy.py deploy` 在没有 `--yes` 时只输出预览。先执行 `plan`，展示目标提交、模块、迁移和风险，再要求发布。

## 自检

```bash
python scripts/validate.py
```

校验器检查技能目录、YAML frontmatter、Python 语法、硬编码敏感信息以及常见项目绑定。它不能代替真实运行环境中的连通性检查。

## 目录

```text
config/                    项目配置与凭据变量示例
scripts/install.py         安装技能到目标项目
scripts/validate.py        仓库自检
skills/<skill>/SKILL.md    技能入口
skills/<skill>/scripts/    可执行辅助脚本
skills/<skill>/references/ 按需加载的详细说明
```
