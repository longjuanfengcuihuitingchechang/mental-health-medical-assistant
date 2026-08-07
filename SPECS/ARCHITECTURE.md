# 心理健康专项智能医疗助手：ARCHITECTURE

## 1. 架构结论

MVP 采用“模块化单体后端 + 静态 Tailwind 前端 + E 盘 SQLite”的单机/小规模研究架构。该选择便于复用现有 Python 业务逻辑和指定静态页面，也符合移动硬盘本地存储目标；它不适用于多节点、多用户高并发生产部署。若进入真实医疗生产环境，应迁移到受管 PostgreSQL/DM8 和集中密钥、备份、监控体系。

## 2. 参考项目事实基线

- 后端现状：Python、PyQt5、DM8/`dmPython`，目录分为 `ui/controllers/services/dao/core/utils`。
- 已有领域：管理员、医生、患者、诊断报告、SAS/SDS/SCL-90、AI 授权、对话记录、生理数据。
- 已知债务：部分 Controller 直接访问 DAO/SQL；返回结构不统一；AI 授权状态存在语义冲突。
- 前端现状：15 个 Tailwind CDN 静态 HTML 页面，无构建系统、状态管理、`fetch/axios`、WebSocket 或 SSE 接入。

因此，新系统复用领域概念和页面视觉，不把 PyQt Controller 直接暴露给浏览器，也不复制现有状态冲突。

## 3. 目标结构

```text
Browser / V13 Tailwind static pages
               |
               | HTTPS / JSON + SSE
               v
API application
├── auth            登录、会话、RBAC
├── users           患者/医生/管理员档案与分配
├── assessments     量表定义、版本、答卷、计分
├── wellbeing       情绪/睡眠/压力日记与趋势
├── conversations   会话、消息、流式输出
├── safety          风险规则、危机事件、人工处置
├── followups       随访任务与记录
├── resources       心理援助资源配置
└── audit           访问、变更、模型与导出审计
               |
       service / policy layer
       /          |           \
SQLite repo   LLM gateway   notification adapter
     |             |                  |
E: database   external model     configured channels
```

## 4. 代码模块建议

```text
backend/
├── app/
│   ├── main.py
│   ├── api/v1/
│   ├── core/          # config, security, errors, logging
│   ├── domain/        # enums, entities, policies
│   ├── services/      # use cases and transactions
│   ├── repositories/  # persistence interfaces
│   ├── db/            # models, session, migrations
│   ├── agent/         # prompts, tools, safety pipeline
│   └── integrations/  # LLM and notifications
└── tests/
    ├── unit/
    ├── integration/
    └── safety/
```

依赖方向只能从 API/集成层指向用例和领域层；领域层不得依赖 Web、数据库或模型 SDK。所有浏览器和智能体工具调用复用同一 Service，避免两套业务规则。

## 5. 部署与 E 盘布局

推荐固定数据根目录：

```text
E:\05_数据库与SQL\mental_health_assistant\
├── data\mental_health.db
├── data\mental_health.db-wal
├── data\mental_health.db-shm
├── backups\
├── exports\
└── quarantine\
```

约束：

- 数据根目录通过配置注入，但生产配置必须解析为 E 盘上述目录。
- 启动时校验盘符、目录、写权限、可用空间和数据库完整性；失败即拒绝写入。
- 禁止自动创建系统盘备用数据库，避免数据分叉和敏感数据泄漏。
- 移动硬盘拔出、I/O 错误或剩余空间低于阈值时，停止新写事务并显示明确告警。
- 数据库文件、WAL 和 SHM 必须同目录；复制备份前执行受控 checkpoint/在线备份。
- E 盘建议启用 BitLocker To Go；字段加密密钥不得保存在同一数据库或 E 盘明文配置中。
- 备份不能只保存在同一物理硬盘；正式使用前必须确定第二备份介质或受控备份位置。

## 6. 核心数据模型

