# v1.0.0 Frontend

该目录由 FastAPI 同源托管，前端只访问 `/api/v1`，不直连数据库或 DeepSeek。

共享运行时：

- `shared/api.js`：Cookie/CSRF、统一 API 和会话。
- `shared/auth-pages.js`：登录、锁定提示和患者/医生注册。
- `shared/role-app.js`：五角色守卫、真实业务工作区和常驻助手。
- `shared/app.css`：助手、提示和移动端样式。

入口：`index.html`。角色页面必须通过后端服务打开，不能用 `file://` 直接运行。

这是 V13 版本的前端起点，用 Tailwind CSS 替代原 PyQt 登录界面。

## 当前内容

- `index.html`：登录页，包含身份类型、账号、密码、记住我、忘记密码、注册入口。
- `register.html`：注册页，包含真实姓名、联系方式、密码确认、协议勾选、登录入口。
- `admin/index.html`：管理员控制台主界面，包含侧边导航、顶部栏、统计卡片和内容占位区。
- `admin/patients.html`：管理员患者管理界面，包含搜索筛选、添加患者、患者表格和分页。
- `admin/doctors.html`：管理员医生管理界面，包含科室筛选、状态筛选、新增医生、医生表格和分页。
- `admin/registration-requests.html`：管理员注册申请处理界面，包含角色筛选、审批状态筛选、批量通过/驳回、申请表格和分页。
- `admin/data-import.html`：管理员数据导入界面，包含导入目标、处理策略、文件上传区、模板下载、导入记录表。
- 当前是静态页面，尚未接入后端登录接口。

## 后续迁移建议

1. 将登录接口从 `core/login_system.py` 中拆出为可复用服务。
2. 为管理员、医生、患者分别建立 Web 页面。
3. 将 PyQt UI 中直接依赖的 Controller 调用改造成 HTTP API 或本地 WebView 桥接。
4. 统一使用 `common/schema.py` 中的数据契约。
