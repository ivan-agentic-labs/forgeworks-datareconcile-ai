const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('apps/web/app.js', 'utf8').split('function errorMessage')[0];
function consoleContext(body, status = 200, legacy = false) {
  const context = vm.createContext({
    document: {getElementById: (id) => ({value: id === 'baseUrl' ? 'https://example.invalid' : ''})},
    fetch: async () => new Response(body, {status}),
    ...(legacy ? {JSON: {parse: (text, reviver) => JSON.parse(text, (key, value) => reviver(key, value))}} : {}),
  });
  vm.runInContext(source, context);
  return context;
}
for (const amount of ['9007199254740993', '-9007199254740993', '9223372036854775807', '-9223372036854775808', '18446744073709551614']) {
  test(`API preserves exact amount ${amount}`, async () => {
    const context = consoleContext(`{"items":[{"amount_minor":${amount}}],"totals":{"left_total_minor":${amount}},"version":2}`);
    const data = await vm.runInContext("api('/v1/report')", context);
    assert.equal(String(data.items[0].amount_minor), amount);
    assert.equal(String(data.totals.left_total_minor), amount);
    assert.equal(data.version, 2);
    context.data = data;
    assert.equal(vm.runInContext('BigInt(data.items[0].amount_minor) + BigInt(data.items[0].amount_minor)', context), BigInt(amount) * 2n);
  });
}
test('safe integers, strings and decimals retain their JSON types', async () => {
  const data = await vm.runInContext("api('/v1/report')", consoleContext('{"count":9007199254740991,"fraction":0.25,"label":"9007199254740993","ok":true}'));
  assert.equal(data.count, Number.MAX_SAFE_INTEGER);
  assert.equal(data.fraction, 0.25);
  assert.equal(data.label, '9007199254740993');
  assert.equal(data.ok, true);
});
for (const body of ['{invalid', '{"amount_minor":1e20}', '{"amount_minor":1e400}']) {
  test(`successful malformed or unsafe response fails closed: ${body}`, async () => {
    await assert.rejects(vm.runInContext("api('/v1/report')", consoleContext(body)));
  });
}
test('browser without source context rejects rounded integers', async () => {
  await assert.rejects(vm.runInContext("api('/v1/report')", consoleContext('{"amount_minor":9007199254740993}', 200, true)), /UNSAFE_JSON_NUMBER/);
});
test('HTTP failure retains status even with a non JSON error page', async () => {
  await assert.rejects(vm.runInContext("api('/v1/report')", consoleContext('<html>Unavailable</html>', 503)), (error) => error.status === 503);
});
test('formatter refuses an already rounded numeric amount', () => {
  assert.throws(() => vm.runInContext('formatInteger(9007199254740993)', consoleContext('{}')), /UNSAFE_INTEGER/);
});
