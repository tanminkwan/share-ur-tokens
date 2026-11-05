import { h, replace } from '/common/dom.js';
import { clock } from '../format.js';

// AccessView: who tried to read the whole ledger. The window's own reads are left out (it reads on every refresh).
export class AccessView {
  constructor(root, store, keep = 8) { this.root = root; this.keep = keep; this.key = null; store.subscribe(s => this.render(s)); }
  render({ view, me }) {
    const rows = (view?.snapshot?.access || []).filter(a => a.reader !== me?.pub);
    const own = (view?.snapshot?.access || []).length - rows.length;
    const key = JSON.stringify([rows, own]);
    if (key === this.key) return;
    this.key = key;
    replace(this.root, h('h2', {}, '원장 열람 기록'),
      rows.length ? h('table', {}, rows.slice(-this.keep).reverse().map(a => h('tr', { testid: 'access-row' },
        h('td', {}, clock(a.ts)), h('td', {}, view.names?.[a.reader] || a.reader.slice(0, 8)), h('td', {}, a.granted ? '허용' : '거부'))))
        : h('div', { class: 'empty', testid: 'no-access' }, '다른 peer의 열람 시도는 아직 없다'),
      h('div', { class: 'empty' }, `이 창 자신의 읽기 ${own}건은 뺐다`));
  }
}