| 聚合 | 主要表 | 关键关系/约束 |
|---|---|---|
| 身份 | `users`, `patient_profiles`, `clinician_profiles`, `care_assignments` | `users.role` 统一角色；分配关系有有效期 |
| 同意 | `consent_records` | 记录用途、文本版本、同意/撤回时间 |
| 量表 | `assessment_definitions`, `assessment_versions`, `assessment_items` | 发布版本不可原地修改 |
| 答卷 | `assessment_sessions`, `assessment_answers`, `assessment_scores` | 答案引用题目版本；得分保存算法版本 |
| 日记 | `wellbeing_entries` | 每用户、日期、类型建立唯一或业务索引 |
| 对话 | `conversations`, `messages`, `model_runs` | 消息与模型运行分离，保存模型/提示词版本 |
| 安全 | `risk_events`, `risk_evidence`, `risk_actions` | 风险事件只追加处置历史，不覆盖审计 |
| 随访 | `followup_tasks`, `followup_notes` | 任务状态变更保留操作者 |
| 资源 | `support_resources` | 区域、有效期、验证时间可配置 |
| 审计 | `audit_events` | 追加写；不保存密码、token 或无关正文 |

主键使用 UUIDv7/UUID；数据库时间统一保存 UTC，API 使用带时区的 ISO 8601，默认展示时区 `Asia/Shanghai`。敏感自由文本字段应做应用层加密或最小化保存。

## 7. 关键架构规则

### 7.1 量表与风险

- 计分器是纯函数：`answers + assessment_version + scoring_rule_version -> scores`。
- 大模型不能参与原始得分计算，也不能覆盖规则引擎风险等级。
- 风险证据分为量表题项、文本规则、模型辅助信号和人工判断，并标记来源与版本。
- 高风险规则必须在模型不可用时独立运行并返回危机支持卡。

### 7.2 智能对话

```text
input validation
-> deterministic crisis rules
-> authorization and consent check
-> minimum-context retrieval
-> LLM call
-> output safety validation
-> persist result/model metadata
-> stream to client
```

命中危机规则时先产生安全响应和风险事件，再决定是否继续受限模型生成。模型超时则返回模板化支持信息，不伪造模型结果。

### 7.3 权限与隐私

- 患者范围：`subject_user_id == session.user_id`。
- 医生范围：存在有效 `care_assignment` 或经审计的临时授权。
- 管理员范围：管理元数据；读取对话正文需要额外权限和理由。
- 所有资源查询在 Repository 层强制加入主体范围，不能只依赖前端隐藏。
- 外部模型请求默认去标识化，不发送姓名、证件号、手机号、精确地址。

## 8. 信任边界

| 边界 | 主要风险 | 控制 |
|---|---|---|
| 浏览器 -> API | 伪造身份、越权、注入 | 会话认证、RBAC、输入校验、CSRF/CORS 策略 |
| API -> E 盘数据库 | 丢盘、拔盘、损坏、窃取 | 硬失败、事务、完整性检查、加密、备份恢复 |
| API -> 外部模型 | 敏感数据泄漏、幻觉 | 最小化、脱敏、供应商策略、输出校验、人工复核 |
| 风险引擎 -> 通知通道 | 误报、未送达 | 明确回执、重试上限、人工队列、审计 |
| 管理员/医生 -> 导出 | 批量泄漏 | 最小字段、理由、权限、审计、文件过期清理策略 |

## 9. 故障策略

| 故障 | 系统行为 |
|---|---|
| E 盘未挂载 | API 启动失败或进入明确只读维护态；不创建替代库 |
| SQLite 锁/损坏 | 停止写入、保留诊断信息、通知管理员、从验证备份恢复 |
| 外部模型不可用 | 量表、规则和危机卡继续可用；普通聊天返回可重试提示 |
| SSE 中断 | 客户端凭事件 ID 重连；断开订阅不改变任务状态，取消为 `CANCELLED`，超时/执行中断为 `FAILED`，未完成内容不得标记 `SUCCEEDED` |
| 通知失败 | 风险事件仍保留在高优先级队列，显示未送达，不声称已通知 |

## 10. 从参考系统迁移

1. 固化现有表字段、状态值、编码和有效量表题目来源。
2. 建立新库和迁移脚本；先迁移用户/医生/患者，再迁移量表、报告、授权和对话。
3. 将 `empiId` 等旧字段映射为新 schema，并保留 `legacy_id` 追溯。
4. 对授权状态 `0..4` 做显式映射，禁止直接沿用冲突语义。
5. 对迁移数量、外键、得分和抽样记录进行校验，生成不可修改的迁移报告。
6. 迁移完成前，旧 DM8 与新 SQLite 不做双向写入。

