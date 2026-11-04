// Composition root: builds the pieces and wires them (the only place that knows the concrete classes).
import { Actions } from '/common/owner/actions.js';
import { ApiClient } from '/common/owner/api.js';
import { Poller } from '/common/owner/poller.js';
import { Store } from '/common/owner/store.js';
import { readToken } from '/common/token.js';
import { defaultCards } from '/common/owner/views/cards.js';
import { EventView } from './views/event.js';
import { EventsView } from '/common/owner/views/events.js';
import { HeaderView } from '/common/owner/views/header.js';
import { HostForm } from '/common/owner/views/hostform.js';
import { ItemsView } from '/common/owner/views/items.js';
import { Toast } from '/common/owner/views/toast.js';

const $ = id => document.getElementById(id);
const toast = new Toast($('toast'));
const store = new Store();
const actions = new Actions(new ApiClient(readToken()), store, (text, tone) => toast.show(text, tone));

new HeaderView($('header'), store);
new EventsView($('events'), store, actions);
new HostForm($('host'), store, actions);
new ItemsView($('items'), store, actions, defaultCards());
new EventView($('event'), store, actions);

actions.load()
  .then(() => new Poller(() => actions.refresh(), store.state.config.poll_ms).start())
  .catch(e => toast.show(e.status === 401 ? '토큰이 없거나 틀렸다. peer가 알려 준 주소(#token=…)로 열어라' : (e.message || String(e)), 'bad'));
