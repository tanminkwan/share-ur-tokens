import { h, replace } from '/common/dom.js';
import { counts } from '../format.js';

// SummaryView: how much the ledger holds, by what kind of entry.
export class SummaryView {
  constructor(root, store) { this.root = root; this.key = null; store.subscribe(s => this.render(s)); }
  render({ view }) {
    const st = view?.snapshot?.stats;
    const key = JSON.stringify(st);
    if (key === this.key) return;
    this.key = key;
    if (!st) return replace(this.root, h('h2', {}, '요약'), h('div', { class: 'empty', testid: 'no-snapshot' }, view?.error || '아직 원장을 읽지 못했다'));
    const stat = (label, n, id) => h('div', { class: 'stat', testid: id }, h('b', {}, n), label);
    replace(this.root, h('h2', {}, '요약'),
      h('div', { class: 'stat-row' }, stat('원장 항목', st.entries, 'stat-entries'), stat('서명한 peer', st.signers, 'stat-signers'),
        stat('event', st.events.length, 'stat-events'), stat('닫힌 event', st.closed.length, 'stat-closed'), stat('경과(초)', st.span_sec, 'stat-span')),
      h('div', { class: 'state', testid: 'by-type' }, counts(st.by_type)),
      h('label', {}, '역할 계약'), h('div', { class: 'state' }, counts(st.roles)));
  }
}
