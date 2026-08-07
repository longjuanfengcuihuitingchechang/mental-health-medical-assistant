# 心理健康专项智能医疗助手：接口文档

## 1. 约定

- Base URL：`/api/v1`
- 认证：服务端会话 Cookie；除登录、健康检查和公开资源外均需认证。
- Content-Type：`application/json; charset=utf-8`
- 时间：ISO 8601 带时区，例如 `2026-08-06T10:30:00+08:00`。
- 请求追踪：客户端可传 `X-Request-ID`，服务端始终返回最终请求 ID。
- 写入幂等：创建类请求传 `Idempotency-Key`。

统一成功响应：

```json
{
  "data": {},
  "meta": {"request_id": "req_01..."}
}
```

统一错误响应：

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "请求参数不正确",
    "details": [{"field": "answers", "reason": "missing_item"}],
    "request_id": "req_01..."
  }
}
```

列表响应：

```json
{
  "data": [],
  "page": {"next_cursor": null, "has_more": false},
  "meta": {"request_id": "req_01..."}
}
```

## 2. 认证与会话

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| POST | `/auth/login` | 公开 | 登录并设置会话 Cookie |
| POST | `/auth/logout` | 已登录 | 注销当前会话 |
| GET | `/auth/session` | 已登录 | 获取当前身份、角色和权限 |
| POST | `/auth/password/reset-requests` | 公开 | 发起密码重置，不暴露账号存在性 |
| POST | `/auth/registrations` | 公开 | 患者注册或提交医生注册申请 |
| GET | `/admin/registration-requests` | 管理员 | 查询医生注册申请 |
| POST | `/admin/registration-requests/{id}/review` | 管理员 | 批准或拒绝医生注册 |

登录请求：

```json
{"role": "patient", "login_identifier": "P001、手机号或邮箱", "password": "********"}
```

注册请求：

```json
{
  "role": "doctor",
  "password": "用户设置的密码",
  "display_name": "张某",
  "id_card": "身份证号",
  "phone": "手机号",
  "email": "邮箱",
  "department": "心理科",
  "professional_title": "医师"
}
```

患者注册成功后返回系统生成的 `Pnnn` 并立即激活；医生返回 `Dnnn` 和 `pending_approval`，审批前不得登录。拒绝审批必须填写原因。

会话响应：

```json
{
  "data": {
    "user_id": "usr_01...",
    "role": "patient",
    "display_name": "王某",
    "permissions": ["profile:read:self", "assessment:submit:self"],
    "expires_at": "2026-08-06T18:30:00+08:00"
  },
  "meta": {"request_id": "req_01..."}
}
```

## 3. 档案与同意

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| GET | `/me` | 已登录 | 当前用户基本资料 |
| PATCH | `/me` | 已登录 | 更新允许自助维护的字段 |
| GET | `/me/consents` | 已登录 | 查看本人同意记录 |
| POST | `/me/consents` | 已登录 | 对特定用途给出单独同意 |
| POST | `/me/consents/{consent_id}/withdraw` | 已登录 | 撤回同意并触发后续限制 |

同意请求：

```json
{
  "purpose": "AI_ASSISTANT",
  "notice_version": "privacy-ai-1.0",
  "granted": true
}
```

## 4. 管理员用户接口

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| GET | `/admin/users` | 管理员 | 按角色/状态/关键词查询用户 |
| POST | `/admin/users` | 管理员 | 创建用户 |
| GET | `/admin/users/{user_id}` | 管理员 | 查看账号与最小必要档案 |
| PATCH | `/admin/users/{user_id}` | 管理员 | 更新状态或角色允许字段 |
| POST | `/admin/care-assignments` | 管理员 | 分配医生与患者 |
| PATCH | `/admin/care-assignments/{id}` | 管理员 | 结束或变更分配 |

禁止用 DELETE 直接删除临床/心理记录。账号停用使用状态变更并保留审计。

## 5. 量表接口

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| GET | `/assessments` | 患者/医生 | 获取已发布量表列表 |
| GET | `/assessments/{code}/versions/{version}` | 患者/医生 | 获取指定版本题目与选项 |
| POST | `/assessment-sessions` | 患者/医生 | 创建答题会话 |
| PUT | `/assessment-sessions/{id}/answers` | 会话主体 | 暂存答案 |
| POST | `/assessment-sessions/{id}/submit` | 会话主体 | 校验、计分并完成提交 |
| GET | `/assessment-sessions/{id}/result` | 本人/负责医生 | 查看得分、解释和风险摘要 |
| GET | `/patients/{patient_id}/assessment-results` | 负责医生 | 查看患者历史和趋势 |

创建会话：

```json
{
  "assessment_code": "SDS",
  "assessment_version": "legacy-reviewed-1.0",
  "subject_user_id": "usr_patient_01"
}
```

保存答案：

```json
{
  "answers": [
    {"item_id": "item_01", "value": 2},
    {"item_id": "item_02", "value": 1}
  ],
  "version": 3
}
```

结果响应：

```json
{
  "data": {
    "session_id": "asmt_01...",
    "assessment": {"code": "SDS", "version": "legacy-reviewed-1.0"},
    "status": "completed",
    "scores": [{"name": "total", "raw": 40, "standardized": 50}],
    "interpretation": {"level": "review_recommended", "text": "结果仅用于筛查，建议由专业人员结合实际情况评估。"},
    "risk": {"level": "medium", "event_id": "risk_01..."},
    "completed_at": "2026-08-06T10:30:00+08:00"
  },
  "meta": {"request_id": "req_01..."}
}
```

客户端不得自行提交 `raw_score` 或 `risk_level` 作为可信结果；服务端依据答案和版本计算。

## 6. 情绪健康日记

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| POST | `/wellbeing-entries` | 患者本人 | 创建情绪/睡眠/压力记录 |
| GET | `/wellbeing-entries` | 患者本人 | 按日期范围查询 |
| PATCH | `/wellbeing-entries/{id}` | 患者本人 | 更新本人记录 |
| GET | `/wellbeing-trends` | 本人/负责医生 | 获取 7/30 天聚合趋势 |

```json
{
  "recorded_on": "2026-08-06",
  "mood": 3,
  "stress": 4,
  "sleep_hours": 6.5,
  "sleep_quality": 2,
  "note": "今天压力较大"
}
```

量值范围由服务端 schema 返回并校验，前端不硬编码为临床结论。

## 7. 对话与智能助手

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| POST | `/conversations` | 患者/医生 | 新建会话 |
| GET | `/conversations` | 会话参与者 | 会话列表 |
| GET | `/conversations/{id}/messages` | 会话参与者/授权医生 | 消息历史 |
| POST | `/conversations/{id}/messages` | 会话参与者 | 非流式发送消息 |
| POST | `/conversations/{id}/messages/stream` | 会话参与者 | SSE 流式发送消息 |
| POST | `/conversations/{id}/close` | 会话参与者 | 关闭会话 |

请求：

```json
{
  "client_message_id": "cm_01...",
  "content": "最近一直睡不好，也很焦虑",
  "consent_id": "consent_01..."
}
```

SSE 事件：

```text
id: evt_01
event: message.accepted
data: {"message_id":"msg_user_01","risk_check":"pending"}

