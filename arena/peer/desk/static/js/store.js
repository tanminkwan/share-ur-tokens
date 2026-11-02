// Store: the screen's state and who listens to it. No HTTP, no DOM.
export class Store {
  constructor(initial = {}) { this.state = { config: null, me: null, events: [], items: [], selected: null, event: null, ...initial }; this.subs = []; }
  subscribe(fn) { this.subs.push(fn); fn(this.state); return () => { this.subs = this.subs.filter(f => f !== fn); }; }
  set(patch) { this.state = { ...this.state, ...patch }; this.subs.forEach(fn => fn(this.state)); }
}
