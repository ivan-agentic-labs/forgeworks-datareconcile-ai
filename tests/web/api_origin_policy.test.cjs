const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('apps/web/app.js', 'utf8').split('function errorMessage')[0];

function browserContext(pageOrigin, apiOrigin) {
  const requests = [];
  const context = vm.createContext({
    URL,
    location: { origin: pageOrigin },
    document: {
      getElementById(id) {
        return { value: id === 'baseUrl' ? apiOrigin : id === 'token' ? 'scoped-token' : '' };
      },
    },
    fetch: async (url, options) => {
      requests.push({url, options});
      return new Response('{"status":"ok"}', { status: 200 });
    },
  });
  vm.runInContext(source, context);
  return { context, requests };
}

test('same-origin HTTPS requests keep the token on its configured origin', async () => {
  const { context, requests } = browserContext('https://reconcile.example', 'https://reconcile.example/');
  const value = await vm.runInContext("api('/healthz')", context);
  assert.equal(value.status, 'ok');
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, 'https://reconcile.example/healthz');
  assert.equal(requests[0].options.headers.Authorization, 'Bearer scoped-token');
});

test('cross-origin host is rejected before bearer token is transmitted', async () => {
  const { context, requests } = browserContext('https://reconcile.example', 'https://attacker.example');
  await assert.rejects(vm.runInContext("api('/healthz')", context), /API_ORIGIN_NOT_ALLOWED/);
  assert.equal(requests.length, 0);
});

test('plain HTTP external hosts are rejected even on the same origin', async () => {
  const { context, requests } = browserContext('http://reconcile.example', 'http://reconcile.example');
  await assert.rejects(vm.runInContext("api('/healthz')", context), /API_HTTPS_REQUIRED/);
  assert.equal(requests.length, 0);
});

test('local development may use explicit loopback ports', async () => {
  const { context, requests } = browserContext('http://127.0.0.1:8080', 'http://localhost:8000');
  await vm.runInContext("api('/healthz')", context);
  assert.equal(requests[0].url, 'http://localhost:8000/healthz');
});

test('URL credentials and query fragments cannot change request origin', async () => {
  for (const origin of ['https://user:pass@reconcile.example', 'https://reconcile.example/?token=leak', 'https://reconcile.example/path']) {
    const { context, requests } = browserContext('https://reconcile.example', origin);
    await assert.rejects(vm.runInContext("api('/healthz')", context), /API_ORIGIN_NOT_ALLOWED/);
    assert.equal(requests.length, 0);
  }
});
