import { h, replace } from '/common/dom.js';
import { clock, short } from '../format.js';

// RecentView: the latest ledger entries, newest first (who signed, never content).
export class RecentView {
  constructor(root, store) { this.root = root; this.key = null; store.subscribe(s => this.render(s)); }
  render({ view }) {
    const rows = view?.snapshot?.recent;
    const key = JSON.stringify(rows);
    if (key === this.key) return;
    this.key = key;
    if (!rows) return replace(this.root);
    replace(this.root, h('h2', {}, '최근 원장 항목'),
      h('div', { class: 'scroll' }, h('table', {},
        h('tr', {}, h('th', { class: 'num' }, '#'), h('th', {}, '종류'), h('th', {}, '서명'), h('th', {}, 'event'), h('th', {}, '시각'), h('th', {}, 'hash')),
        rows.map(e => h('tr', { testid: 'recent-row', 'data-type': e.type },
          h('td', { class: 'num' }, e.seq), h('td', {}, e.type), h('td', {}, e.who.join(', ')), h('td', { class: 'code' }, short(e.event_id || '', 14)),
          h('td', {}, clock(e.ts)), h('td', { class: 'code' }, short(e.hash, 8)))))));
  }
}
