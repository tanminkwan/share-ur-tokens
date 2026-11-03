// Composition root of the chat window.
import { Actions } from './actions.js';
import { ChatApi } from './api.js';
import { Store } from './store.js';
import { readToken } from '/common/token.js';
import { ComposerView, HeaderView, TimelineView } from './views.js';

const $ = id => document.getElementById(id);
const store = new Store();
const notify = text => { $('toast').textContent = text; };
const actions = new Actions(new ChatApi(readToken()), store, notify);
new HeaderView($('header'), store);
new TimelineView($('timeline'), store, actions);
new ComposerView($('composer'), store, actions);

const poll = async () => { try { await actions.refresh(); } catch (e) { notify(e.status === 401 ? '토큰이 없거나 틀렸다. peer가 알려 준 주소(#token=…)로 열어라' : e.message); return; } setTimeout(poll, store.state.pollMs); };
poll();
