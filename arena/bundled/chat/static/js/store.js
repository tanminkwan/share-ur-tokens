// Store: the chat's state and who listens to it. No HTTP, no DOM.
export class Store {
  constructor() { this.state = { me: null, messages: [], items: [], busy: false, pollMs: 2000 }; this.subs = []; }
  subscribe(fn) { this.subs.push(fn); fn(this.state); }
  set(patch) { this.state = { ...this.state, ...patch }; this.subs.forEach(fn => fn(this.state)); }
}
