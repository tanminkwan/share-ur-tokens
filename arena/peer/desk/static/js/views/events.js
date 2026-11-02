import { h, replace } from './dom.js';

// EventsView: the events this peer hosts or takes part in.
export class EventsView {
  constructor(root, store, actions) { this.root = root; this.actions = actions; store.subscribe(s => this.render(s)); }
  render({ events, selected }) {
    replace(this.root, h('h2', {}, '이벤트'),
      events.length ? events.map(e => h('button', {
        class: `event-item${e.event_id === selected ? ' selected' : ''}`, testid: 'event-item', 'data-id': e.event_id,
        onclick: () => this.actions.openEvent(e.event_id),
      }, `${e.title} · ${e.role === 'host' ? '개최' : '참가'} · ${e.drive}${e.closed ? ' · 닫힘' : ''}`))
        : h('div', { class: 'empty', testid: 'no-events' }, '아직 이벤트가 없다'));
  }
}
