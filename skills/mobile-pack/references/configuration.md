# 移动端打包配置

项目根目录 `.agent-skills.json`：

```json
{
  "mobilePack": {
    "project": ".",
    "manifest": "src/manifest.json",
    "outputDir": "unpackage/release",
    "namePrefix": "example-app",
    "cliEnv": "HBUILDERX_CLI",
    "timeoutSec": 2700,
    "requireNodeModules": true,
    "android": {
      "packageName": "com.example.app",
      "certAlias": "release",
      "certFile": "signing/release.keystore",
      "certPasswordEnv": "MOBILE_ANDROID_KEY_PASSWORD",
      "storePasswordEnv": "MOBILE_ANDROID_STORE_PASSWORD"
    },
    "ios": {
      "bundleId": "com.example.app",
      "certFile": "signing/release.p12",
      "profile": "signing/release.mobileprovision",
      "certPasswordEnv": "MOBILE_IOS_CERT_PASSWORD",
      "supportedDevices": "iPhone"
    }
  }
}
```

相对路径均相对于项目根目录，`project` 相对于 `.agent-skills.json`。

可选字段：

- `cli`：HBuilderX CLI 绝对路径；也可通过 `cliEnv` 指向环境变量。
- `passwordFile`：本地密码文件，作为对应密码环境变量缺失时的回退；文件只能放在 Git 忽略目录。
- `packOptions`：传给 HBuilderX 的通用布尔选项。
- `artifactPattern`：产物名模板，可用 `{name}`、`{platform}`、`{version}`、`{versionCode}`、`{timestamp}`。
- `requireNodeModules`：默认 `true`；确实不需要本地依赖时设为 `false`。

Android 使用 `packageName`、`certAlias`、`certFile` 和两个密码字段。iOS 使用 Bundle ID、`.p12`、`.mobileprovision` 和证书密码。传输密码文件或证书时不进入仓库。
