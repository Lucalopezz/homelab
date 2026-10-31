#!/usr/bin/env python3
"""Fixture sintética para o teste Jellyfin; somente dentro da VM."""

import base64, hashlib, json, os, shutil, sqlite3, subprocess, sys, time
from pathlib import Path
import requests

assert os.geteuid() == 0 and os.uname().nodename == "lab-downloads"
record = Path("/opt/jellyfin-export/flow-fixture.json")
c = json.loads(Path("/opt/media-stack/credentials.json").read_text())
s = requests.Session()
s.trust_env = False
s.headers["Referer"] = "http://192.168.250.10:8080/"
base = "http://192.168.250.10:8080/api/v2/"
assert (
    s.post(
        base + "auth/login",
        data={"username": "admin", "password": c["qbit_password"]},
        timeout=15,
    ).text
    == "Ok."
)


def encode(v):
    if isinstance(v, int):
        return b"i" + str(v).encode() + b"e"
    if isinstance(v, str):
        v = v.encode()
    if isinstance(v, bytes):
        return str(len(v)).encode() + b":" + v
    if isinstance(v, dict):
        return b"d" + b"".join(encode(k) + encode(v[k]) for k in sorted(v)) + b"e"


def unit(name):
    subprocess.run(["systemctl", "start", name], check=True, timeout=900)


if sys.argv[1] == "prepare":
    assert not record.exists(), "Fixture anterior pendente; conferir antes de repetir"
    name = "Lab.Validacao.Jellyfin." + str(int(time.time()))
    raw = Path("/srv/downloads/recebidos") / name
    lib = Path("/srv/downloads/biblioteca/filmes") / name
    assert not raw.exists() and not lib.exists()
    raw.mkdir(mode=0o750)
    os.chown(raw, 1001, 1001)
    video = raw / (name + ".mp4")
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1280x720:r=10",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-t",
            "12",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(video),
        ],
        check=True,
        timeout=90,
    )
    os.chown(video, 1001, 1001)
    video.chmod(0o640)
    data = video.read_bytes()
    info = {
        "length": len(data),
        "name": video.name,
        "piece length": 262144,
        "pieces": b"".join(
            hashlib.sha1(data[i : i + 262144]).digest()
            for i in range(0, len(data), 262144)
        ),
    }
    h = hashlib.sha1(encode(info)).hexdigest()
    result = {
        "hash": h,
        "raw": str(raw),
        "directory": str(lib),
        "relative": "filmes/" + name,
        "filename": video.name,
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    record.write_text(json.dumps(result) + "\n")
    r = s.post(
        base + "torrents/add",
        files={
            "torrents": (
                "lab-test.torrent",
                encode({"announce": "http://127.0.0.1:9/announce", "info": info}),
            )
        },
        data={"savepath": str(raw), "category": "manual", "autoTMM": "false"},
        timeout=20,
    )
    assert r.text == "Ok."
    for _ in range(30):
        torrents = s.get(
            base + "torrents/info", params={"hashes": h}, timeout=10
        ).json()
        if torrents and torrents[0]["progress"] == 1:
            break
        time.sleep(2)
    else:
        raise RuntimeError("Fixture não foi reconhecida pelo cliente")
    code = (
        "import importlib.util,json; s=importlib.util.spec_from_file_location('t','/opt/media-stack/triage/triage.py'); t=importlib.util.module_from_spec(s);s.loader.exec_module(t); p=t.Pipeline(); a=next(x for x in p.qget('torrents/info') if x['hash']=='"
        + h
        + "');p.process(a)"
    )
    subprocess.run(
        ["runuser", "-u", "triagem", "--", "python3", "-c", code],
        check=True,
        timeout=900,
    )
    db = sqlite3.connect("/var/lib/media-triage/state.sqlite3")
    row = db.execute("SELECT status,details FROM items WHERE hash=?", (h,)).fetchone()
    db.close()
    assert row and row[0] == "aprovado", row
    result["approved"] = json.loads(row[1])["destination"]
    record.write_text(json.dumps(result) + "\n")
    lib.mkdir(mode=0o2750)
    os.chown(lib, 1100, 1100)
    shutil.copyfile(video, lib / video.name)
    os.chown(lib / video.name, 1100, 1100)
    (lib / video.name).chmod(0o640)
    subtitle = lib / (video.stem + ".pt-BR.srt")
    subtitle.write_text(
        "1\n00:00:00,000 --> 00:00:10,000\nVídeo sintético de validação do laboratório.\n"
    )
    os.chown(subtitle, 1100, 1100)
    subtitle.chmod(0o640)
    bad = lib / (video.stem + ".en.srt")
    bad.write_bytes(
        base64.b64decode(
            "WDVPIVAlQEFQWzRcUFpYNTQoUF4pN0NDKTd9JEVJQ0FSLVNUQU5EQVJELUFOVElWSVJVUy1URVNULUZJTEUhJEgrSCo="
        )
    )
    os.chown(bad, 1100, 1100)
    bad.chmod(0o640)
    subprocess.run(
        [
            "runuser",
            "-u",
            "triagem",
            "--",
            "python3",
            "/opt/jellyfin-export/export-manifest.py",
            result["relative"],
        ],
        check=True,
        timeout=900,
    )
    manifest = json.loads(
        Path("/srv/downloads/biblioteca/.publicacao/manifest.json").read_text()
    )
    entries = [
        f for f in manifest["files"] if f["path"].startswith(result["relative"] + "/")
    ]
    assert len(entries) == 2 and not any(f["path"].endswith(".en.srt") for f in entries)
    print(json.dumps(result))
elif sys.argv[1] == "cleanup":
    if record.exists():
        d = json.loads(record.read_text())
        s.post(
            base + "torrents/delete",
            data={"hashes": d["hash"], "deleteFiles": "false"},
            timeout=15,
        ).raise_for_status()
        for key, basepath in [
            ("raw", Path("/srv/downloads/recebidos")),
            ("directory", Path("/srv/downloads/biblioteca/filmes")),
            ("approved", Path("/srv/downloads/aprovados/manuais")),
        ]:
            if key in d:
                p = Path(d[key])
                assert p.is_relative_to(basepath) and p != basepath
                if p.exists():
                    shutil.rmtree(p)
        db = sqlite3.connect("/var/lib/media-triage/state.sqlite3")
        db.execute("DELETE FROM items WHERE hash=?", (d["hash"],))
        db.commit()
        db.close()
        record.unlink()
        subprocess.run(
            [
                "runuser",
                "-u",
                "triagem",
                "--",
                "python3",
                "/opt/jellyfin-export/export-manifest.py",
                d["relative"],
            ],
            check=True,
            timeout=900,
        )
    print("Fixture removida")
else:
    raise SystemExit("Ação desconhecida")
