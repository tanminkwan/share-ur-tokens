// Poller: runs a task every few milliseconds while the page is open (the owner sees new things without reloading).
export class Poller {
  constructor(task, ms) { this.task = task; this.ms = ms; this.timer = null; }
  start() { const tick = async () => { try { await this.task(); } finally { this.timer = setTimeout(tick, this.ms); } }; this.timer = setTimeout(tick, this.ms); }
  stop() { clearTimeout(this.timer); }
}
