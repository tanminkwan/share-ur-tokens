import { Actions } from '/common/owner/actions.js';

// ConsoleActions: the owner's use cases plus stepping into the conversation.
export class ConsoleActions extends Actions {
  async refresh() {
    await super.refresh();
    this.store.set({ agent: await this.api.agent() });
  }

  async say(id, to, text) {
    await this.guard(async () => {
      const r = await this.api.say(id, to, text);
      if (r.ok === false || r.error) this.notify(r.error || '보내지 못했다', 'bad'); else this.notify(`보냈다 → ${to}`);
      await this.refresh();
    });
  }

  async tell(id, text) {
    await this.guard(async () => { await this.api.tell(id, text); this.notify('내 agent에게 지시했다'); await this.refresh(); });
  }

  async agentSay(text) {
    await this.guard(async () => { await this.api.agentSay(text); await this.refresh(); });
  }
}
