import { h } from '/common/dom.js';

// Toast: short messages about what just happened (results, errors).
export class Toast {
  constructor(root, keepMs = 6000) { this.root = root; this.keepMs = keepMs; }
  show(text, tone = 'ok') {
    const m = h('div', { class: `msg ${tone}`, testid: `toast-${tone}` }, text);
    this.root.append(m);
    setTimeout(() => m.remove(), this.keepMs);
  }
}
