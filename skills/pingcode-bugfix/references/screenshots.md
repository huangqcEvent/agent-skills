# 截图证据

## 命名

保存到 `~/.pingcode-mcp/evidence/<工作项>/`：

```text
修改前-首页异常.png
修改后-首页异常.png
修改前-接口返回.png
修改后-接口返回.png
```

同一工作项有多处时，场景名必须能区分位置和状态，例如：

```text
修改前-客户列表-空数据.png
修改后-客户列表-空数据.png
```

## shot.py

```bash
python .agents/skills/pingcode-bugfix/scripts/shot.py app   --route / --login default --item PROJ-10 --stage before --name 首页异常

python .agents/skills/pingcode-bugfix/scripts/shot.py admin   --route dashboard --login none --out ./tmp/dashboard.png
```

- `app`、`admin` 是项目配置 `shot.targets` 中的名称，可替换成任意 target。
- `--login default` 读取 target 的 `login` 配置和账号环境变量。
- `--login user:password` 只适合临时排查；默认使用环境变量，避免账号进入命令历史和日志。
- `--tap` 可以重复，按可见文字依次点击。
- 复杂表单或接口造数应写项目内临时脚本，复用截图函数，不把一次性脚本提交到仓库。

## 可比性

修改前后保持相同：

- target 和路由；
- 登录角色与数据状态；
- 视口尺寸、缩放和主题；
- 操作步骤与等待条件。

如果技术原因无法保持完全一致，在评论中说明变化和原因。
