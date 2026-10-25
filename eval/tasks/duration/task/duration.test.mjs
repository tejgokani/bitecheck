import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseDuration } from './duration.mjs';

test('is exported', () => {
  assert.equal(typeof parseDuration, 'function');
});
