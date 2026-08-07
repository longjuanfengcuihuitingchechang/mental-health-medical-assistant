(() => {
  const api = window.MHApi;
  const show = (text, kind = "error") => {
    document.querySelector("#formMessage")?.remove();
    const node = document.createElement("div");
    node.id = "formMessage";
    node.className = `rounded-lg p-3 text-sm ${kind === "error" ? "bg-red-50 text-red-700" : "bg-emerald-50 text-emerald-700"}`;
    node.textContent = text;
    document.querySelector("form")?.prepend(node);
  };

  const loginForm = document.querySelector("#loginForm");
  if (loginForm) loginForm.addEventListener("submit", async event => {
    event.preventDefault();
    const button = loginForm.querySelector("button[type=submit]");
    button.disabled = true;
    button.textContent = "正在验证…";
    try {
      const data = await api.login(
        document.querySelector("#role").value,
        document.querySelector("#username").value.trim(),
        document.querySelector("#password").value,
      );
      location.href = data.redirect_path;
    } catch (error) {
      const remaining = error.data?.locked_remaining_seconds;
      const warning = error.data?.warning === "ONE_ATTEMPT_REMAINING" ? "（再失败 1 次将锁定 5 分钟）" : "";
      show(`${error.message}${remaining ? ` 请在 ${remaining} 秒后重试。` : warning}`);
    } finally {
      button.disabled = false;
      button.textContent = "登录";
    }
  });

  const registerForm = document.querySelector("#registerForm");
  if (!registerForm) return;
  const roleInput = document.querySelector("#reg-role");
  roleInput.addEventListener("change", () => {
    const doctor = roleInput.value === "doctor";
    document.querySelector("#doctorFields").classList.toggle("hidden", !doctor);
    document.querySelector("#department").required = doctor;
  });
  registerForm.addEventListener("submit", async event => {
    event.preventDefault();
    const password = document.querySelector("#password").value;
    if (password !== document.querySelector("#confirm-password").value) return show("两次输入的密码不一致");
    const button = registerForm.querySelector("button[type=submit]");
    button.disabled = true;
    button.textContent = "正在提交…";
    try {
      const role = roleInput.value;
      const data = await api.request("/registrations", {
        method: "POST",
        body: JSON.stringify({
          role,
          password,
          display_name: document.querySelector("#fullname").value.trim(),
          id_card: document.querySelector("#id-card").value.trim(),
          phone: document.querySelector("#phone").value.trim(),
          email: document.querySelector("#contact").value.trim(),
          department: role === "doctor" ? document.querySelector("#department").value.trim() : null,
          professional_title: role === "doctor" ? document.querySelector("#professional-title").value.trim() || null : null,
        }),
      });
      show(data.status === "pending_approval" ? `申请已提交，账号 ${data.account || "待生成"}，请等待管理员审批。` : `注册成功，系统账号：${data.account}`, "success");
      registerForm.reset();
      document.querySelector("#doctorFields").classList.add("hidden");
    } catch (error) {
      show(error.message);
    } finally {
      button.disabled = false;
      button.textContent = "注册";
    }
  });
})();
