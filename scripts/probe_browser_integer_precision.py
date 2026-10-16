"""Real Chromium + HTTP verification of synthetic integer response transport."""
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
AMOUNT = 9223372036854775807
TOTAL = AMOUNT * 2
TOTALS = {key: TOTAL for key in ('left_total_minor', 'right_total_minor', 'allocated_total_minor')} | {'source_unbalanced_minor': 0, 'conservation_discrepancy_minor': 0, 'open_exception_count': 0}


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/v1/import-batches/proof/rows':
            value = {'items': [{'amount_minor': AMOUNT}, {'amount_minor': AMOUNT}]}
        elif self.path == '/v1/reports/proof-report/download':
            value = {'totals': TOTALS, 'expires_at': 'synthetic', 'download_url': '/unused'}
        elif self.path == '/v1/auth/config':
            value = {'enabled': False}
        else:
            return super().do_GET()
        self.reply(value)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path == "/v1/import-batches":
            value = {"id": "proof", "source_label": "browser-proof", "row_count": 2, "currency": "USD"}
        elif self.path == "/v1/reconciliation-runs":
            value = {"id": "proof-run", "status": "MATCHED", "unmatched_count": 0, "version": 1}
        elif self.path == "/v1/reconciliation-runs/proof-run/finalize":
            value = {"id": "proof-report", "totals": TOTALS, "ledger_sha256": "synthetic"}
        else:
            self.send_error(404)
            return
        self.reply(value)

    def reply(self, value):
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT / 'apps/web')))
thread = Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(f'http://127.0.0.1:{server.server_port}/index.html')
        page.locator('#baseUrl').fill(f'http://127.0.0.1:{server.server_port}')
        # Synthetic fixture identities belong in the test, never as defaults
        # presented to a real reviewer or report approver.
        page.locator('#sourceLabel').fill('browser-proof')
        page.locator('#artifactId').fill('33333333-3333-3333-3333-333333333333')
        page.locator('#fileSha').fill('a' * 64)
        page.locator('#importForm button[type=submit]').click()
        expect(page.locator('#rowsButton')).to_be_enabled()
        page.locator('#rowsButton').click()
        expect(page.locator('#rowSummary')).to_contain_text(f'{TOTAL:,}')
        assert f'{TOTAL:,}' in page.locator('#rowSummary').inner_text()
        page.locator('#rightBatchId').fill('proof')
        page.locator('#reconcileForm button[type=submit]').click()
        expect(page.locator('#runStatus')).to_contain_text('MATCHED')
        page.locator('#summarySha').fill('c' * 64)
        page.locator('#finalizeForm button[type=submit]').click()
        expect(page.locator('#reportBox')).to_contain_text('Report finalized')
        expect(page.locator('#rowSummary')).to_contain_text(f'{TOTAL:,}')
        assert f'{TOTAL:,}' in page.locator('#rowSummary').inner_text()
        assert not errors, errors
        print(json.dumps({'result': 'PASS', 'browser': browser.version, 'amount_minor': str(AMOUNT),
                          'total_minor': str(TOTAL), 'javascript_errors': errors,
                          'scope': 'Actual console, Chromium fetch and DOM over synthetic local HTTP; no staging/customer acceptance'}))
        browser.close()
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
