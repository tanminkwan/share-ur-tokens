import { h, replace } from '/common/dom.js';
import { short } from '../format.js';

// EventsView: the events the ledger knows, who opened them, who endorsed, whether they are closed.
export class EventsView {
  constructor(root, store) { this.root = root; this.key = null; store.subscribe(s => this.render(s)); }
  render({ view }) {
    const st = view?.snapshot?.stats;
    const key = JSON.stringify([st?.events, st?.closed]);
    if (key === this.key) return;
    this.key = key;
    if (!st) return replace(this.root);
    const closed = new Set(st.closed.map(c => c.event_id)), name = p => view.names?.[p] || short(p, 8);
    replace(this.root, h('h2', {}, 'event'),
      st.events.length ? h('div', { class: 'scroll' }, h('table', {},
        h('tr', {}, h('th', {}, 'event'), h('th', {}, '종류'), h('th', {}, '연 peer'), h('th', { class: 'num' }, '공동 서명'), h('th', {}, '상태')),
        st.events.map(e => h('tr', { testid: 'event-row' }, h('td', { class: 'code' }, e.event_id), h('td', {}, e.kind || '-'), h('td', {}, name(e.issuer)),
          h('td', { class: 'num' }, e.endorsers.length), h('td', {}, closed.has(e.event_id) ? '닫힘' : '열림')))))
        : h('div', { class: 'empty', testid: 'no-events' }, '아직 event가 없다'));
  }
}
