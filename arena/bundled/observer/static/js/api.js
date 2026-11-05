// ObserverApi: read-only. The snapshot of the whole world as the god sees it.
export class ObserverApi {
  constructor(token) { this.token = token; }
  async get(path) {
    const r = await fetch(path, { headers: { Authorization: `Bearer ${this.token}` } });
    if (!r.ok) { const e = new Error(r.status === 401 ? 'token required' : `HTTP ${r.status}`); e.status = r.status; throw e; }
    return r.json();
  }
  config() { return this.get('/api/config'); }
  state() { return this.get('/api/state'); }
  snapshot() { return this.get('/api/snapshot'); }
}
