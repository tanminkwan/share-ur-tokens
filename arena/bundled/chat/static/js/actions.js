// Actions: what the person can do here (say something, answer a pending question). Views call these.
export class Actions {
  constructor(api, store, notify) { this.api = api; this.store = store; this.notify = notify; }
  async refresh() {
    const f = await this.api.feed();
    this.store.set({ me: f.me, messages: f.messages, items: f.items, pollMs: f.poll_ms });
  }
  async say(text) {
    if (!text.trim()) return;
    this.store.set({ busy: true });
    try { await this.api.say(text); await this.refresh(); } catch (e) { this.notify(e.message); } finally { this.store.set({ busy: false }); }
  }
  async answer(id, answer) {
    try { await this.api.answer(id, answer); await this.refresh(); } catch (e) { this.notify(e.message); }
  }
}