## 11. 架构验收

- 模块依赖、数据归属和事务边界可由代码结构验证。
- 拔出 E 盘模拟测试不会在其他盘生成数据库。
- 相同量表输入可重复得到相同结果，且保留规则版本。
- 高风险流程在断网/模型故障时仍能显示危机卡并创建本地风险事件。
- 患者、非负责医生和普通管理员的越权测试全部失败并形成审计。

## 12. 患者当前页助手

```text
患者页面 -> PageAssistantAgent -> 规则前置层
                                ├─ 危机命中 -> 固定现实求助渠道
                                ├─ 正式就诊 -> Care Navigation Repository -> SQLite
                                ├─ 跨页问题 -> 页面路由提示
                                └─ 当前页问题 -> BaseLLM -> 输出边界
```

- `BaseLLM` 是可注入端口；未配置模型时使用明确的规则降级，不伪装成真实诊疗模型。
- 年龄由服务端根据 `person_profiles.birth_date` 和当前日期计算，前端不得上传或覆盖年龄组。
- `doctor_availability` 是医生状态唯一事实源；`clinical_visit_summaries` 只提供既往接诊关系，`consultation_queue` 提供实时队列。
- 普通页面问答最多调用一次模型；危机和诊疗导航均不依赖模型生成。
- 模型提示仅包含当前页能力和年龄组，不包含姓名、证件、联系方式及默认病历正文。

### 12.1 跨页记忆与介绍限次

- `assistant_sessions` 由服务端生成并绑定患者；客户端保存的 ID 不是授权凭证。
- `assistant_messages` 仅保存用户主动输入和助手回答，模型调用时按时间装载最近 12 条；页面介绍不写入消息历史，避免污染上下文。
- `patient_feature_usage` 以患者、页面、功能为联合键。打开事件和使用日志在同一 `BEGIN IMMEDIATE` 事务中更新，保证计数一致。
- 前 8 次打开直接返回 `prompts/page_templates.py` 中的固定介绍，不调用 DeepSeek；第 9 次起停止介绍。
- DeepSeek 适配器只存在于后端，读取环境变量或只读 `.env`；浏览器、数据库和日志均不接触 API Key。

## 13. 预约协商架构

```text
患者预约 -> 资格计数(完成就诊>=10) -> 医生未来两天容量
                                   ├─ 容量内 -> queued
                                   └─ 超额 -> 患者换医生/坚持
                                                   └─ 医生接受/拒绝
                                                           └─ 可选委婉改写
助理工作台 <- 待处理协调元数据                夜班表 <- 每日唯一约束
```

- 资格、容量、人数、队列和状态转换均由 SQLite 事务决定，LLM不参与事实计算。
- `appointment_events` 采用追加写；医生拒绝后才允许调用 LLM 改写通知。
- 助理是独立 `assistant` 角色，只查看协调元数据和排班，不继承管理员或医生临床权限。
- SQLite 仍由单一后端进程拥有；多浏览器会话不能直接连接 E 盘。

## 14. 角色化工作助手

```text
医生/助理浏览器 -> 角色助手 API -> 页面与角色策略 -> 只读 Tool Registry
                                                  ├─ 授权患者摘要
                                                  ├─ 本人/公开工作安排
                                                  ├─ 预约与夜班元数据
                                                  └─ 库存摘要（待数据源）
                                      -> DeepSeek -> 输出校验 -> 浏览器
```

- Tool Registry 根据服务端会话角色建立，浏览器传入的角色、患者 ID 和工具名均不可信。
- 医生患者查询必须附加有效负责关系；助理只能获得协调所需最小字段。
- 药物库存工具只返回库存事实，不能提供剂量、适应症、替代药或处方建议。
- 所有工具调用写入审计，至少记录操作者、工具名、过滤范围、结果数量、状态和时间，不记录 API Key。
- 当前仅完成 DeepSeek 基础适配器，医生/助理角色 Tool Registry 和库存数据源仍待实现。
