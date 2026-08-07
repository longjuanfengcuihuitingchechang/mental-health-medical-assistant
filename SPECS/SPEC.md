# 心理健康专项智能医疗助手：技术规格说明

## 1. 适用范围

本文定义后续实现的技术基线。当前阶段只写规格，不创建数据库、不安装依赖、不修改指定前端。

## 2. 推荐技术栈

| 层 | 选择 | 说明 |
|---|---|---|
| 前端 | 现有 HTML + Tailwind CSS | 复用指定目录；当前为 CDN 静态页面，后续以完整前端提示词指导接入 |
| 后端 | Python 3.12 + FastAPI | 与参考系统 Python 逻辑兼容，原生支持 OpenAPI 与流式响应 |
| 校验 | Pydantic v2 | 统一请求、响应和配置 schema |
| 数据访问 | SQLAlchemy 2 + Alembic | 避免 Controller 拼 SQL，支持后续迁移数据库 |
| MVP 数据库 | SQLite 3（WAL） | 数据文件位于 E 盘；仅适用单机/低并发研究原型 |
| 认证 | 服务端会话 Cookie | `HttpOnly`、`Secure`、`SameSite=Lax/Strict`；不在 localStorage 放长期 token |
| 实时输出 | SSE | 文本单向流足够，重连模型简单 |
| 测试 | pytest + HTTPX | 单元、集成、权限、安全和故障注入 |

若实现阶段发现上述组件未安装，应先给出完整 PowerShell 安装命令并等待用户确认，不代为下载安装。

## 3. 配置规范

建议环境变量名（本文不修改 `.env`）：

```text
APP_ENV=development|test|production
APP_TIMEZONE=Asia/Shanghai
DATABASE_PATH=E:\05_数据库与SQL\mental_health_assistant\data\mental_health.db
DATABASE_REQUIRE_DRIVE=E:
DATABASE_MIN_FREE_MB=2048
SESSION_SECRET=<external secret>
FIELD_ENCRYPTION_KEY_REF=<OS key reference>
LLM_PROVIDER=<provider>
LLM_MODEL=<model>
LLM_API_KEY=<external secret>
```

启动校验：

1. `DATABASE_PATH` 必须是绝对路径，规范化后仍位于允许根目录。
2. 实际卷标/盘符必须符合 `DATABASE_REQUIRE_DRIVE`。
3. 密钥不能等于默认值，也不能位于 E 盘项目目录。
4. 生产环境禁止 `debug`、宽泛 CORS 和 Tailwind CDN。
5. 数据库不可写或空间不足时拒绝启动写服务。

## 4. 数据库规范

### 4.1 连接与事务

- 每个 HTTP 请求最多一个工作单元；写操作显式事务。
- 启用 `PRAGMA foreign_keys=ON`、合理 `busy_timeout`，并对 WAL 模式做启动验证。
- SQLite 连接不得跨线程无控制共享；后台任务使用独立 session。
- 迁移由 Alembic 版本控制，应用启动不得自动执行不可逆迁移。
- 所有删除默认软删除或状态失效；真正清除由保留策略和审批流程处理。

### 4.2 必要字段约定

所有业务表至少按需包含：

```text
id, created_at, updated_at, version
subject_user_id / owner_user_id
created_by, updated_by
deleted_at (需要软删除时)
```

审计表只追加；量表发布版本、答卷、得分和风险证据不得原地覆盖。

### 4.3 索引

- 所有外键建索引。
- 高频复合索引：`(subject_user_id, created_at)`、`(clinician_id, status, created_at)`、`(risk_level, status, detected_at)`。
- `idempotency_key`、用户名/账号、量表代码+版本建立唯一约束。

## 5. 量表与安全引擎

### 5.1 量表定义

量表配置包括 `code`、`display_name`、`version`、`locale`、`items`、选项、反向题、计分公式、分量表、解释区间、版权/授权来源、适用人群、发布状态和校验哈希。

