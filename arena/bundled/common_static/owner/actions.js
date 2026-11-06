// Actions: the owner's use cases. Views call these; these call the ApiClient and update the Store (views never call HTTP).
export class Actions {
  constructor(api, store, notify) { this.api = api; this.store = store; this.notify = notify; }

  async load() {
    const config = await this.api.config();
    this.store.set({ config });
    await this.refresh();
  }

  async refresh() {
    const [st, items] = await Promise.all([this.api.state(), this.api.items('open')]);
    this.store.set({ me: st.me, events: st.events, items: items.items });
    const sel = this.store.state.selected;
    if (sel) this.store.set({ event: await this.api.event(sel) });
  }

  async openEvent(id) {
    this.store.set({ selected: id, event: await this.api.event(id) });
  }

  async answer(id, answer) {
    await this.guard(async () => { await this.api.answer(id, answer); await this.refresh(); });
  }

  async setDrive(id, drive) {
    await this.guard(async () => { await this.api.setDrive(id, drive); this.notify(`운전석: ${drive}`); await this.refresh(); });
  }

  async runTool(id, name, args) {
    await this.guard(async () => {
      const r = await this.api.runTool(id, name, args);
      this.notify(`${name} → ${JSON.stringify(r)}`, r.ok === false || r.error ? 'bad' : 'ok');
      await this.refresh();
    });
  }

  async setNick(nick) {
    await this.guard(async () => { const r = await this.api.setNick(nick); this.notify(`이름: ${r.pen}`); await this.refresh(); });
  }

  async host(form) {
    await this.guard(async () => {
      const r = await this.api.host(form);
      this.notify(`이벤트를 열었다: ${form.title}`);
      await this.refresh();
      await this.openEvent(r.event_id);
    });
  }

  async guard(fn) {
    try { await fn(); } catch (e) { this.notify(e.message || String(e), 'bad'); }
  }
}
