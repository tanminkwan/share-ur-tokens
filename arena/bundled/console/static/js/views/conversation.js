import { h, replace } from '/common/dom.js';

const BY = { peer: '', agent: '내 agent', owner: '나', system: '' };
const NOTE = { action: '행동', thought: '생각', instruction: '내 지시', notice: '공지', ledger: '원장', timer: '예약' };

// ConversationView: one event's conversation as it happens (watch), and stepping in: speak as my peer to another
// (one message: a2a is a walkie-talkie), or instruct my agent. The composer is kept while the timeline refreshes.
export class ConversationView {
  constructor(root, store, actions) {
    this.root = root; this.actions = actions; this.key = null; this.count = -1;
    store.subscribe(s => this.render(s));
  }

  line(x) {
    if (x.dir === 'in') return h('div', { class: 'line in', testid: 'line-in' }, h('span', { class: 'who' }, x.who || '상대'), x.text);
    if (x.dir === 'out') return h('div', { class: `line out by-${x.by}`, testid: 'line-out' },
      h('span', { class: 'who' }, `${BY[x.by] || x.by} → ${x.who || ''}`), x.text);
    const label = [BY[x.by], NOTE[x.kind] || x.kind].filter(Boolean).join(' ');
    return h('div', { class: `line note by-${x.by} ${x.kind}`, testid: `line-note-${x.kind}` }, `${label}: ${x.text}`);
  }

  composer(event) {
    const to = h('select', { testid: 'say-to' }, event.peers.map(p => h('option', { value: p.handle }, p.handle)));
    const text = h('textarea', { testid: 'say-text', placeholder: '상대에게 할 말 (보내면 한 번의 말, 답은 기다린다)' });
    const send = () => { if (text.value.trim()) { this.actions.say(event.event_id, to.value, text.value); text.value = ''; } };
    return h('div', { class: 'composer' }, to, text, h('button', { testid: 'say-send', onclick: send, disabled: !event.peers.length }, '보내기'));
  }

  tellBox(event) {
    const text = h('textarea', { testid: 'tell-text', placeholder: '내 agent에게 이 이벤트에서 할 일을 지시' });
    const go = () => { if (text.value.trim()) { this.actions.tell(event.event_id, text.value); text.value = ''; } };
    return h('div', { class: 'tell' }, text, h('button', { testid: 'tell-send', onclick: go }, '지시'));
  }

  render({ event, me }) {
    if (!event) { this.key = null; return replace(this.root, h('div', { class: 'empty', testid: 'no-event' }, '왼쪽에서 이벤트를 고르면 대화가 보인다')); }
    const key = JSON.stringify([event.event_id, event.peers.map(p => p.handle), !!me?.llm]);
    if (key !== this.key) {  // a new event or new people to speak to: rebuild around the timeline
      this.key = key; this.count = -1;
      this.timeline = h('div', { class: 'timeline', testid: 'timeline' });
      replace(this.root,
        h('h2', { testid: 'conversation-title' }, `${event.title} (${event.role === 'host' ? '개최' : '참가'})`),
        this.timeline, this.composer(event), me?.llm ? this.tellBox(event) : null);
    }
    if (event.timeline.length !== this.count) {
      this.count = event.timeline.length;
      replace(this.timeline, event.timeline.length ? event.timeline.map(x => this.line(x)) : h('div', { class: 'empty' }, '아직 오간 말이 없다'));
      this.timeline.scrollTop = this.timeline.scrollHeight;
    }
  }
}
