#!/usr/bin/env python3
"""Configure as bibliotecas existentes do Jellyfin e sincronize-as com o Seerr."""

import json
import time
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "jellyfin"
JELLYFIN_URL = "http://127.0.0.1:8096"
SEERR_URL = "http://192.168.250.10:5055/api/v1/"
LIBRARIES = (
    ("Lab - Filmes", "movies", "/lab-media/filmes"),
    ("Lab - Séries", "tvshows", "/lab-media/series"),
)
LIBRARY_OPTIONS = {
    "EnableRealtimeMonitor": True,
    "SaveLocalMetadata": False,
    "MetadataSavers": [],
    "EnableChapterImageExtraction": False,
    "ExtractChapterImagesDuringLibraryScan": False,
    "EnableTrickplayImageExtraction": False,
    "ExtractTrickplayImagesDuringLibraryScan": False,
    "EnableLUFSScan": False,
    "PreferredMetadataLanguage": "pt",
    "MetadataCountryCode": "BR",
}


def jellyfin_api(session, method, path, **kwargs):
    """Envie uma solicitação autenticada ao servidor Jellyfin existente."""
    response = session.request(
        method,
        f"{JELLYFIN_URL}/{path}",
        timeout=30,
        **kwargs,
    )
    response.raise_for_status()
    return response.json() if response.content else None


def configure_jellyfin_libraries(session):
    """Crie as bibliotecas do laboratório se faltarem e solicite uma atualização."""
    server_info = jellyfin_api(session, "GET", "System/Info")
    assert server_info["Version"].startswith("12.4")

    existing_libraries = jellyfin_api(session, "GET", "Library/VirtualFolders")
    for name, collection_type, path in LIBRARIES:
        path_is_registered = any(
            path in library.get("Locations", []) for library in existing_libraries
        )
        if path_is_registered:
            continue

        jellyfin_api(
            session,
            "POST",
            "Library/VirtualFolders",
            params={
                "name": name,
                "collectionType": collection_type,
                "paths": path,
                "refreshLibrary": "false",
            },
            json={"LibraryOptions": LIBRARY_OPTIONS},
        )

    jellyfin_api(session, "POST", "Library/Refresh")
    return server_info


def create_seerr_session(api_key):
    """Crie uma sessão de API sem herdar proxies configurados no host."""
    session = requests.Session()
    session.trust_env = False
    session.headers["X-Api-Key"] = api_key
    return session


def wait_for_seerr(session):
    """Aguarde o Seerr responder depois que a VM iniciar."""
    for _ in range(120):
        try:
            response = session.get(f"{SEERR_URL}auth/me", timeout=3)
            if response.ok:
                return response
        except requests.RequestException:
            pass
        time.sleep(2)

    raise RuntimeError(
        "Seerr ainda não disponível; executar este configurador novamente "
        "após o boot da VM"
    )


def connect_seerr_libraries(
    jellyfin_session,
    seerr_session,
    jellyfin_info,
    seerr_user,
):
    """Confirme as identidades existentes e habilite as duas bibliotecas do lab."""
    users = jellyfin_api(jellyfin_session, "GET", "Users")
    assert seerr_user["jellyfinUserId"] in {user["Id"] for user in users}, (
        "Identidade do usuário mudou"
    )

    # Consulte no Seerr o servidor Jellyfin selecionado e os IDs das bibliotecas.
    response = seerr_session.get(f"{SEERR_URL}settings/jellyfin", timeout=15)
    response.raise_for_status()
    assert response.json()["serverId"] == jellyfin_info["Id"], (
        "Identidade do servidor mudou"
    )

    response = seerr_session.post(
        f"{SEERR_URL}settings/jellyfin/library/sync",
        timeout=45,
    )
    response.raise_for_status()
    libraries = response.json()

    for library in libraries:
        if library.get("name") not in {name for name, _, _ in LIBRARIES}:
            continue

        response = seerr_session.put(
            f"{SEERR_URL}settings/jellyfin/library/{library['id']}",
            json={"enabled": True},
            timeout=20,
        )
        response.raise_for_status()

    return len(users)


def main():
    jellyfin_credentials = json.loads(
        (ROOT / "secrets/jellyfin-host.json").read_text()
    )
    jellyfin_session = requests.Session()
    jellyfin_session.trust_env = False
    jellyfin_session.headers["Authorization"] = (
        'MediaBrowser Client="Lab", Device="Fedora", DeviceId="lab-sync", '
        'Version="1", Token="'
        + jellyfin_credentials["api_key"]
        + '"'
    )

    jellyfin_info = configure_jellyfin_libraries(jellyfin_session)

    media_credentials = json.loads(
        (ROOT / "secrets/media-stack.json").read_text()
    )
    seerr_session = create_seerr_session(media_credentials["seerr_key"])
    seerr_user = wait_for_seerr(seerr_session).json()
    user_count = connect_seerr_libraries(
        jellyfin_session,
        seerr_session,
        jellyfin_info,
        seerr_user,
    )

    result = {
        "version": jellyfin_info["Version"],
        "server_id_preserved": True,
        "user_mapping_preserved": True,
        "users": user_count,
        "library_names": [name for name, _, _ in LIBRARIES],
        "config_in_lab": True,
        "media_read_only": True,
    }
    output = BASE / "runtime/applied.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        "Jellyfin "
        + jellyfin_info["Version"]
        + ": identidade e usuários preservados; bibliotecas do lab conectadas ao Seerr."
    )


if __name__ == "__main__":
    main()
