---
name: pingcode-bugfix
description: 用 PingCode MCP 盘点、阅读、分类、修复和回写项目缺陷，并生成修改前后截图证据。用户说“看看我的 bug”“盘点缺陷”“看某条工作项”“修复并回写”或提供 PingCode 工作项链接时使用；项目地址、测试账号和校验命令从项目配置读取。
metadata:
  short-description: PingCode 缺陷盘点、读图、修复、证据与回写闭环
---

# PingCode 缺陷处理

依赖 `pingcode__*` 工具。工具不可用时，先按 `../pingcode-mcp/SKILL.md` 安装或排错。

## 选择模式

| 用户意图 | 产出 |
| --- | --- |
| 看、盘点、有哪些缺陷 | 分类表和下一步建议，停下等用户选择 |
| 看单条、贴链接 | bug 理解卡 |
| 修复、解决并回写 | 代码改动、验证、修改前后证据、评论和状态 |
| 一批处理完 | 批量收尾报告 |

## 先理解，再修改

1. 用 `pingcode__view_work_item` 读取正文、重现步骤、评论和附件。
2. 把返回的每张 `[图N]` 都检查一遍。超过返回上限的图从缓存目录读取原图。不得只凭标题判断。
3. 按 [读图规范](references/reading-bugs.md) 写 bug 理解卡。
4. 对照当前代码、Git 历史和项目需求分类：
   - A 已修复
   - B 当前代码确实需要修复
   - C 需求冲突或信息不足，需要确认
   - D 不是缺陷或不属于当前负责范围
5. 盘点模式按 [汇报规范](references/reporting.md) 输出后停止，不未经选择就批量修改。

## 修复

1. 按项目 `AGENTS.md` 和本地环境说明复现。
2. 留存“修改前”证据：按重现步骤截图，或使用工作项原图；接口问题记录请求、响应和日志。
3. 只修改 B 类问题的相关范围，不夹带走查到的其他问题。
4. 执行项目规定的校验。命令和账号从项目 `.agent-skills.json` 或项目本地说明读取，不能照搬其他项目的测试命令。
5. 在同一页面、同一账号状态、同一尺寸和同一步骤生成“修改后”证据。
6. 用项目要求的提交格式提交代码；不把截图、安装包、缓存或凭据提交到代码仓库。
7. 按 [评论规范](references/fix-comment.md) 准备 `pingcode__submit_fix`。先看预览，再按用户授权正式写入。

A 类已经修复的问题仍可回写：使用工作项原图作为修改前证据，用当前代码截图作为修改后证据，并写清最初修复对应的提交。

C、D 类使用 `pingcode__add_work_item_comment` 说明原因，不修改状态：“已修复”只用于当前代码确实完成并有验证的问题。

## 证据

截图默认保存到 `~/.pingcode-mcp/evidence/<工作项>/`，不影响代码仓库。脚本和命名规范见 [留图规范](references/screenshots.md)。

```bash
python .agents/skills/pingcode-bugfix/scripts/shot.py app   --route / --login default --item PROJ-10 --stage before --name 首页异常
```

`shot.py` 支持 `before/after` 以及中文 `修改前/修改后`。页面地址、登录字段、账号环境变量、浏览器通道和默认尺寸来自项目 `.agent-skills.json` 的 `shot.targets`。

## 收尾

按 [汇报规范](references/reporting.md) 给出：

- 已修复和已验证的问题；
- 已回写评论和状态变化；
- 仍待确认、不归当前范围的问题；
- 代码是否只提交、推送、合并或部署；这些状态不要混写。

项目特有的启动、账号和校验命令填入 [项目本地模板](references/project-local.example.md)，并放在项目自己的本地文档中。