id: evt_02
event: safety.result
data: {"risk_level":"medium","risk_event_id":"risk_01"}

id: evt_03
event: message.delta
data: {"message_id":"msg_ai_01","delta":"听起来这段时间很辛苦。"}

id: evt_04
event: message.completed
data: {"message_id":"msg_ai_01","finish_reason":"stop"}
```

高风险时服务器可以先发：

```text
event: crisis.support_required
data: {"risk_event_id":"risk_01","resource_codes":["CN_12356","CN_120","CN_110"],"model_continues":false}
```

不得在 SSE 中发送内部规则全文、模型密钥或其他患者数据。

## 8. 风险事件与处置

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| GET | `/risk-events` | 医生/管理员安全角色 | 按等级、状态、患者筛选 |
| GET | `/risk-events/{id}` | 负责医生/安全角色 | 查看证据摘要和处置历史 |
| POST | `/risk-events/{id}/actions` | 负责医生/安全角色 | 追加处置动作 |
| POST | `/risk-events/{id}/assign` | 安全角色 | 指派负责人 |
| GET | `/risk-events/{id}/audit` | 审计权限 | 查看事件审计链 |

处置请求：

```json
{
  "action": "CONTACT_ATTEMPTED",
  "note": "已按登记电话尝试联系，未接通",
  "next_status": "in_progress",
  "occurred_at": "2026-08-06T10:35:00+08:00",
  "version": 2
}
```

允许动作：`ACKNOWLEDGED`、`CONTACT_ATTEMPTED`、`CONTACT_CONFIRMED`、`REFERRED`、`FALSE_POSITIVE`、`CLOSED`。关闭必须有理由；模型账号无关闭权限。

## 9. 随访和支持资源

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| POST | `/followups` | 医生 | 创建随访任务 |
| GET | `/followups` | 本人/负责医生 | 查询随访 |
| PATCH | `/followups/{id}` | 负责医生 | 更新任务状态与时间 |
| POST | `/followups/{id}/notes` | 负责医生 | 追加随访记录 |
| GET | `/support-resources` | 已登录/危机公开页 | 获取当前地区有效资源 |
| POST | `/admin/support-resources` | 管理员 | 创建资源 |
| PATCH | `/admin/support-resources/{id}` | 管理员 | 更新、验证或停用资源 |

公开资源响应不得包含内部值班人员私人联系方式。`12356` 资源必须包含来源、适用地区、最后核验日期和是否 24 小时服务等字段，不能把未核验属性写死。

## 10. 管理与审计

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| GET | `/admin/audit-events` | 审计权限 | 按操作者、对象、动作和时间查询 |
| GET | `/admin/system/database-status` | 管理员 | E 盘、空间、连接、WAL 和备份状态 |
| POST | `/admin/system/backups` | 数据管理员 | 创建受控备份任务 |
| GET | `/admin/system/backups` | 数据管理员 | 查看备份及校验结果 |
| POST | `/admin/assessment-versions` | 量表管理员 | 创建草稿版本 |
| POST | `/admin/assessment-versions/{id}/publish` | 量表管理员+审批 | 发布不可变版本 |

数据库状态示例：

```json
{
  "data": {
    "state": "healthy",
    "required_drive": "E:",
    "database_path_masked": "E:\\05_数据库与SQL\\mental_health_assistant\\data\\mental_health.db",
    "free_mb": 102400,
    "journal_mode": "wal",
    "integrity_check": "ok",
    "last_verified_backup_at": "2026-08-05T02:00:00+08:00"
  },
  "meta": {"request_id": "req_01..."}
}
```

## 11. 健康检查

| 方法 | 路径 | 认证 | 说明 |
|---|---|---|---|
| GET | `/health/live` | 无 | 进程存活，不暴露内部细节 |
| GET | `/health/ready` | 内部/管理员 | 校验 E 盘数据库与必要服务 |

`ready` 在 E 盘缺失、数据库不可写或迁移不匹配时返回 503；外部模型不可用只标记 `degraded`，不得使危机规则服务失效。

## 12. 前端页面到接口映射

| 现有页面 | 目标接口 |
|---|---|
| `index.html`, `register.html` | `/auth/*`, `/me/consents` |
| `admin/index.html` | `/admin/system/*`, `/risk-events`, `/admin/audit-events` |
| `admin/patients.html`, `admin/doctors.html` | `/admin/users`, `/admin/care-assignments` |
| `admin/registration-requests.html` | 后续 `/admin/registration-requests` |
| `admin/data-import.html` | 后续受控导入任务接口，不允许浏览器直写数据库 |
| `doctor/index.html`, `doctor/my-patients.html` | `/patients/*`, `/risk-events`, `/followups` |
| `doctor/online-consultation.html` | `/conversations/*` |
| `doctor/schedule-appointments.html` | `/followups`，预约接口待后续范围确认 |
| `doctor/prescriptions-records.html` | 医生记录接口待确认；AI 不提供处方接口 |
| `doctor/profile.html` | `/me` |
| `patient/index.html` | `/me`, `/wellbeing-trends`, `/assessment-sessions/*`, `/followups` |
| `patient/online-consultation.html` | `/conversations/*`, `/support-resources` |
| `patient/vital-signs-checkin.html` | `/wellbeing-entries`；生理体征独立接口待确认 |

## 13. 兼容与待定

- 参考系统目前没有 HTTP API，因此本文定义的是目标契约，不是已有可调用端点。
- 旧 `empiId`、`patientName` 等字段只在迁移适配层存在；HTTP API 统一 `snake_case`。
- 注册审批、预约、生理体征和医生记录的详细端点需在 MVP 边界确认后补充。
- OpenAPI 文档应由代码生成，并在 CI 中与本文做契约测试；本文与实现冲突时必须更新版本和变更记录。

## 14. 患者当前页助手与诊疗导航

以下为目标 HTTP 契约；当前已实现领域 Agent、Repository 和 SQLite 表，HTTP 路由仍待接入。

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| POST | `/patient/page-assistant/respond` | 患者本人 | 当前页进入说明、当前页问答、危机支持或诊疗导航 |
| GET | `/patient/page-assistant/sessions/{session_id}/messages` | 患者本人 | 恢复同一助手会话的可见消息 |
| GET | `/patient/care-navigation/doctors` | 患者本人 | 查询医生状态、既往接诊关系和本人排队位置 |

请求：

```json
{
  "page": "overview",
  "feature_key": "page",
  "event": "message",
  "session_id": "assistant_session_uuid",
  "message": "我要就诊"
}
```

`page` 允许 `overview`、`support`、`assessments`、`wellbeing`、`resources`、`care`。`event` 允许 `page_open`、`feature_open`、`message`。首次请求省略 `session_id`，后续跨页请求回传服务端生成的值。页面/功能打开时 `message` 为空；消息事件必须包含文本。服务端从认证会话取得患者 ID，不接受浏览器传入的 `patient_user_id`。

诊疗导航响应：

```json
{
  "data": {
    "response_type": "care_navigation",
    "page": "overview",
    "answer": "已进入患者诊疗导航，请选择医生。",
    "age_group": "adult",
    "suggested_page": "care",
    "requires_guardian_support": false,
    "doctors": [
      {
        "doctor_user_id": "doctor_uuid",
        "display_name": "李医生",
        "department": "心理科",
        "professional_title": "医师",
        "availability": "working",
        "availability_label": "工作中",
        "queue_length": 2,
        "patient_queue_position": null,
        "is_previous_doctor": true,
        "last_visit_at": "2026-07-01T08:00:00+08:00",
        "expected_available_at": null,
        "leave_remaining_days": null
      }
    ],
    "crisis_contacts": [],
    "session_id": "assistant_session_uuid",
    "feature_key": "page",
    "usage_count": 3,
    "introduction_suppressed": false
  },
  "meta": {"request_id": "req_01..."}
}
```

约束：

- 医生状态缺失时必须返回 `unknown/状态待确认`，不得由 LLM 猜测为在岗。
- 既往就诊只用于标记和排序原接诊医生；未经单独授权，不把病历正文发送给外部模型。
- 未满 18 周岁且无有效监护支持记录时，`requires_guardian_support=true`；不能把该字段当作紧急求助的阻断条件。
- 危机词命中时 `response_type=crisis_support`，直接返回 `12356`、`110`、`120` 等现实渠道，绕过普通 LLM 回答。
- LLM 不可用时普通问答可返回 503/降级文本，但页面介绍、医生真实状态和危机渠道仍可用。
- 同一患者、页面和功能前 8 次 `page_open/feature_open` 返回模板介绍；第 9 次起返回 `response_type=introduction_suppressed`、空 `answer` 和 `introduction_suppressed=true`。
- `message` 事件只写使用日志，不增加功能打开次数；助手只加载同一患者同一 `session_id` 最近 12 条受控消息。

功能白名单：

| 页面 | `feature_key` |
|---|---|
| `overview` | `page`, `mood_checkin`, `latest_screening`, `trend`, `followups`, `crisis_resources` |
| `support` | `page`, `ask_question`, `formal_care` |
| `assessments` | `page`, `available_scales`, `continue_assessment`, `results` |
| `wellbeing` | `page`, `new_entry`, `history`, `trend` |
| `resources` | `page`, `followups`, `professional_help`, `privacy` |
| `care` | `page`, `doctor_selection`, `previous_doctor`, `queue_status` |

## 15. 预约、超额审批、夜班和助理

以下为目标 HTTP 契约；当前领域 Agent 和 SQLite 数据层已实现，路由待接入。

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| PUT | `/doctors/me/capacities/{date}` | 医生本人 | 设置未来第 1、2 天接诊容量 |
| POST | `/patient/appointments` | 已完成就诊≥10次的患者 | 指定医生预约并进入队列 |
| POST | `/patient/appointments/{id}/decision` | 预约患者 | 选择换医生或坚持请求 |
| GET | `/doctor/appointments/pending-decisions` | 对应医生 | 获取医生端超额预约弹窗 |
| POST | `/doctor/appointments/{id}/decision` | 对应医生 | 接受或拒绝超额预约 |
| GET | `/assistant/appointments/pending-decisions` | 助理/管理员 | 查看三方协调队列 |
| POST | `/night-shifts` | 助理/管理员 | 安排当日唯一夜班医生 |

创建预约请求：

```json
{"doctor_user_id":"doctor_uuid","appointment_date":"2026-08-07"}
```

超过容量时返回 `awaiting_patient_decision`、当前 `appointment_count`、`capacity` 和 `queue_position`。患者坚持使用：

```json
{"decision":"continue_request"}
```

医生拒绝时必须选择告知方式：

```json
{"decision":"decline","communication_mode":"gentle"}
```

`direct` 使用固定直接文案；`gentle` 允许 LLM 在不改变事实的前提下改写语气。LLM 输出只写 `patient_message`，不改变预约状态。所有状态变化追加到 `appointment_events`。

## 16. 医生与助理工作助手

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| POST | `/doctor/work-assistant/respond` | 医生 | 当前页说明及本人工作数据只读查询 |
| POST | `/assistant/work-assistant/respond` | 助理 | 当前页说明及协调数据只读查询 |
| POST | `/doctor/work-assistant/tasks` | 医生 | 创建可取消、可流式读取的异步任务 |
| POST | `/assistant/work-assistant/tasks` | 助理 | 创建可取消、可流式读取的异步任务 |
| GET | `/agent-tasks/{task_id}` | 任务本人 | 查询状态与完整最终结果 |
| GET | `/agent-tasks/{task_id}/events` | 任务本人 | SSE 增量及断点续传 |
| POST | `/agent-tasks/{task_id}/cancel` | 任务本人 | 幂等取消 |
| GET | `/doctor/work-assistant/sessions/{id}/messages` | 会话医生 | 恢复医生助手消息 |
| GET | `/assistant/work-assistant/sessions/{id}/messages` | 会话助理 | 恢复助理助手消息 |
| GET | `/inventory/medicines` | 医生/助理 | 只读药物库存摘要，数据源待接入 |

请求沿用 `page`、`feature_key`、`event`、`session_id`、`message`。服务端依据认证会话选择角色工具白名单，不接受客户端传入角色或任意工具名。

医生工具：`get_my_schedule`、`get_my_capacity`、`get_pending_overcapacity_requests`、`search_my_patient_visible_summary`、`search_medicine_inventory`。

助理工具：`get_coordination_queue`、`get_doctor_public_schedule`、`get_night_shift_gaps`、`get_appointment_counts`、`get_patient_coordination_summary`、`search_medicine_inventory`。

所有工具必须只读。模型返回的导航建议不能直接执行预约决定、排班、风险关闭、病历修改或库存变更。

患者流式入口为 `POST /patient/page-assistant/tasks`。危机规则在创建任务前同步执行，命中时不创建任务、不调用模型。SSE 使用任务内单调事件 ID，支持 `Last-Event-ID`/`after`；只有完整输出通过校验并持久化后才能发送 `task.completed` 并写入 `SUCCEEDED`。
