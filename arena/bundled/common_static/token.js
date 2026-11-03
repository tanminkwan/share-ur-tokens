// Where a window's token comes from: the link the peer printed (#token=...), kept for this tab only (each window is its
// own origin, so the same key never mixes two windows) and taken out of the address bar.
export function readToken(location = window.location, storage = window.sessionStorage) {
  const m = /(?:^|[#&])token=([^&]+)/.exec(location.hash || '');
  if (m) {
    storage.setItem('arena-window-token', decodeURIComponent(m[1]));
    history.replaceState(null, '', location.pathname);
  }
  return storage.getItem('arena-window-token') || '';
}
