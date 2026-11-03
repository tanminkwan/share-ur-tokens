import { h, replace } from './dom.js';

// ItemsView: the open things on the desk, newest first, each drawn by its kind's card.
export class ItemsView {
  constructor(root, store, actions, cards) {
    this.root = root; this.actions = actions; this.cards = cards; this.lastKey = null;
    store.subscribe(s => this.render(s));
  }
  render({ items, config }) {
    const key = items.map(it => it.id).join(',') + (config ? '+' : '');
    if (key === this.lastKey) return;  // the same items: keep what the owner is typing
    this.lastKey = key;
    const labels = config?.item_kinds || {};
    if (!items.length) return replace(this.root, h('div', { class: 'empty', testid: 'no-items' }, '열린 알림이 없다'));
    replace(this.root, items.map(it => this.cards.render(it, this.actions, labels)));
  }
}
