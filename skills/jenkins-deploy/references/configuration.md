# Jenkins 配置

脚本从项目 `.agent-skills.json` 读取 `jenkins.profiles.<name>`。示例：

```json
{
  "jenkins": {
    "defaultProfile": "production",
    "profiles": {
      "production": {
        "urlEnv": "JENKINS_URL",
        "usernameEnv": "JENKINS_USER_ID",
        "tokenEnv": "JENKINS_API_TOKEN",
        "remote": "origin",
        "branch": "main",
        "folder": "release",
        "useProxy": false,
        "parameters": {
          "action": "ACTION",
          "ref": "REF",
          "deploy": "DEPLOY",
          "buildOnly": "BUILD_ONLY",
          "rollback": "ROLLBACK",
          "rollbackRelease": "ROLLBACK_RELEASE"
        },
        "artifactPath": "artifact/artifacts/BUILD_INFO",
        "deploymentOrder": ["backend", "web"],
        "components": {
          "backend": {
            "job": "backend-release",
            "changePaths": ["backend/", "shared/"],
            "migrationPaths": ["backend/db/migrations/"],
            "migrationRecord": "docs/deployments.md",
            "health": {
              "urlEnv": "BACKEND_HEALTH_URL",
              "expectStatus": 200,
              "expectJson": {"status": "UP"}
            },
            "releaseIdPattern": "release-backend-[0-9]+-[A-Za-z0-9._-]+"
          }
        }
      }
    }
  }
}
```

字段说明：

- `urlEnv`、`usernameEnv`、`tokenEnv`：Jenkins 地址和认证变量名。也可用 `url` 填写非秘密地址，但账号和 Token 仍必须由环境变量提供。
- `folder`：Job 所在文件夹，支持 `a/b`；留空表示根目录。
- `remote` / `branch`：用于确认远端目标分支最新提交。
- `parameters`：映射项目 Jenkinsfile 的参数名和动作值。
- `artifactPath`：构建后展示提交信息的归档文件；不配置时不核对提交。
- `deploymentOrder`：发布顺序，默认使用组件对象顺序。
- `changePaths`：正则或路径前缀；`plan` 用它判断组件是否需要发布。
- `migrationPaths` / `migrationRecord`：只对需要发布的后端组件检查新增 SQL 是否在登记文档中出现。
- `health.url` 或 `health.urlEnv`：发布后健康检查。`expectStatus` 默认 200，`expectJson` 支持点路径。
- `releaseIdPattern`：回滚 ID 校验正则，`{component}` 会被替换成组件名。

环境变量：

- `JENKINS_INSECURE=1`：仅对使用自签证书的内部 Jenkins 跳过 TLS 校验。
- `JENKINS_USE_PROXY=1`：强制使用系统代理；未设置时默认直连。
