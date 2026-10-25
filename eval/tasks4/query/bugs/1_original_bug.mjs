export function parseQuery(qs) {
  const out = {};
  for (const part of qs.split('&')) {
    const [key, value] = part.split('=');
    out[decodeURIComponent(key)] = decodeURIComponent(value);
  }
  return out;
}
