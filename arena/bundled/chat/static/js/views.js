import { h } from '/common/dom.js';

// Pending things from the desk shown inside the chat. One renderer per kind (a new kind = a new registration).
const AWAITED = {
  question: (it, a) => h('div', { class: 'ask', testid: 'ask-question', 'data-id': it.id },
    h('div', { class: 'kind' }, '비서가 묻습니다'), h('div', {}, it.title),
    h('div', { class: 'row' },
      h('button', { class: 'primary', testid: 'ask-yes', onclick: () => a.answer(it.id, { yes: true, why: '예' }) }, '예'),
      h('button', { class: 'bad', testid: 'ask-no', onclick: () => a.answer(it.id, { yes: false, why: '아니오' }) }, '아니오'))),
  suggestion: (it, a) => h('div', { class: 'ask', testid: 'ask-suggestion', 'data-id': it.id },
    h('div', { class: 'kind' }, '비서가 이렇게 하려 합니다'), h('div', {}, `${it.fields.tool} ${JSON.stringify(it.fields.args || {})}`),
    h('div', { class: 'row' },
      h('button', { class: 'primary', testid: 'ask-approve', onclick: () => a.answer(it.id, { approve: true }) }, '승인'),
      h('button', { class: 'bad', testid: 'ask-reject', onclick: () => a.answer(it.id, { approve: false }) }, '거절'))),
};
const NOTE = (it, a) => h('div', { class: 'note', testid: `note-${it.kind}` }, `· ${it.title} `,
  h('button', { onclick: () => a.answer(it.id, {}) }, '확인'));

export class HeaderView {
  constructor(root, store) { this.root = root; store.subscribe(s => this.render(s)); }
  render({ me }) { this.root.replaceChildren(me ? h('span', { class: 'pen', testid: 'me-pen' }, me.pen) : h('span', {}, '연결 중…'),
    h('span', {}, '내 비서와 대화')); }
}

export class TimelineView {
  constructor(root, store, actions, awaited = AWAITED, note = NOTE) {
    this.root = root; this.actions = actions; this.awaited = awaited; this.note = note; this.key = null;
    store.subscribe(s => this.render(s));
  }
  render({ messages, items }) {
    const key = JSON.stringify([messages.length, items.map(i => i.id)]);
    if (key === this.key) return;
    this.key = key;
    const msgs = messages.map(m => h('div', { class: `msg ${m.who}`, testid: `msg-${m.who}` }, m.text));
    const pend = items.map(it => (this.awaited[it.kind] || this.note)(it, this.actions));
    this.root.replaceChildren(...msgs, ...pend);
    this.root.scrollTop = this.root.scrollHeight;
  }
}

export class ComposerView {
  constructor(root, store, actions) {
    this.input = h('input', { testid: 'say', placeholder: '내 비서에게 말하기', autocomplete: 'off' });
    this.button = h('button', { class: 'primary', testid: 'send', type: 'submit' }, '보내기');
    root.append(this.input, this.button);
    root.addEventListener('submit', e => { e.preventDefault(); const t = this.input.value; this.input.value = ''; actions.say(t); });
    store.subscribe(s => { this.button.disabled = s.busy; });
  }
}