现有 SAS/SDS/SCL-90 逻辑可作为迁移输入，不能直接视为临床定稿。正式发布前必须由具备资质的专业人员核对题目授权、版本、计分取整方式、阈值和适用人群。新增 PHQ-9/GAD-7 等量表同样遵循版本与授权审核。

### 5.2 风险级别

```text
low      无即时危机证据，提供一般支持
medium   存在持续困扰或显著量表信号，建议专业评估并进入随访
high     出现明确自伤/他伤意图、计划、手段、近期行为或关键题项
critical 已发生行为或有迫近危险，需要立即现实世界求助
```

上述是工作流等级，不是医学诊断。规则命中要保存 `rule_id`、`rule_version`、证据类型、证据摘要、时间和结果。敏感原文只在必要时加密保存。

## 6. 智能体规范

### 6.1 可用工具

- `get_user_context`：读取最少必要档案与授权。
- `list_assessments` / `start_assessment`：只返回已发布版本。
- `get_wellbeing_trend`：返回结构化趋势，不生成诊断。
- `create_followup_request`：创建请求，不声称预约已确认。
- `list_support_resources`：只返回已验证且有效的资源。
- `raise_risk_event`：只能提升/创建风险，不能关闭事件。

医生关闭风险事件必须通过普通业务 API 和显式理由，不能由模型工具直接执行。

### 6.2 提示与输出

- 系统提示固定声明角色边界、危机规则、禁做事项和工具权限。
- 对话上下文按用户、会话和授权隔离；不跨患者检索。
- 每次模型运行保存供应商、模型、提示词版本、工具版本、延迟、状态和安全判定，不保存 API key。
- 输出必须经过危机遗漏、处方/确诊、隐私泄漏和工具结果一致性检查。
- 对不确定信息明确表达不确定性，鼓励联系专业人员。

## 7. 认证与安全

- 密码采用成熟自适应哈希（Argon2id 或等效方案），禁止明文和可逆加密。
- 登录、敏感查询、导出、量表发布、风险处置和权限变更写审计。
- 登录与对话接口限流；连续失败触发渐进延迟，不向客户端泄漏账号是否存在。
- 请求使用统一 `request_id`；日志对姓名、证件号、手机号、对话正文和 token 做脱敏。
- 数据导出设置有效期、最小字段和下载审计。
- 个人数据撤回/删除请求不能破坏法定或安全审计，需区分删除、匿名化和保留义务。

## 8. API 与 SSE 技术约定

- API 前缀：`/api/v1`；JSON 编码 UTF-8。
- 时间：ISO 8601 带时区；存储 UTC。
- 列表：游标分页优先，`limit` 最大 100。
- 写请求支持 `Idempotency-Key`；重复键返回原结果或 409。
- 乐观并发使用 `version`/`If-Match`，冲突返回 409。
- SSE `Content-Type: text/event-stream`，事件含 `id`、`event` 和 JSON `data`。

## 9. 错误码

| HTTP | 代码 | 含义 |
|---:|---|---|
| 400 | `VALIDATION_ERROR` | 参数、答卷或状态转换无效 |
| 401 | `UNAUTHENTICATED` | 未登录或会话失效 |
| 403 | `FORBIDDEN` | 角色或数据范围不允许 |
| 404 | `NOT_FOUND` | 资源不存在或对当前用户不可见 |
| 409 | `CONFLICT` | 幂等键、版本或状态冲突 |
| 422 | `ASSESSMENT_INCOMPLETE` | 量表答案不完整/不合法 |
| 423 | `DATABASE_UNAVAILABLE` | E 盘数据库不可写或维护中 |
| 429 | `RATE_LIMITED` | 请求过频 |
| 503 | `MODEL_UNAVAILABLE` | 模型不可用；安全规则仍应可用 |

## 10. 测试矩阵

