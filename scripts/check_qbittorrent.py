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
EXPECTED_PREFERENCES = {
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
    'max_active_downloads': 4,
    'max_active_torrents': 6,
    'max_active_uploads': 2,
    'up_limit': 262144,
    'lsd': False,
    'autorun_enabled': False,
    'excluded_file_names_enabled': True,
}


def connect():
    password = (ROOT / 'secrets/qbittorrent-password').read_text().strip()
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    data = urllib.parse.urlencode(
        {'username': 'admin', 'password': password}
    ).encode()
    request = urllib.request.Request(
        BASE + '/api/v2/auth/login',
        data=data,
        headers=HEADERS,
    )
    response = opener.open(request, timeout=8)
    if response.read() != b'Ok.':
        raise RuntimeError('Login do painel falhou.')
    return opener


def request(opener, method, data=None):
    payload = urllib.parse.urlencode(data).encode() if data is not None else None
    request = urllib.request.Request(
        BASE + '/api/v2/' + method,
        data=payload,
        headers=HEADERS,
    )
    return opener.open(request, timeout=15).read()


def main():
    try:
        urllib.request.urlopen(BASE + '/api/v2/app/preferences', timeout=8)
    except urllib.error.HTTPError as error:
        assert error.code == 403
    else:
        raise RuntimeError('API acessível sem autenticação.')
    client = connect()
    preferences = json.loads(request(client, 'app/preferences'))
    for key, value in EXPECTED_PREFERENCES.items():
        actual = preferences[key]
        if key in ('save_path', 'temp_path'):
            actual = actual.rstrip('/')
        assert actual == value, (key, preferences[key], value)
    result = {
        'version': request(client, 'app/version').decode(),
        'authentication_required': True,
        'preferences': EXPECTED_PREFERENCES,
    }
    report = ROOT / 'state/qbittorrent-check.json'
    report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
