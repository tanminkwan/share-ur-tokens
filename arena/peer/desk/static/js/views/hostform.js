import { h, replace } from './dom.js';

// HostForm: open an event (title, kind, rules, roles, schedule). Time codes come from the peer's config.
export class HostForm {
  constructor(root, store, actions) { this.root = root; this.actions = actions; this.drawn = false; store.subscribe(s => this.render(s)); }
  render({ config }) {
    if (!config || this.drawn) return;
    this.drawn = true;
    const title = h('input', { testid: 'host-title' }), kind = h('input', { testid: 'host-kind' });
    const rules = h('textarea', { testid: 'host-rules' }), roles = h('input', { testid: 'host-roles', value: 'member' });
    const when = h('input', { type: 'datetime-local', testid: 'host-when' });
    const code = h('select', { testid: 'host-code' }, h('option', { value: '' }, '(일정 없음)'),
      Object.entries(config.time_codes || {}).map(([c, d]) => h('option', { value: c, title: d }, c)));
    const submit = () => {
      const form = { title: title.value, kind: kind.value, rules: rules.value,
        policy: { roles: roles.value.split(',').map(x => x.trim()).filter(Boolean) } };
      if (code.value && when.value) form.schedule = [{ at: new Date(when.value).getTime() / 1000, code: code.value }];
      this.actions.host(form);
    };
    replace(this.root, h('details', { testid: 'host-form' }, h('summary', {}, '이벤트 열기'),
      h('label', {}, '제목', title), h('label', {}, '종류', kind), h('label', {}, '규칙(자연어)', rules),
      h('label', {}, '역할(쉼표로)', roles), h('label', {}, '일정 시각', when), h('label', {}, '일정 종류', code),
      h('div', { class: 'row' }, h('button', { class: 'primary', testid: 'host-submit', onclick: submit }, '열기'))));
  }
}
