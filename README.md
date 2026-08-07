# Mental Health Medical Assistant

面向心理健康场景的多角色智能医疗助手研究原型，包含患者、医生、助理、管理员以及基于 DeepSeek 的受控页面/工作助手。

> 本项目仅用于研究和开发，不提供医学诊断、处方或紧急服务。存在立即危险时，请联系当地紧急服务；在中国大陆可拨打 12356、110 或 120。

## 当前能力

- 患者、医生、助理、管理员身份认证与会话隔离。
- 医生注册审批、管理员人员目录和敏感标识脱敏存储。
- 患者页面助手、跨页记忆、介绍限次及正式诊疗导航。
- 完成就诊 10 次后的指定医生预约、容量、队列和超额协商。
- 医生未来两天接诊容量、每日唯一夜班和助理协调角色。
- SQLite migration、E 盘硬失败策略及未来 Linux/PostgreSQL 迁移边界。

## 项目结构

```text
backend/    Python 标准库后端领域 Agent、SQLite、迁移和测试
fronts/     Tailwind 静态前端原型
SPECS/      产品、技术、架构、API 和前端规格
scripts/    Windows 开发与快捷方式脚本
assets/     项目图标
```

## 本地开发

要求：Windows PowerShell、Git、Python 3.11 或更高版本。

```powershell
Set-Location -LiteralPath 'D:\path\to\mental-health-medical-assistant'
.\scripts\Setup-Dev.ps1
```

再次运行测试：

```powershell
.\scripts\Run-Tests.ps1
```

当前测试使用临时 SQLite，不需要访问正式 E 盘数据库。真实配置请复制 `.env.example` 为 `.env` 并填入本机路径和服务端 Key；`.env`、`private/` 和数据库文件不会进入 Git。

## DeepSeek

DeepSeek 只由后端读取 `DEEPSEEK_API_KEY` 并调用。前端不得读取 `.env` 或直接连接模型服务。未配置 Key 时使用明确的安全降级。

## 重要边界

- 当前 SQLite 只允许单一后端服务进程拥有写权限，不是多人生产数据库服务器。
- 医生和助理工作助手的只读 Tool Registry、HTTP 路由及药物库存数据源仍待实现。
- `fronts` 目前是静态原型；目标接口和完整改造要求见 `SPECS/`。
- 不要使用真实患者资料进行未审批的开发、演示或模型调试。

## 文档

- [v1.0.0 需求与系统边界](SPECS/V1.0.0_需求与系统边界.md)
- [v1.0.0 API 与数据结构](SPECS/V1.0.0_API与数据结构.md)
- [v1.0.0 Linux 与容器基础环境](SPECS/V1.0.0_Linux与容器基础环境.md)
- [产品需求](SPECS/PRD.md)
- [技术规格](SPECS/SPEC.md)
- [系统架构](SPECS/ARCHITECTURE.md)
- [接口契约](SPECS/API.md)
- [全部前端修改意见](SPECS/前端全部修改意见.md)
- [助理端生成 Prompt](SPECS/助理端生成Prompt.md)

## 贡献与安全

提交问题和变更前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。安全问题请按 [SECURITY.md](SECURITY.md) 私下报告，不要在公开 Issue 中提交患者数据、密钥或漏洞利用细节。
