import { h } from './dom.js';

// ToolForm: a form drawn from a tool's argument schema, so new tools need no screen code. Strings are text fields,
// numbers number fields, booleans checkboxes, anything else JSON.
export class ToolForm {
  constructor(onRun) { this.onRun = onRun; }

  field(name, schema) {
    if (schema.type === 'boolean') return h('input', { type: 'checkbox', testid: `arg-${name}` });
    if (schema.type === 'number' || schema.type === 'integer') return h('input', { type: 'number', testid: `arg-${name}` });
    if (schema.type === 'string') return h('input', { testid: `arg-${name}` });
    return h('textarea', { testid: `arg-${name}`, placeholder: 'JSON' });
  }

  read(name, schema, el) {
    if (schema.type === 'boolean') return el.checked;
    if (schema.type === 'number' || schema.type === 'integer') return el.value === '' ? undefined : Number(el.value);
    if (schema.type === 'string') return el.value;
    return el.value ? JSON.parse(el.value) : undefined;
  }

  render(tool) {
    const props = tool.args?.properties || {};
    const fields = Object.entries(props).map(([n, s]) => [n, s, this.field(n, s)]);
    const run = () => {
      const args = {};
      for (const [n, s, el] of fields) { const v = this.read(n, s, el); if (v !== undefined && v !== '') args[n] = v; }
      this.onRun(tool.name, args);
    };
    return h('details', { testid: `tool-${tool.name}` },
      h('summary', {}, tool.label || tool.name, ' ', h('span', { class: 'code' }, tool.name)),
      h('div', { class: 'body' }, tool.help || tool.description),
      ...fields.map(([n, s, el]) => h('label', {}, s.title || n, el)),
      h('div', { class: 'row' }, h('button', { class: 'primary', testid: `run-${tool.name}`, onclick: run }, '실행')));
  }
}
