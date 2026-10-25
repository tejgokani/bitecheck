export function parseQuery(qs) {
  const out = {};
  for (const part of qs.split('&')) {
    if (part === '') continue;
    const eq = part.lastIndexOf('=');
    const rawKey = eq === -1 ? part : part.slice(0, eq);
    const rawValue = eq === -1 ? '' : part.slice(eq + 1);
    const decode = (s) => decodeURIComponent(s.replace(/\+/g, ' '));
    out[decode(rawKey)] = decode(rawValue);
  }
  return out;
}
