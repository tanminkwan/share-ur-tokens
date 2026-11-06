// ApiClient: talks to the owner API and nothing else (single responsibility). fetch is injected (tests may replace it).
export class ApiError extends Error {
  constructor(status, body) { super(body?.error || `HTTP ${status}`); this.status = status; this.body = body; }
}

export class ApiClient {
  constructor(token, fetchFn = (...a) => window.fetch(...a)) { this.token = token; this.fetch = fetchFn; }

  async request(method, path, body) {
    const r = await this.fetch(path, {
      method, headers: { 'Authorization': `Bearer ${this.token}`, 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let data = {};
    try { data = await r.json(); } catch (_) { /* empty body */ }
    if (!r.ok) throw new ApiError(r.status, data);
    return data;
  }

  config() { return this.request('GET', '/api/config'); }
  state() { return this.request('GET', '/api/state'); }
  items(status = 'open') { return this.request('GET', `/api/items?status=${encodeURIComponent(status)}`); }
  answer(id, answer) { return this.request('POST', `/api/items/${encodeURIComponent(id)}/answer`, answer); }
  event(id) { return this.request('GET', `/api/events/${encodeURIComponent(id)}`); }
  setDrive(id, drive) { return this.request('POST', `/api/events/${encodeURIComponent(id)}/drive`, { drive }); }
  runTool(id, name, args) { return this.request('POST', `/api/events/${encodeURIComponent(id)}/tools/${encodeURIComponent(name)}`, { args }); }
  setNick(nick) { return this.request('POST', '/api/nick', { nick }); }
  host(form) { return this.request('POST', '/api/events', form); }
}
