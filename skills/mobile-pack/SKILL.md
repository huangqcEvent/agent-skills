---
name: mobile-pack
description: 通过 HBuilderX CLI 构建 Android APK 或 iOS IPA 并下载产物。用户说“打包移动端”“打包 APK/App/Android/iOS”或要求复用现有 HBuilderX 云打包配置时使用；项目目录、包名、Bundle ID、签名和环境变量均由项目配置提供。
---

# 移动端打包

使用 `scripts/mobile_pack.py`。脚本从项目 `.agent-skills.json` 的 `mobilePack` 章节读取项目目录、manifest、输出目录和签名配置。

## 先确认平台

用户没有明确 Android 或 iOS 时，先询问平台。用户已说“安卓包”“iOS 包”或本轮选择过平台，就直接执行，不重复询问。

真实打包需要已登录的 HBuilderX、Python 3.9+、项目 npm 依赖和有效签名配置。项目配置缺失时报告缺少的字段；密码只能从环境变量或本地密码文件读取，不能要求用户在聊天中发送。

## 执行流程

```bash
S=.agents/skills/mobile-pack/scripts/mobile_pack.py
python "$S" --platform android --dry-run
python "$S" --platform android
python "$S" --platform ios
```

1. `--dry-run` 只输出脱敏后的 HBuilderX 配置，用来检查路径、包名和参数。
2. 真正执行时脚本启动 HBuilderX、导入项目、提交云打包、跟踪日志并下载安装包。
3. 日志较长时持续等待。约每分钟说明仍在编译、排队或下载；提交云端成功不等于安装包已生成。
4. 超时或中断时先用 `pack status` 查询已有任务，不能直接重复提交。
5. 下载失败只重试下载，不重新打包。

查看任务：

```bash
"${HBUILDERX_CLI:-<configured-cli>}" pack status --project "<configured-project>"
```

## 完成条件

只有脚本返回 `安装包已保存` 且退出码为 0 时，才能报告打包完成。回复中给出平台、版本、产物绝对路径、大小、警告，以及是否需要重新登录或补充配置。

打包技能不负责上传应用市场、发布 Jenkins、修改业务代码或运行额外测试，除非用户明确要求。配置字段见 [配置说明](references/configuration.md)。
