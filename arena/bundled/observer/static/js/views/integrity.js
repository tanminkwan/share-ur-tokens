import { h, replace } from '/common/dom.js';
import { short } from '../format.js';

// IntegrityView: the god audits every recorder's copy itself (hash chain, signatures, the recorder's seal).
export class IntegrityView {
  constructor(root, store) { this.root = root; this.key = null; store.subscribe(s => this.render(s)); }
  render({ view }) {
    const ig = view?.snapshot?.integrity;
    const key = JSON.stringify(ig);
    if (key === this.key) return;
    this.key = key;
    if (!ig) return replace(this.root);
    replace(this.root, h('h2', {}, '무결성 (god이 직접 검증)'),
      h('div', { class: ig.agree ? 'state' : 'state warn', testid: 'integrity-verdict' },
        ig.agree ? '정상: 해시 사슬, 서명, 기록자 봉인이 맞고 사본이 모두 같다' : '경고: 변조 또는 기록자 사이 불일치'),
      h('table', {}, h('tr', {}, h('th', {}, '기록자'), h('th', {}, '상태'), h('th', { class: 'num' }, '항목'), h('th', {}, 'head')),
        ig.recorders.map(r => h('tr', { testid: 'recorder-row' }, h('td', {}, view.names?.[r.recorder] || short(r.recorder, 8)),
          h('td', {}, r.status), h('td', { class: 'num' }, r.length), h('td', { class: 'code' }, short(r.head))))));
  }
}
