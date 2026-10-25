import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseQuery } from './query.mjs';

test('simple pairs', () => {
  assert.deepEqual(parseQuery('a=1&b=two'), { a: '1', b: 'two' });
});
