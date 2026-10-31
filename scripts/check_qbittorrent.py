#!/usr/bin/env python3
"""Confere painel, autenticação e preferências; não altera o cliente."""
import http.cookiejar
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://192.168.250.10:8080'
HEADERS = {'Origin': BASE, 'Referer': BASE + '/'}

def connect():
    password = (ROOT / 'secrets/qbittorrent-password').read_text().strip()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    data = urllib.parse.urlencode({'username': 'admin', 'password': password}).encode()
    response = opener.open(urllib.request.Request(
        BASE + '/api/v2/auth/login', data=data, headers=HEADERS), timeout=8)
    if response.read() != b'Ok.':
        raise RuntimeError('Login do painel falhou.')
    return opener

def request(opener, method, data=None):
    payload = urllib.parse.urlencode(data).encode() if data is not None else None
    return opener.open(urllib.request.Request(
        BASE + '/api/v2/' + method, data=payload, headers=HEADERS), timeout=15).read()

if __name__ == '__main__':
    try:
        urllib.request.urlopen(BASE + '/api/v2/app/preferences', timeout=8)
    except urllib.error.HTTPError as error:
        assert error.code == 403
    else:
        raise RuntimeError('API acessível sem autenticação.')
    client = connect()
    preferences = json.loads(request(client, 'app/preferences'))
    expected = {
        'save_path': '/srv/downloads/recebidos',
        'temp_path': '/srv/downloads/incompletos',
        'temp_path_enabled': True,
        'upnp': False,
        'web_ui_upnp': False,
        'bypass_local_auth': False,
        'bypass_auth_subnet_whitelist_enabled': False,
        'web_ui_csrf_protection_enabled': True,
        'web_ui_host_header_validation_enabled': True,
        'queueing_enabled': True,
        'max_active_downloads': 2,
        'up_limit': 262144,
        'lsd': False,
        'autorun_enabled': False,
        'excluded_file_names_enabled': True,
    }
    for key, value in expected.items():
        actual = preferences[key]
        if key in ('save_path', 'temp_path'):
            actual = actual.rstrip('/')
        assert actual == value, (key, preferences[key], value)
    result = {'version': request(client, 'app/version').decode(),
              'authentication_required': True, 'preferences': expected}
    (ROOT / 'state/qbittorrent-check.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