| 类别 | 必测内容 |
|---|---|
| 单元 | 量表计分、风险规则、状态机、权限策略、脱敏 |
| 集成 | API + SQLite 事务、迁移、SSE、幂等、审计 |
| 安全 | 横向/纵向越权、注入、会话固定、敏感日志、导出权限 |
| 故障 | 拔盘、只读盘、磁盘满、数据库锁、损坏、模型/通知超时 |
| 临床安全 | 高风险表达、否认后反复表达、混合语言、模型拒答、危机卡 |
| 前端契约 | 15 个现有页面路由、空/载入/错误/断网/权限状态 |

## 11. 发布门槛

- 临床负责人签署量表版本、解释文本和风险规则。
- 隐私负责人确认单独同意、告知、导出、撤回和保留策略。
- E 盘加密、备份、恢复、拔盘与磁盘满测试通过。
- 不使用真实患者数据进行未审批的开发和模型调试。
- 高风险全链路演练通过，且所有通知状态真实可验证。

## 12. 患者页面助手技术规格

### 12.1 确定性路由顺序

1. 从服务端会话取得患者身份并检查账号可用性。
2. 根据出生日期计算年龄组，不让模型推算年龄。
3. 先检查危机表达；命中后绕过模型并返回现实求助渠道。
4. 再检查正式诊疗意图；读取医生状态、既往接诊关系和队列，确定性返回医生选项。
5. 再检查跨页主题；返回目标页枚举，不让模型自由扩展回答。
6. 只有当前页普通功能问题调用一次 `BaseLLM`；失败时返回安全降级文本。

### 12.2 数据与隐私

- `doctor_availability` 保存结构化状态和预计返岗时间，缺失即 `unknown`。
- `clinical_visit_summaries` 保存最小就诊关系和可选受控摘要；当前版本不把摘要发送给 LLM。
- `consultation_queue` 只统计 `waiting/called`，同一患者在同一医生名下最多一个活动队列项。
- `minor_guardian_consents` 记录 `pending/granted/revoked`，只影响正式诊疗提示，不屏蔽危机资源。
- 请求最大 2000 字；患者 ID、出生日期、联系方式、证件和病历正文均不进入模型提示。

### 12.3 状态与降级

允许响应类型：`page_intro`、`page_answer`、`out_of_scope`、`care_navigation`、`crisis_support`。医生状态允许 `working`、`off_duty`、`on_leave`、`unavailable`、`unknown`。模型错误不能影响页面介绍、诊疗导航或危机支持。

### 12.4 会话、模板和 DeepSeek

- 页面及功能介绍使用代码内版本化模板直接响应，不为固定文案消耗模型调用。
- 同一会话跨页携带最近 12 条对话；DeepSeek API 无状态，历史由服务端按患者和会话隔离后拼接。
- DeepSeek 使用 `POST {DEEPSEEK_BASE_URL}/chat/completions`，默认模型 `deepseek-v4-flash`、关闭思考模式、低温度和短输出限制，以降低页面功能问答延迟。
- `.env` 只允许包含服务端配置；前端构建产物不得嵌入 `DEEPSEEK_API_KEY`。

## 13. 预约状态机技术规格

- 指定医生资格只统计 `clinical_visit_summaries.status='completed'`，阈值为 10。
- 容量日期只能为服务端当天后的第 1 或第 2 天；容量允许 0–1000，并使用版本号递增。
- 队列号在 `BEGIN IMMEDIATE` 事务中按医生和日期生成；所有成功或待确认预约都有队列号。
- 超额预约状态依次为 `awaiting_patient_decision`、`awaiting_doctor_decision`，最终进入 `queued_over_capacity` 或拒绝状态。
- 夜班日期为主键，数据库层保证同日最多一位医生；排班权限限助理和管理员。
- `assistant` 使用 `Snnn` 账号、独立登录入口和独立 Profile，不映射成管理员角色。
