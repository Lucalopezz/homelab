#!/usr/bin/env python3
"""Finalize as integrações do Seerr após o login do usuário no Jellyfin."""

import json
from pathlib import Path

import requests


ROOT = Path("/opt/media-stack")
API_URL = "http://192.168.250.10:5055/api/v1/"
APPLICATIONS = (
    ("sonarr", 8989, "series"),
    ("radarr", 7878, "filmes"),
)


def create_session(api_key):
    """Crie uma sessão autenticada do Seerr sem proxies do ambiente."""
    session = requests.Session()
    session.trust_env = False
    session.headers["X-Api-Key"] = api_key
    return session


def seerr_api(session, method, path, payload=None):
    response = session.request(
        method,
        API_URL + path,
        json=payload,
        timeout=45,
    )
    if response.status_code in (401, 403):
        raise SystemExit("Aguardando login inicial do Jellyfin na interface do Seerr.")
    if not response.ok:
        raise RuntimeError(f"Seerr {path}: HTTP {response.status_code}")
    return response.json() if response.content else None


def application_settings(name, port, directory, config):
    response = requests.get(
        f"http://192.168.250.10:{port}/api/v3/qualityprofile",
        headers={"X-Api-Key": config[name + "_key"]},
        timeout=15,
    )
    profiles = response.json()
    profile = next(item for item in profiles if item["name"].startswith("Lab -"))

    settings = {
        "name": name.capitalize() + " lab",
        "hostname": name,
        "port": port,
        "apiKey": config[name + "_key"],
        "useSsl": False,
        "baseUrl": "",
        "activeProfileId": profile["id"],
        "activeProfileName": profile["name"],
        "activeDirectory": "/data/biblioteca/" + directory,
        "is4k": False,
        "isDefault": True,
        "tags": [],
        "syncEnabled": True,
        "preventSearch": False,
        "tagRequests": False,
        "overrideRule": [],
    }

    if name == "sonarr":
        settings.update(
            {
                "seriesType": "standard",
                "animeSeriesType": "anime",
                "activeAnimeProfileId": profile["id"],
                "activeAnimeProfileName": profile["name"],
                "activeAnimeDirectory": "/data/biblioteca/series",
                "animeTags": [],
                "enableSeasonFolders": True,
                "monitorNewItems": "all",
            }
        )
    else:
        settings["minimumAvailability"] = "released"

    return settings


def configure_application(session, name, port, directory, config):
    existing_settings = seerr_api(session, "GET", "settings/" + name)
    configured_name = name.capitalize() + " lab"
    if any(item["name"] == configured_name for item in existing_settings):
        return

    settings = application_settings(name, port, directory, config)
    seerr_api(session, "POST", "settings/" + name + "/test", settings)
    seerr_api(session, "POST", "settings/" + name, settings)
    print(name + ": teste de conexão do Seerr concluído.", flush=True)


def main():
    config = json.loads((ROOT / "credentials.json").read_text())
    session = create_session(config["seerr_key"])

    seerr_api(session, "GET", "auth/me")
    for name, port, directory in APPLICATIONS:
        configure_application(session, name, port, directory, config)

    seerr_api(
        session,
        "POST",
        "settings/main",
        {
            "applicationTitle": "Lab - Filmes e Séries",
            "applicationUrl": "http://192.168.250.10:5055",
            "locale": "pt-BR",
            "discoverRegion": "BR",
            "streamingRegion": "BR",
            "partialRequestsEnabled": True,
            "enableSpecialEpisodes": False,
            "newPlexLogin": False,
        },
    )
    seerr_api(session, "POST", "settings/initialize")
    print("Seerr pronto para procurar e solicitar filmes, temporadas e episódios.")


if __name__ == "__main__":
    main()
