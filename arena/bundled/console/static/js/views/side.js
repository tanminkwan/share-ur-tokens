import { h, replace } from '/common/dom.js';
import { ToolForm } from '/common/owner/views/toolform.js';

// SideView: where the event stands as the code sees it, who drives it, its schedule and timers, and the tools the
// person may run by hand (stepping in beyond words).
export class SideView {
  constructor(root, store, actions) { this.root = root; this.actions = actions; this.key = null; store.subscribe(s => this.render(s)); }

  render({ event, config }) {
    if (!event) { this.key = null; return replace(this.root); }
    const key = JSON.stringify([event.event_id, event.drive, event.tools.map(t => t.name), event.timers.length]);
    if (key === this.key) {  // keep half-filled tool forms while polling: the state line carries the clock, so only its text is renewed
      if (this.stateEl) this.stateEl.textContent = event.state_line;
      return;
    }
    this.key = key;
    const forms = new ToolForm((name, args) => this.actions.runTool(event.event_id, name, args));
    this.stateEl = h('div', { class: 'state', testid: 'state-line' }, event.state_line);
    const drive = h('select', { testid: 'drive', onchange: e => this.actions.setDrive(event.event_id, e.target.value) },
      (config?.drives || []).map(d => h('option', { value: d, selected: d === event.drive }, d)));
    replace(this.root,
      h('label', {}, '운전석', drive),
      h('label', {}, '지금 상태(코드가 적음)'), this.stateEl,
      event.schedule.length ? h('div', { testid: 'schedule' }, h('label', {}, '일정(원장)'),
        event.schedule.map(x => h('div', {}, `${x.when} ${x.code}${x.subject ? ' ' + x.subject : ''}`))) : null,
      event.timers.length ? h('div', { testid: 'timers' }, h('label', {}, '예약'), event.timers.map(t => h('div', {}, `${t.when} ${t.kind}`))) : null,
      h('details', { testid: 'tools-box' }, h('summary', {}, '할 수 있는 일(직접 실행)'), h('div', { testid: 'tools' }, event.tools.map(t => forms.render(t)))),
      h('details', {}, h('summary', {}, '규칙'), h('div', { class: 'body' }, event.rules)));
  }
}
