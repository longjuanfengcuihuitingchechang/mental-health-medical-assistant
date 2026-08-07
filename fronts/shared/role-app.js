(() => {
  const api = window.MHApi;
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const roleFromPath = () => location.pathname.match(/\/(patient|doctor|assistant|admin)\//)?.[1];
  const homes = { patient: "../patient/index.html", doctor: "../doctor/index.html", assistant: "../assistant/index.html", admin: "../admin/index.html", super_admin: "../admin/index.html" };
  const navs = {
    patient: [["概览", "index.html"], ["心理诊疗", "online-consultation.html"], ["健康记录", "vital-signs-checkin.html"]],
    doctor: [["工作台", "index.html"], ["患者队列", "my-patients.html"], ["排班预约", "schedule-appointments.html"], ["在线诊疗", "online-consultation.html"]],
    assistant: [["协调工作台", "index.html"]],
    admin: [["控制台", "index.html"], ["患者目录", "patients.html"], ["医生目录", "doctors.html"], ["注册审批", "registration-requests.html"]],
  };

  function toast(message, kind = "info") {
    const node = document.createElement("div");
    node.className = `mh-toast ${kind}`;
    node.textContent = message;
    document.body.append(node);
    setTimeout(() => node.remove(), 4500);
  }

  function shell(session) {
    const navRole = session.role === "super_admin" ? "admin" : session.role;
    document.body.className = "min-h-screen bg-slate-50 text-slate-900";
    document.body.innerHTML = `<div class="min-h-screen md:flex">
      <aside class="bg-slate-900 p-5 text-white md:min-h-screen md:w-64">
        <h1 class="text-xl font-bold">心理健康医疗助手</h1><p class="mt-1 text-xs text-slate-400">v1.0.0 研究原型</p>
        <nav class="mt-8 space-y-2">${navs[navRole].map(([label, url]) => `<a href="${url}" class="block rounded-lg px-4 py-3 hover:bg-slate-700">${label}</a>`).join("")}</nav>
        <button id="logoutButton" class="mt-8 w-full rounded-lg border border-slate-600 px-4 py-2 text-sm">退出登录</button>
      </aside>
      <main class="min-w-0 flex-1 p-4 md:p-8"><header class="mb-6 flex flex-wrap items-center justify-between gap-3"><div><h2 id="pageTitle" class="text-2xl font-bold">工作区</h2><p class="text-sm text-slate-500">${esc(session.display_name)} · ${esc(session.role)}</p></div><span class="rounded-full bg-emerald-100 px-3 py-1 text-xs text-emerald-700">E 盘数据库已连接</span></header><section id="workspace"></section></main>
    </div>`;
    document.querySelector("#logoutButton").onclick = async () => { try { await api.logout(); } finally { location.href = "../index.html"; } };
  }

  const card = (title, body) => `<article class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><h3 class="mb-4 text-lg font-bold">${title}</h3>${body}</article>`;

  async function patientPage() {
    const file = location.pathname.split("/").pop();
    const isCare = file === "online-consultation.html";
    const title = isCare ? "心理诊疗与预约" : file === "vital-signs-checkin.html" ? "健康记录" : "患者概览";
    document.querySelector("#pageTitle").textContent = title;
    document.querySelector("#workspace").innerHTML = isCare
      ? `<div id="doctorOptions" class="grid gap-4"><div class="mh-spinner"></div></div>`
      : card("当前功能", `<p class="text-slate-600">本页仅显示已接入的真实功能。心理咨询和医生预约请进入“心理诊疗”。</p><div class="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">本系统不提供自动诊断、处方或紧急救援。</div>`);
    installAssistant("patient", isCare ? "care" : "overview", isCare ? "doctor_selection" : "page", data => {
      if (isCare && data.doctors) renderDoctors(data.doctors);
    });
  }

  function renderDoctors(doctors) {
    const host = document.querySelector("#doctorOptions");
    host.innerHTML = doctors.length ? doctors.map(d => card(esc(d.display_name), `
      <p class="text-sm text-slate-500">${esc(d.department || "科室待确认")} · ${esc(d.professional_title || "")}</p>
      <p class="mt-2 text-sm">状态：${esc(d.availability_label)}；预约人数：${d.appointment_count ?? d.queue_length ?? 0}</p>
      ${d.leave_remaining_days != null ? `<p class="text-sm text-amber-700">预计还需休假 ${d.leave_remaining_days} 天</p>` : ""}
      <div class="mt-4 flex flex-wrap gap-2"><input type="date" class="appointment-date rounded-lg border px-3 py-2" data-doctor="${esc(d.doctor_user_id)}"><button data-book="${esc(d.doctor_user_id)}" class="rounded-lg bg-emerald-600 px-4 py-2 text-white">预约</button></div>`)).join("")
      : card("暂无可选医生", "<p class='text-slate-500'>数据库中暂时没有可展示的医生。</p>");
    host.querySelectorAll("[data-book]").forEach(button => button.onclick = async () => {
      const input = host.querySelector(`input[data-doctor="${CSS.escape(button.dataset.book)}"]`);
      if (!input.value) return toast("请选择预约日期", "error");
      button.disabled = true;
      try {
        const data = await api.request("/patient/appointments", { method: "POST", body: JSON.stringify({ doctor_user_id: button.dataset.book, appointment_date: input.value }) });
        toast(data.message, "success");
        if (data.status === "awaiting_patient_decision") showPatientDecision(data.appointment_id);
      } catch (error) { toast(error.message, "error"); } finally { button.disabled = false; }
    });
  }

  function showPatientDecision(id) {
    const node = document.createElement("div");
    node.className = "fixed inset-0 z-50 grid place-items-center bg-slate-900/50 p-4";
    node.innerHTML = `<div class="max-w-md rounded-xl bg-white p-6"><h3 class="font-bold">医生预约已超过容量</h3><p class="my-3 text-sm">可以更换医生，也可以继续提交给医生确认。</p><div class="flex gap-2"><button data-choice="switch_doctor" class="rounded border px-3 py-2">更换医生</button><button data-choice="continue_request" class="rounded bg-emerald-600 px-3 py-2 text-white">仍然预约</button></div></div>`;
    document.body.append(node);
    node.querySelectorAll("[data-choice]").forEach(button => button.onclick = async () => {
      try {
        const data = await api.request(`/patient/appointments/${id}/decision`, { method: "POST", body: JSON.stringify({ decision: button.dataset.choice }) });
        toast(data.patient_message, "success");
        node.remove();
      } catch (error) { toast(error.message, "error"); }
    });
  }

  async function doctorPage() {
    document.querySelector("#pageTitle").textContent = "医生工作台";
    document.querySelector("#workspace").innerHTML = `<div class="grid gap-5 lg:grid-cols-2">${card("未来两天接诊容量", `<form id="capacityForm" class="space-y-3"><input id="capacityDate" type="date" required class="w-full rounded-lg border px-3 py-2"><input id="capacityValue" type="number" min="0" max="1000" required placeholder="接诊人数" class="w-full rounded-lg border px-3 py-2"><button class="rounded-lg bg-teal-600 px-4 py-2 text-white">保存容量</button></form>`)}${card("待确认的超额预约", `<div id="pendingAppointments"><span class="mh-spinner"></span></div>`)}</div>`;
    document.querySelector("#capacityForm").onsubmit = async event => {
      event.preventDefault();
      try {
        const data = await api.request(`/doctors/me/capacities/${document.querySelector("#capacityDate").value}`, { method: "PUT", body: JSON.stringify({ capacity: Number(document.querySelector("#capacityValue").value) }) });
        toast(`已保存容量 ${data.capacity}，当前预约 ${data.appointment_count}`, "success");
      } catch (error) { toast(error.message, "error"); }
    };
    try {
      const items = await api.request("/doctors/me/appointments/pending-decisions");
      const host = document.querySelector("#pendingAppointments");
      host.innerHTML = items.length ? items.map(item => `<div class="mb-3 rounded-lg border p-3"><p>${esc(item.patient_display_name)} · ${esc(item.appointment_date)} · 第 ${item.queue_position} 位</p><div class="mt-2 flex gap-2"><button data-id="${item.appointment_id}" data-decision="accept" class="rounded bg-teal-600 px-3 py-1 text-white">接受</button><button data-id="${item.appointment_id}" data-decision="decline" class="rounded border px-3 py-1">委婉拒绝</button></div></div>`).join("") : "<p class='text-slate-500'>暂无待确认预约。</p>";
      host.querySelectorAll("button[data-decision]").forEach(button => button.onclick = () => doctorDecide(button));
    } catch (error) { toast(error.message, "error"); }
    installAssistant("doctor", "schedule", "daily_queue");
  }

  async function doctorDecide(button) {
    button.disabled = true;
    try {
      const decline = button.dataset.decision === "decline";
      const data = await api.request(`/doctors/me/appointments/${button.dataset.id}/decision`, { method: "POST", body: JSON.stringify({ decision: button.dataset.decision, communication_mode: decline ? "gentle" : null }) });
      toast(data.patient_message, "success");
      button.closest("div.mb-3").remove();
    } catch (error) { toast(error.message, "error"); button.disabled = false; }
  }

  async function assistantPage() {
    document.querySelector("#pageTitle").textContent = "医疗助理协调台";
    document.querySelector("#workspace").innerHTML = card("三方协调队列", `<div id="coordination"><span class="mh-spinner"></span></div>`);
    try {
      const items = await api.request("/assistants/me/coordination-queue");
      document.querySelector("#coordination").innerHTML = items.length ? items.map(item => `<div class="mb-3 rounded-lg border p-3"><b>${esc(item.patient_display_name)}</b> → ${esc(item.doctor_display_name)}<p class="text-sm text-slate-500">${esc(item.appointment_date)} · ${esc(item.status)}</p></div>`).join("") : "<p class='text-slate-500'>当前没有待协调事项。</p>";
    } catch (error) { toast(error.message, "error"); }
    installAssistant("assistant", "coordination", "queue");
  }

  async function adminPage(session) {
    const file = location.pathname.split("/").pop();
    if (file === "registration-requests.html") {
      document.querySelector("#pageTitle").textContent = "医生注册审批";
      document.querySelector("#workspace").innerHTML = card("待审批申请", `<div id="requests"><span class="mh-spinner"></span></div>`);
      await loadRegistrations();
      return;
    }
    const target = file === "doctors.html" ? "doctor" : file === "patients.html" ? "patient" : session.role === "super_admin" ? "admin" : "doctor";
    document.querySelector("#pageTitle").textContent = "人员管理";
    document.querySelector("#workspace").innerHTML = card(`${target} 目录`, `<div id="directory"><span class="mh-spinner"></span></div>`);
    try {
      const data = await api.request(`/admin/directory/${target}`);
      document.querySelector("#directory").innerHTML = data.items.length ? `<div class="overflow-x-auto"><table class="w-full text-left text-sm"><thead><tr><th class="p-2">账号</th><th>姓名</th><th>状态</th><th>黑名单</th><th>在职</th></tr></thead><tbody>${data.items.map(item => `<tr class="border-t"><td class="p-2">${esc(item.account)}</td><td>${esc(item.display_name)}</td><td>${esc(item.account_status)}</td><td>${item.blacklisted ? "是" : "否"}</td><td>${esc(item.employment_status || "-")}</td></tr>`).join("")}</tbody></table></div>` : "<p class='text-slate-500'>没有记录。</p>";
    } catch (error) { toast(error.message, "error"); }
  }

  async function loadRegistrations() {
    try {
      const data = await api.request("/admin/doctor-registrations?status=pending");
      const host = document.querySelector("#requests");
      host.innerHTML = data.items.length ? data.items.map(item => `<div class="mb-3 rounded-lg border p-4"><b>${esc(item.display_name)}</b> · ${esc(item.department)}<p class="text-sm text-slate-500">${esc(item.account)} · ${esc(item.phone_masked)} · ${esc(item.email_masked)}</p><textarea class="mt-2 w-full rounded border p-2" placeholder="拒绝时填写原因"></textarea><div class="mt-2 flex gap-2"><button data-id="${item.registration_request_id}" data-action="approve" class="rounded bg-blue-600 px-3 py-1 text-white">批准</button><button data-id="${item.registration_request_id}" data-action="reject" class="rounded border px-3 py-1">拒绝</button></div></div>`).join("") : "<p class='text-slate-500'>没有待审批申请。</p>";
      host.querySelectorAll("button[data-action]").forEach(button => button.onclick = async () => {
        const note = button.closest("div.mb-3").querySelector("textarea").value.trim();
        try {
          await api.request(`/admin/doctor-registrations/${button.dataset.id}/decision`, { method: "POST", body: JSON.stringify({ action: button.dataset.action, review_note: note || null }) });
          toast("审批已保存", "success");
          button.closest("div.mb-3").remove();
        } catch (error) { toast(error.message, "error"); }
      });
    } catch (error) { toast(error.message, "error"); }
  }

  function installAssistant(role, page, feature, onData) {
    const patient = role === "patient";
    const node = document.createElement("aside");
    node.className = "mh-assistant";
    node.innerHTML = `<header class="flex items-center justify-between bg-slate-800 px-4 py-3 text-white"><b>${patient ? "页面智能助手" : "工作智能助手"}</b><div class="flex items-center gap-2"><button type="button" class="mh-cancel hidden rounded bg-red-700 px-2 py-1 text-xs">停止</button><button type="button" aria-label="折叠助手">−</button></div></header><div class="mh-assistant-body"><div class="mh-stream-status px-4 pt-2 text-xs text-slate-500" aria-live="polite"></div><div class="mh-messages" aria-live="polite"></div><form class="flex gap-2 border-t p-3"><input maxlength="2000" required class="min-w-0 flex-1 rounded-lg border px-3 py-2" placeholder="询问当前页功能"><button class="rounded-lg bg-teal-600 px-4 text-white">发送</button></form></div>`;
    document.body.append(node);
    node.querySelector("button[aria-label='折叠助手']").onclick = () => node.classList.toggle("collapsed");
    const messages = node.querySelector(".mh-messages");
    const status = node.querySelector(".mh-stream-status");
    const form = node.querySelector("form");
    const input = form.querySelector("input");
    const submit = form.querySelector("button");
    const cancel = node.querySelector(".mh-cancel");
    const add = (text, who) => { const item = document.createElement("div"); item.className = `mh-message ${who}`; item.textContent = text; messages.append(item); messages.scrollTop = messages.scrollHeight; return item; };
    const key = `mh_${role}_assistant_session`;
    const taskKey = `mh_${role}_active_task`;
    let sessionId = sessionStorage.getItem(key);
    let source = null;
    let activeTask = null;
    let streamMessage = null;
    const setBusy = busy => { input.disabled = busy; submit.disabled = busy; cancel.disabled = false; cancel.classList.toggle("hidden", !busy); };
    const saveTask = () => activeTask ? sessionStorage.setItem(taskKey, JSON.stringify(activeTask)) : sessionStorage.removeItem(taskKey);
    const finishTask = () => { source?.close(); source = null; activeTask = null; saveTask(); setBusy(false); status.textContent = ""; };
    const handleResponse = data => {
      sessionId = data.assistant_session_id || data.session_id || sessionId;
      if (sessionId) sessionStorage.setItem(key, sessionId);
      if (streamMessage && data.answer) streamMessage.textContent = data.answer;
      else if (data.answer) streamMessage = add(data.answer, "assistant");
      if (data.degraded) add("当前模型不可用，以上为安全降级结果。", "assistant");
      onData?.(data);
    };
    const connect = task => {
      activeTask = task;
      saveTask();
      setBusy(true);
      status.textContent = "正在生成，可安全断线后重连…";
      streamMessage = add("", "assistant");
      const separator = task.stream_url.includes("?") ? "&" : "?";
      source = new EventSource(`${task.stream_url}${separator}after=${task.last_event_id || 0}`);
      const remember = event => { if (event.lastEventId) { activeTask.last_event_id = Number(event.lastEventId); saveTask(); } };
      source.addEventListener("task.started", event => { remember(event); status.textContent = "模型任务正在运行…"; });
      source.addEventListener("message.delta", event => { remember(event); const data = JSON.parse(event.data); streamMessage.textContent += data.text || ""; messages.scrollTop = messages.scrollHeight; });
      source.addEventListener("task.completed", event => { remember(event); const data = JSON.parse(event.data); handleResponse(data.response || {}); finishTask(); });
      source.addEventListener("task.failed", event => { remember(event); const data = JSON.parse(event.data); streamMessage.textContent = data.message || "任务执行失败，未完成内容未保存为成功结果。"; finishTask(); });
      source.addEventListener("task.cancelled", event => { remember(event); streamMessage.textContent = "任务已取消，未完成内容未保存。"; finishTask(); });
      source.onerror = () => { if (activeTask) status.textContent = "连接中断，正在从上次事件继续…"; };
    };
    const send = async (message, event) => {
      try {
        const path = patient ? "/patient/page-assistant/tasks" : `/${role}/work-assistant/tasks`;
        const body = patient ? { page, message, assistant_session_id: sessionId, feature_key: feature, event } : { page, feature_key: feature, message, assistant_session_id: sessionId };
        const data = await api.request(path, { method: "POST", body: JSON.stringify(body) });
        if (data.mode === "synchronous") {
          handleResponse(data.response || {});
          setBusy(false);
          return;
        }
        connect({ task_id: data.task_id, stream_url: data.stream_url, cancel_url: data.cancel_url, last_event_id: 0 });
      } catch (error) { add(error.message, "assistant"); setBusy(false); status.textContent = ""; }
    };
    cancel.onclick = async () => { if (!activeTask) return; cancel.disabled = true; status.textContent = "正在取消…"; try { await api.request(activeTask.cancel_url, { method: "POST" }); } catch (error) { status.textContent = error.message; cancel.disabled = false; } };
    form.onsubmit = event => { event.preventDefault(); const text = input.value.trim(); if (!text || activeTask) return; add(text, "user"); input.value = ""; setBusy(true); send(text, "message"); };
    const stored = sessionStorage.getItem(taskKey);
    if (stored) {
      try { const task = JSON.parse(stored); api.request(`/agent-tasks/${task.task_id}`).then(snapshot => { if (["SUCCEEDED", "FAILED", "CANCELLED"].includes(snapshot.status)) { if (snapshot.status === "SUCCEEDED") handleResponse(snapshot.output || {}); else add(snapshot.status === "CANCELLED" ? "任务已取消。" : "任务执行失败。", "assistant"); activeTask = null; saveTask(); } else connect(task); }).catch(() => { sessionStorage.removeItem(taskKey); setBusy(false); }); } catch { sessionStorage.removeItem(taskKey); }
    } else if (patient) {
      setBusy(true);
      send("", page === "overview" ? "page_open" : "feature_open");
    } else add("可以查询当前工作页相关的真实排班、队列、夜班或库存信息。", "assistant");
  }

  async function boot() {
    const pathRole = roleFromPath();
    if (!pathRole) return;
    try {
      const session = await api.session(true);
      const allowed = pathRole === "admin" ? ["admin", "super_admin"].includes(session.role) : session.role === pathRole;
      if (!allowed) { location.href = homes[session.role] || "../index.html"; return; }
      shell(session);
      if (pathRole === "patient") await patientPage();
      else if (pathRole === "doctor") await doctorPage();
      else if (pathRole === "assistant") await assistantPage();
      else await adminPage(session);
    } catch (error) {
      toast(error.message, "error");
      setTimeout(() => location.href = "../index.html", 1200);
    }
  }

  boot();
})();
