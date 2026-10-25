const RE = /^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$/;

export function parseDuration(text) {
  if (typeof text !== 'string') throw new TypeError('not a string');
  const t = text;
  const m = RE.exec(t);
  if (t === '' || !m) throw new TypeError(`bad duration: ${text}`);
  const [, h, mi, s] = m;
  return Number(h ?? 0) * 3600 + Number(mi ?? 0) * 60 + Number(s ?? 0);
}
