import { h, replace } from '/common/dom.js';
import { counts, total } from '../format.js';

// PeersView: each peer's strengths (what its profile says) beside its track record (what the ledger proves).
export class PeersView {
  constructor(root, store) { this.root = root; this.key = null; store.subscribe(s => this.render(s)); }
  render({ view }) {
    const rows = view?.snapshot?.peers;
    const key = JSON.stringify(rows);
    if (key === this.key) return;
    this.key = key;
    if (!rows) return replace(this.root);
    replace(this.root, h('h2', {}, 'peer (강점과 실적)'),
      rows.length ? h('div', { class: 'scroll' }, h('table', {},
        h('tr', {}, h('th', {}, 'peer'), h('th', {}, '강점(자기소개)'), h('th', { class: 'num' }, '계약'), h('th', { class: 'num' }, '등록'), h('th', { class: 'num' }, '받음')),
        rows.map(p => h('tr', { testid: 'peer-row' }, h('td', {}, p.who), h('td', { class: 'strengths', title: p.strengths || '' }, p.strengths || (p.labels || []).join(', ') || '-'),
          h('td', { class: 'num', title: counts(p.roles) }, total(p.roles)), h('td', { class: 'num' }, p.published), h('td', { class: 'num' }, p.received_by)))))
        : h('div', { class: 'empty', testid: 'no-peers' }, '아직 peer가 없다'));
  }
}
