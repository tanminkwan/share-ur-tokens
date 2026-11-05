import { h, replace } from '/common/dom.js';
import { showKind } from '/common/owner/views/header.js';
import { clock } from '../format.js';

// HeaderView: who this peer is, its kind (the background), and that the window keeps itself fresh (the person leaves it open).
export class HeaderView {
  constructor(root, store) { this.root = root; store.subscribe(s => this.render(s)); }
  render({ me, pollMs, lastOk, error }) {
    if (!me) return replace(this.root, h('span', { class: 'empty' }, '연결 중…'));
    showKind(me);
    replace(this.root,
      h('span', { class: 'pen', testid: 'me-pen' }, me.pen),
      h('span', { class: 'tag kind', testid: 'me-kind' }, me.kind_label),
      h('span', { class: 'tag', testid: 'refresh-state' }, error ? '연결 끊김, 다시 시도 중' : `자동 갱신 · ${pollMs / 1000}초마다`),
      h('span', { class: 'tag', testid: 'last-update' }, lastOk ? `마지막 갱신 ${clock(lastOk)}` : '아직 받지 못함'));
  }
}
