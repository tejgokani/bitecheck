import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatBytes } from './bytes.mjs';

test('small values are bytes', () => {
  assert.equal(formatBytes(512), '512 B');
});

test('megabytes', () => {
  assert.equal(formatBytes(5 * 1024 * 1024), '5.0 MB');
});
