const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'];

export function formatBytes(n) {
  let i = 0;
  while (n > 1024 && i < UNITS.length - 1) {
    n /= 1024;
    i++;
  }
  return i === 0 ? `${n} B` : `${n.toFixed(1)} ${UNITS[i]}`;
}
