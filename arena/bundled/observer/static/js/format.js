// Small pure helpers for the observer's tables.
export const clock = ts => new Date(ts * 1000).toLocaleTimeString('ko-KR', { hour12: false });
export const short = (s, n = 10) => (s || '').slice(0, n);
export const total = obj => Object.values(obj || {}).reduce((a, b) => a + b, 0);
export const counts = obj => Object.entries(obj || {}).map(([k, v]) => `${k} ${v}`).join(', ') || '-';
