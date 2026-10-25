import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseDuration } from './duration.mjs';

test('hidden valid', () => {
  assert.equal(parseDuration('1h30m'), 5400);
  assert.equal(parseDuration('90s'), 90);
  assert.equal(parseDuration('2h'), 7200);
  assert.equal(parseDuration('1h0m5s'), 3605);
  assert.equal(parseDuration('  45m '), 2700);
  assert.equal(parseDuration('0s'), 0);
});
test('hidden invalid', () => {
  for (const bad of ['', '   ', '5', '1x', '1.5h', '-1h', '30m1h', '1h1h', 'h']) {
    assert.throws(() => parseDuration(bad), TypeError, bad);
  }
});
