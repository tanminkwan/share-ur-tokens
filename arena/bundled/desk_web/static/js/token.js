// Where the owner API token comes from: the link the peer printed (#token=...), kept for this tab only.
export function readToken(location = window.location, storage = window.sessionStorage) {
  const m = /(?:^|[#&])token=([^&]+)/.exec(location.hash || '');
  if (m) {
    storage.setItem('arena-desk-token', decodeURIComponent(m[1]));
    history.replaceState(null, '', location.pathname);  // keep the token out of the address bar
  }
  return storage.getItem('arena-desk-token') || '';
}
