import { ApiClient } from '/common/owner/api.js';

// ConsoleApi: the owner API plus the conversation (speak as my peer, instruct my agent, talk with my agent).
export class ConsoleApi extends ApiClient {
  say(id, to, text) { return this.request('POST', `/api/events/${encodeURIComponent(id)}/say`, { to, text }); }
  tell(id, text) { return this.request('POST', `/api/events/${encodeURIComponent(id)}/tell`, { text }); }
  agent() { return this.request('GET', '/api/agent'); }
  agentSay(text) { return this.request('POST', '/api/agent/say', { text }); }
}
