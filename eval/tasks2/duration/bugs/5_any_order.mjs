const RE = /^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$/;
const RE2 = /^(?:(\d+)m)?(?:(\d+)h)?(?:(\d+)s)?$/;

export function parseDuration(text) {
  if (typeof text !== 'string') throw new TypeError('not a string');
  const t = text.trim();
  let m = RE.exec(t);
  if (!m) { const r = RE2.exec(t); if (r) m = [r[0], r[2], r[1], r[3]]; }
  if (t === '' || !m) throw new TypeError(`bad duration: ${text}`);
  const [, h, mi, s] = m;
  return Number(h ?? 0) * 3600 + Number(mi ?? 0) * 60 + Number(s ?? 0);
}
