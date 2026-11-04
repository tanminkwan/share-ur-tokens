import { h, replace } from '/common/dom.js';

// AgentView: talk with my own agent (only when the peer has an LLM). Kept while the messages refresh.
export class AgentView {
  constructor(root, store, actions) { this.root = root; this.actions = actions; this.count = -1; this.built = null; store.subscribe(s => this.render(s)); }

  render({ agent }) {
    if (!agent?.available) { if (this.built !== false) { this.built = false; replace(this.root); } return; }
    if (this.built !== true) {
      this.built = true; this.count = -1;
      this.list = h('div', { class: 'agent-messages', testid: 'agent-messages' });
      const text = h('textarea', { testid: 'agent-text', placeholder: '내 agent에게 묻거나 말하기' });
      const go = () => { if (text.value.trim()) { this.actions.agentSay(text.value); text.value = ''; } };
      replace(this.root, h('h2', {}, '내 agent'), this.list, h('div', { class: 'agent-say' }, text, h('button', { testid: 'agent-send', onclick: go }, '말하기')));
    }
    if (agent.messages.length !== this.count) {
      this.count = agent.messages.length;
      replace(this.list, agent.messages.map(m => h('div', { class: m.who }, m.text)));
    }
  }
}
