import { h, replace } from '/common/dom.js';

// HeaderView: who this peer is, what kind of peer (its background, arena.css [data-peer]) and who drives it.
// With `actions`, the owner can rename the peer here, any time (the nickname before the key start; the key start stays).
const REACH = { direct: '직접 연결됨', relay: '중계로 연결됨', checking: '연결 확인 중' };

export function showKind(me, doc = document) { if (me && me.kind) doc.documentElement.dataset.peer = me.kind; }

export class HeaderView {
  constructor(root, store, actions = null) { this.root = root; this.actions = actions; this.editing = false; this.last = null;
    store.subscribe(s => this.render(s)); }

  rename(me) {  // the form replaces the name until it is sent or cancelled; polling must not wipe what is being typed
    const input = h('input', { testid: 'nick-input', value: me.nick, maxlength: 16, 'aria-label': '닉네임' });
    const done = () => { this.editing = false; this.render(this.last); };
    const send = async () => { await this.actions.setNick(input.value.trim()); done(); };
    input.addEventListener('keydown', e => { if (e.key === 'Enter') send(); if (e.key === 'Escape') done(); });
    this.editing = true;
    replace(this.root, input, h('span', { class: 'tag' }, `-${me.pen.slice(me.pen.lastIndexOf('-') + 1)}`),
      h('button', { class: 'primary', testid: 'nick-save', onclick: send }, '저장'), h('button', { testid: 'nick-cancel', onclick: done }, '취소'));
    input.focus(); input.select();
  }

  render(s) {
    this.last = s;
    const { me, items } = s;
    if (this.editing && me) return;
    if (!me) return replace(this.root, h('span', { class: 'empty' }, '연결 중…'));
    showKind(me);
    replace(this.root,
      h('span', { class: 'pen', testid: 'me-pen' }, me.pen),
      ...(this.actions ? [h('button', { testid: 'nick-edit', title: '닉네임 바꾸기', onclick: () => this.rename(me) }, '이름 바꾸기')] : []),
      h('span', { class: 'tag kind', testid: 'me-kind' }, me.kind_label),
      h('span', { class: 'tag', testid: 'me-operator' }, me.operator),
      ...(me.reach ? [h('span', { class: 'tag', testid: 'me-reach', title: '바깥에서 이 peer에 닿는 길' }, REACH[me.reach] || me.reach)] : []),
      h('span', { class: 'tag' }, me.llm ? 'LLM 있음' : 'LLM 없음'),
      h('span', { class: 'tag', testid: 'open-count' }, `열린 알림 ${items.length}`));
  }
}
