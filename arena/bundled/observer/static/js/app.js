// Composition root of the observer window: read-only views over one snapshot, refreshed by a poller.
import { ObserverApi } from './api.js';
import { Poller } from '/common/owner/poller.js';
import { Store } from '/common/owner/store.js';
import { readToken } from '/common/token.js';
import { Toast } from '/common/owner/views/toast.js';
import { AccessView } from './views/access.js';
import { EventsView } from './views/events.js';
import { HeaderView } from './views/header.js';
import { IntegrityView } from './views/integrity.js';
import { PeersView } from './views/peers.js';
import { RecentView } from './views/recent.js';
import { SummaryView } from './views/summary.js';

const $ = id => document.getElementById(id);
const toast = new Toast($('toast'));
const store = new Store({ me: null, view: null, pollMs: 3000, lastOk: 0, error: false });
const api = new ObserverApi(readToken());

new HeaderView($('header'), store);
new SummaryView($('summary'), store);
new IntegrityView($('integrity'), store);
new AccessView($('access'), store);
new RecentView($('recent'), store);
new EventsView($('events'), store);
new PeersView($('peers'), store);

async function refresh() {
  try {
    const view = await api.snapshot();
    store.set({ view, lastOk: view.as_of, error: false });
  } catch (e) {
    store.set({ error: true });
    if (e.status === 401) toast.show('토큰이 없거나 틀렸다. peer가 알려 준 주소(#token=…)로 열어라', 'bad');
  }
}

Promise.all([api.config(), api.state()])
  .then(([config, { me }]) => { store.set({ me, pollMs: config.poll_ms }); return refresh().then(() => new Poller(refresh, config.poll_ms).start()); })
  .catch(e => toast.show(e.status === 401 ? '토큰이 없거나 틀렸다. peer가 알려 준 주소(#token=…)로 열어라' : (e.message || String(e)), 'bad'));
