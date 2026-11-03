// ChatApi: talks to the chat app's local web and nothing else. fetch is injected.
export class ChatApi {
  constructor(token, fetchFn = (...a) => window.fetch(...a)) { this.token = token; this.fetch = fetchFn; }
  async request(method, path, body) {
    const r = await this.fetch(path, { method, headers: { 'Authorization': `Bearer ${this.token}`, 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(data.error || `HTTP ${r.status}`); e.status = r.status; throw e; }
    return data;
  }
  feed() { return this.request('GET', '/api/feed'); }
  say(text) { return this.request('POST', '/api/say', { text }); }
  answer(id, answer) { return this.request('POST', `/api/items/${encodeURIComponent(id)}/answer`, answer); }
}
