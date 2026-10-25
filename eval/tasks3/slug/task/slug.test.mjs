import { test } from 'node:test';
import assert from 'node:assert/strict';
import { slugify } from './slug.mjs';

test('lowercases words', () => {
  assert.equal(slugify('Hello'), 'hello');
});

test('replaces a space', () => {
  assert.equal(slugify('hello world'), 'hello-world');
});
