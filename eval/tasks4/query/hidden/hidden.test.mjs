import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseQuery } from './query.mjs';

test('hidden', () => {
  assert.deepEqual(parseQuery('q=hello+world&flag&x=a%3Db'), { q: 'hello world', flag: '', x: 'a=b' });
  assert.deepEqual(parseQuery('a=1&&b=2'), { a: '1', b: '2' });
  assert.deepEqual(parseQuery(''), {});
  assert.deepEqual(parseQuery('k=a=b'), { k: 'a=b' });
});
