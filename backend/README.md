# Backend

当前实现包含 SQLite schema 和第一个确定性 Agent：管理员目录查询。

第二个确定性 Agent 为身份登录，支持患者、医生、管理员三种入口；管理员入口同时覆盖 `admin` 和 `super_admin`。连续第 7 次失败发出锁定预警，第 8 次失败锁定 5 分钟。

## 权限

- `admin`：可查看患者和医生基本信息。
- `super_admin`：除上述能力外，可查看管理员基本信息。
- 其他角色：无权调用。

`requester_user_id` 必须来自服务端认证会话，不能信任浏览器请求体中的同名字段。

## 数据库

目标路径：

```text
E:\05_数据库与SQL\mental_health_assistant\data\mental_health.db
```

初始化脚本不会创建默认账号或密码。后续应通过独立、安全的最高管理员引导流程创建首个账号。

登录密码必须通过 `app.core.passwords.PasswordHasher` 生成哈希后写入；禁止直接写入明文。Agent 成功返回的原始会话令牌只应由后续 HTTP 层写入 `HttpOnly` Cookie。

注册 Agent 为患者生成 `Pnnn`，注册后立即激活；为医生生成 `Dnnn`，管理员审批前保持 `pending`。账号、手机号和邮箱均可作为登录标识。数据库只保存联系方式和身份证的 HMAC 指纹与掩码。

患者页面助手 Agent 负责当前页介绍、当前页限定问答、跨页导航、正式诊疗导航和危机支持。年龄由服务端计算；医生状态、既往接诊关系和排队信息只读取 SQLite 结构化记录。危机和诊疗导航绕过普通 LLM 生成。`BaseLLM` 可注入真实模型适配器；未配置时使用明确的规则降级。

正式库当前没有真实排班、就诊和排队数据，因此医生可用性返回 `unknown`。后续必须由经过授权的排班/状态接口写入，禁止用静态演示数据冒充真实医疗状态。

页面/功能介绍使用预置模板，前 8 次打开会显示，第 9 次起停止自动介绍。患者助手会话跨页保存最近受控消息，功能打开次数与使用日志写入 SQLite。

DeepSeek 配置由服务端按以下优先级只读加载：进程环境变量、项目根目录 `.env`。支持的键为：

```text
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_TIMEOUT_SECONDS=20
```

没有 Key 时自动使用规则降级；Key 不写入数据库、日志或浏览器。当前实现不依赖 `python-dotenv` 或 OpenAI SDK。

预约模块包含医生未来两天容量、完成就诊 10 次资格、容量内排队、超额患者确认、医生接受/拒绝、委婉通知和每日唯一夜班。助理使用独立 `assistant` 角色及 `Snnn` 账号，登录后目标为 `assistant/index.html`。

两个合成助理账号的初始凭据保存在 `private/assistant_accounts.csv`。该文件和认证 pepper 仅授权当前用户、SYSTEM 与本机管理员访问，不得加入 Git 或复制到前端目录。

初始化账号凭据和认证 pepper 保存在项目 `private/`，该目录已加入 `.gitignore`。初始化账号是合成演示数据，不得用于发送真实短信或邮件。

## 服务器边界

当前 SQLite 只能由一个后端服务进程访问，前端和其他客户端不得直连或共享打开 E 盘数据库。未来 Linux 多用户环境迁移到 PostgreSQL，使用 `DATABASE_PATH`/后续 `DATABASE_URL` 和 `AUTH_PEPPER_FILE` 注入路径，不能把 E 盘 SQLite 当作多进程数据库服务器。

服务端统一从 `app.container.build_application_agents()` 获取 Agent 实例；不要在 API 路由或前端代码中自行创建数据库连接。

只读验证：

```powershell
Set-Location -LiteralPath 'D:\SCY个人代码\assistant\backend'
python scripts\verify_database.py
```

## 测试

```powershell
Set-Location -LiteralPath 'D:\SCY个人代码\assistant\backend'
$env:PYTHONPATH = (Get-Location).Path
python -m unittest discover -s tests -v
```
