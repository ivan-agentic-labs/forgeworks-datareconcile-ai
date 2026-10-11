"""Real Chromium + HTTP verification of synthetic integer response transport."""
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
AMOUNT = 9223372036854775807
TOTAL = AMOUNT * 2


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/v1/import-batches/proof/rows':
            value = {'items': [{'amount_minor': AMOUNT}, {'amount_minor': AMOUNT}]}
        elif self.path == '/proof/report':
            value = {'totals': {key: TOTAL for key in ('left_total_minor', 'right_total_minor', 'allocated_total_minor')}
                     | {'source_unbalanced_minor': 0, 'conservation_discrepancy_minor': 0, 'open_exception_count': 0}}
        elif self.path == '/v1/auth/config':
            value = {'enabled': False}
        else:
            return super().do_GET()
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
        page.evaluate("async () => { state.batches.left = {id: 'proof'}; await loadRows(); }")
        assert f'{TOTAL:,}' in page.locator('#rowSummary').inner_text()
        values = page.evaluate("async () => { const report = await api('/proof/report'); renderMetrics(report.totals); return report.totals; }")
        assert values['left_total_minor'] == str(TOTAL)
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
