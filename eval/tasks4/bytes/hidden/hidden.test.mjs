import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatBytes } from './bytes.mjs';

test('hidden', () => {
  assert.equal(formatBytes(0), '0 B');
  assert.equal(formatBytes(1023), '1023 B');
  assert.equal(formatBytes(1024), '1.0 KB');
  assert.equal(formatBytes(1048576), '1.0 MB');
  assert.equal(formatBytes(1024 ** 4), '1.0 TB');
  assert.equal(formatBytes(1024 ** 5), '1024.0 TB');
  assert.throws(() => formatBytes(-1), RangeError);
});
