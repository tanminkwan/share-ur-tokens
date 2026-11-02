import { h } from './dom.js';

// Cards for desk items. One renderer per kind, registered here: a new kind is a new registration, not an edit of the
// views (open/closed). A renderer gets the item and the actions and returns an element.
export class CardRegistry {
  constructor(fallback) { this.renderers = new Map(); this.fallback = fallback; }
  register(kind, renderer) { this.renderers.set(kind, renderer); return this; }
  render(item, actions, labels) { return (this.renderers.get(item.kind) || this.fallback)(item, actions, labels); }
}

function frame(item, labels, ...rest) {
  return h('div', { class: 'card', testid: `item-${item.kind}`, 'data-id': item.id },
    h('div', { class: 'kind' }, labels[item.kind] || item.kind, item.event_id ? ` · ${item.event_id}` : ''),
    h('div', { class: 'title' }, item.title),
    item.body ? h('div', { class: 'body' }, item.body) : null,
    ...rest);
}

const openEvent = (item, actions) => item.event_id
  ? h('button', { testid: 'open-event', onclick: () => actions.openEvent(item.event_id) }, '이벤트 열기') : null;

export function infoCard(item, actions, labels) {
  return frame(item, labels, h('div', { class: 'row' },
    openEvent(item, actions),
    h('button', { testid: 'mark-read', onclick: () => actions.answer(item.id, {}) }, '읽음')));
}

export function questionCard(item, actions, labels) {
  const why = h('input', { placeholder: '이유(선택)', testid: 'why' });
  return frame(item, labels, why, h('div', { class: 'row' },
    h('button', { class: 'primary', testid: 'answer-yes', onclick: () => actions.answer(item.id, { yes: true, why: why.value || '예' }) }, '예'),
    h('button', { class: 'bad', testid: 'answer-no', onclick: () => actions.answer(item.id, { yes: false, why: why.value || '아니오' }) }, '아니오'),
    openEvent(item, actions)));
}

export function writeCard(item, actions, labels) {
  const inputs = Object.entries(item.fields || {}).map(([name, desc]) => [name, h('textarea', { testid: `field-${name}`, placeholder: desc })]);
  return frame(item, labels,
    ...inputs.map(([name, el]) => h('label', {}, name, el)),
    h('div', { class: 'row' }, h('button', { class: 'primary', testid: 'send-fields',
      onclick: () => actions.answer(item.id, { fields: Object.fromEntries(inputs.map(([n, el]) => [n, el.value])) }) }, '보내기')));
}

export function suggestionCard(item, actions, labels) {
  return frame(item, labels,
    h('div', { class: 'body', testid: 'suggested-tool' }, `${item.fields.tool} ${JSON.stringify(item.fields.args || {})}`),
    h('div', { class: 'row' },
      h('button', { class: 'primary', testid: 'approve', onclick: () => actions.answer(item.id, { approve: true }) }, '승인'),
      h('button', { class: 'bad', testid: 'reject', onclick: () => actions.answer(item.id, { approve: false }) }, '거절'),
      openEvent(item, actions)));
}

export function defaultCards() {
  return new CardRegistry(infoCard).register('question', questionCard).register('write', writeCard).register('suggestion', suggestionCard);
}
