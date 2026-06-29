export const Api = {
  showApiError(body, fallback = "Request failed") {
    if (body?.error?.message) {
      const code = body.error.code ? `${body.error.code}: ` : "";
      return `${code}${body.error.message}`;
    }
    return body?.detail || fallback;
  },

  async request(path, options = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(Api.showApiError(body, res.statusText));
    }
    return res.json();
  },
};
