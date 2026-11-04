import { h, replace } from '/common/dom.js';

// HeaderView: who this peer is and who drives it.
export class HeaderView {
  constructor(root, store) { this.root = root; store.subscribe(s => this.render(s)); }
  render({ me, items }) {
    if (!me) return replace(this.root, h('span', { class: 'empty' }, '연결 중…'));
    replace(this.root,
      h('span', { class: 'pen', testid: 'me-pen' }, me.pen),
      h('span', { class: 'tag', testid: 'me-operator' }, me.operator),
      h('span', { class: 'tag' }, me.llm ? 'LLM 있음' : 'LLM 없음'),
      h('span', { class: 'tag', testid: 'open-count' }, `열린 알림 ${items.length}`));
  }
}
