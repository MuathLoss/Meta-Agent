"""Read-only health monitor. Nonzero exit integrates with any later scheduler."""
import json
import sys
import urllib.request
base = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8088').rstrip('/')
checks = [('/', None), ('/api/health', 'ok'), ('/api/health/ready', 'ready')]
failed = False
for path, status in checks:
    try:
        with urllib.request.urlopen(base + path, timeout=5) as response:
            if response.status != 200 or (status and json.load(response).get('status') != status):
                raise ValueError('unhealthy')
        print('PASS', path)
    except Exception:
        failed = True
        print('FAIL', path, '(unavailable or unhealthy)')
sys.exit(1 if failed else 0)
