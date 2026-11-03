import { h, replace } from '/common/dom.js';
import { ToolForm } from './toolform.js';

// EventView: one event as the code sees it (state line, schedule, my timers), its drive, the tools the owner may run,
// and the recent record.
export class EventView {
  constructor(root, store, actions) {
    this.root = root; this.actions = actions; this.lastKey = null;
    store.subscribe(s => this.render(s));
  }
  render({ event, config }) {
    if (!event) return replace(this.root, h('div', { class: 'empty', testid: 'no-event' }, '왼쪽에서 이벤트를 고르면 여기에 보인다'));
    const key = JSON.stringify([event.event_id, event.drive, event.transcript.length, event.state_line, event.tools.map(t => t.name), event.timers.length]);
    if (key === this.lastKey) return;  // keep half-filled forms while polling
    this.lastKey = key;
    const forms = new ToolForm((name, args) => this.actions.runTool(event.event_id, name, args));
    const drive = h('select', { testid: 'drive', onchange: e => this.actions.setDrive(event.event_id, e.target.value) },
      (config?.drives || []).map(d => h('option', { value: d, selected: d === event.drive }, d)));
    replace(this.root,
      h('h2', { testid: 'event-title' }, `${event.title} (${event.role === 'host' ? '개최' : '참가'})`),
      h('label', {}, '운전석', drive),
      h('label', {}, '지금 상태(코드가 적음)'), h('div', { class: 'state', testid: 'state-line' }, event.state_line),
      event.schedule.length ? h('div', { testid: 'schedule' }, h('label', {}, '일정(원장)'),
        event.schedule.map(x => h('div', {}, `${x.when} ${x.code}${x.subject ? ' ' + x.subject : ''}${x.note ? ' · ' + x.note : ''}`))) : null,
      event.timers.length ? h('div', { testid: 'timers' }, h('label', {}, '예약'),
        event.timers.map(t => h('div', {}, `${t.when} ${t.kind}`))) : null,
      h('label', {}, '할 수 있는 일'), h('div', { testid: 'tools' }, event.tools.map(t => forms.render(t))),
      h('label', {}, '기록'), h('div', { class: 'transcript', testid: 'transcript' }, event.transcript.join('\n')),
      h('details', {}, h('summary', {}, '규칙'), h('div', { class: 'body' }, event.rules)));
  }
}
