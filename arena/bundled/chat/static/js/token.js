// The token from the link the peer printed (#token=...), kept for this tab only and taken out of the address bar.
export function readToken(location = window.location, storage = window.sessionStorage) {
  const m = /(?:^|[#&])token=([^&]+)/.exec(location.hash || '');
  if (m) { storage.setItem('arena-chat-token', decodeURIComponent(m[1])); history.replaceState(null, '', location.pathname); }
  return storage.getItem('arena-chat-token') || '';
}
