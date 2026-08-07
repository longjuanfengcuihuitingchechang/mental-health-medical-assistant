# Linux 部署与数据库服务器化

## 1. 当前模式

当前 Windows 研究原型使用：

```text
浏览器 -> 后端 API 服务 -> E 盘 SQLite
```

E 盘 SQLite 只能由后端服务进程访问。浏览器、桌面前端、脚本和其他计算机不得直接打开或共享挂载数据库文件。这是“数据库由服务器托管”的单进程原型模式，不等同于真正的数据库服务器。

SQLite 文件不适合通过 SMB/NFS/移动硬盘共享给多个服务进程并发写入；移动硬盘断开时后端必须进入不可写状态，禁止回退到系统盘。

## 2. Linux 目标模式

生产或多用户部署采用：

```text
Browser
  -> HTTPS reverse proxy
  -> Python API service (systemd/container)
  -> PostgreSQL service
  -> controlled backup storage
```

推荐配置边界：

```text
DATABASE_URL=postgresql+driver://user@database-host/dbname
AUTH_PEPPER_FILE=/run/secrets/mental-health-auth-pepper
APP_TIMEZONE=Asia/Shanghai
```

代码不得依赖 `E:`、反斜杠路径或 Windows COM。数据库访问统一经过 Repository；SQLite 与 PostgreSQL 分别提供适配实现。

## 3. 迁移前提

1. 建立 PostgreSQL schema migration，不能直接复制 SQLite 文件。
2. 将 UUID、布尔、时间、唯一约束和事务锁语义映射为 PostgreSQL 类型。
3. `account_sequences` 改为 PostgreSQL sequence 或事务安全计数器。
4. 密码哈希原样迁移；认证 pepper 通过 Linux secret 挂载，不写入数据库或镜像。
5. 联系方式和身份证仍只迁移 HMAC 指纹与掩码。
6. 迁移后逐项核对角色数量、账号、外键、申请状态和审计记录。
7. 通过并发、连接池、备份恢复、磁盘满和数据库不可用测试后才能切换。

## 4. 服务运行要求

- API 服务使用非 root 账号运行。
- pepper 文件权限为 `0600`，仅服务账号可读。
- 数据库账号按最小权限分离运行、迁移和只读审计权限。
- 会话 Cookie 设置 `HttpOnly`、`Secure` 和合适的 `SameSite`。
- 反向代理限制请求体、超时和登录速率，并传递可信请求 ID。
- 日志不记录密码、会话令牌、身份证、完整手机号、完整邮箱或心理正文。
- 定期执行加密备份和异机恢复演练。

## 5. 当前不可做的假设

- 不能把 E 盘共享目录直接作为 Linux 多实例数据库。
- 不能在多个 Windows/Linux 进程间共同写同一个 SQLite 文件。
- 不能把 `private/` 凭据或 pepper 提交到 Git、复制进容器镜像或公开分发。
- 不能在未实现 HTTPS、认证 API 和恢复方案前将当前原型公开到网络。
