# 项目本地环境模板

这个文件是模板。复制到项目自己的本地说明或 `.agent-skills.json`，按真实环境填写，不提交账号和秘密。

## 启动

```text
App: <command>
Admin: <command>
Backend: <command>
```

## 本地地址

```text
App: <url>
Admin: <url>
API: <url>
```

## 测试身份

```text
App user env: LOCAL_APP_USER / LOCAL_APP_PASSWORD
Admin user env: LOCAL_ADMIN_USER / LOCAL_ADMIN_PASSWORD
角色或权限状态: <fill>
测试数据: <fill>
```

## 校验

```text
Frontend: <validate command>
Backend: <test command>
Standards: <optional command>
```

## 注意事项

- 需要 VPN / 代理时写清楚。
- 需要迁移或种子数据时写命令，不写真实密码。
- 外部服务 mock 的边界和数据来源。
