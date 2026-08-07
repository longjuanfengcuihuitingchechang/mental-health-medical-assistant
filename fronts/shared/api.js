(() => {
  const state = { session: null, csrf: null };

  class ApiError extends Error {
    constructor(message, status, data) {
      super(message);
      this.status = status;
      this.data = data || {};
    }
  }

  async function request(path, options = {}) {
    const method = (options.method || "GET").toUpperCase();
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.body && !(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
    if (!["GET", "HEAD", "OPTIONS"].includes(method) && state.csrf) headers["X-CSRF-Token"] = state.csrf;
    const response = await fetch(`/api/v1${path}`, { ...options, method, headers, credentials: "same-origin" });
    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new ApiError("服务返回了无法解析的响应", response.status);
    }
    if (!response.ok || payload.code !== 0) {
      if (response.status === 401 && !path.startsWith("/auth/login")) state.session = state.csrf = null;
      throw new ApiError(payload.message || "请求失败", response.status, payload.data);
    }
    return payload.data;
  }

  async function session(force = false) {
    if (state.session && !force) return state.session;
    const data = await request("/auth/session");
    state.session = data;
    state.csrf = data.csrf_token;
    return data;
  }

  async function login(identity_type, account, password) {
    const data = await request("/auth/login", {
      method: "POST",
      body: JSON.stringify({ identity_type, account, password }),
    });
    state.session = data;
    state.csrf = data.csrf_token;
    return data;
  }

  async function logout() {
    await request("/auth/logout", { method: "POST" });
    state.session = state.csrf = null;
  }

  window.MHApi = { request, session, login, logout, state, ApiError };
})();
