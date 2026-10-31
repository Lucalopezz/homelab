#!/usr/bin/env python3
"""Dentro da VM: aprova hashes da biblioteca organizada para coleta SFTP."""

import fcntl, hashlib, importlib.util, json, os, sqlite3, tempfile, time
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "triage", "/opt/media-stack/triage/triage.py"
)
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
ROOT = Path("/srv/downloads/biblioteca")
STATE = Path("/var/lib/jellyfin-export")
t.RAW = ROOT


def safe(path):
    parts = t.safe_parts(path)
    if parts[0] not in ("filmes", "series") or any(
        x.startswith(".") or any(c in x for c in "\"'") for x in parts
    ):
        raise ValueError("Caminho de biblioteca recusado")
    return parts


def main(only_prefix=None):
    if only_prefix is not None:
        safe(only_prefix + "/sentinela.mp4")
    db = sqlite3.connect("file:/var/lib/media-triage/state.sqlite3?mode=ro", uri=True)
    approved = set()
    for status, raw in db.execute("SELECT status,details FROM items"):
        if status in ("aprovado", "pendente-importacao"):
            approved.update(
                digest
                for name, digest in json.loads(raw).get("files", {}).items()
                if Path(name).suffix.lower() in t.VIDEO
            )
    db.close()
    daily = list(Path("/var/lib/clamav").glob("daily.c[lv]d"))
    signature = max((p.stat().st_mtime_ns for p in daily), default=0)
    if signature < (time.time() - 7 * 86400) * 1e9:
        raise RuntimeError("Assinaturas ausentes ou antigas")
    cache_path = STATE / "cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    files = []
    newcache = {}
    rejected = []
    for section in ("filmes", "series"):
        for parent, dirs, names in os.walk(ROOT / section, followlinks=False):
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".") and not (Path(parent) / d).is_symlink()
            ]
            for name in sorted(names):
                source = Path(parent) / name
                relative = source.relative_to(ROOT).as_posix()
                if only_prefix is not None and not relative.startswith(
                    only_prefix + "/"
                ):
                    continue
                if source.suffix.lower() not in t.VIDEO | t.SUBTITLE:
                    continue
                try:
                    safe(relative)
                    fd = t.open_source(source)
                    try:
                        stamp = list(t.stamp(os.fstat(fd)))
                    finally:
                        os.close(fd)
                    old = cache.get(relative)
                    if old and old["stamp"] == stamp and old["signature"] == signature:
                        digest = old["sha256"]
                        if source.suffix.lower() in t.VIDEO and digest not in approved:
                            raise ValueError("Vídeo sem aprovação vigente da triagem")
                    elif source.suffix.lower() in t.VIDEO:
                        # O vídeo já passou por AV e ffprobe na triagem. Reutilizar o resultado
                        # somente para bytes idênticos; a coleta confere novamente o mesmo SHA256.
                        fd = t.open_source(source)
                        try:
                            before = os.fstat(fd)
                            if before.st_size > t.MAX_BYTES:
                                raise t.Review("Arquivo acima do limite individual")
                            digest_builder = hashlib.sha256()
                            while chunk := os.read(fd, 1024 * 1024):
                                digest_builder.update(chunk)
                            if t.stamp(before) != t.stamp(os.fstat(fd)):
                                raise t.Rejected("Origem mudou durante a conferência")
                            digest = digest_builder.hexdigest()
                        finally:
                            os.close(fd)
                        if digest not in approved:
                            raise ValueError(
                                "Vídeo não corresponde a uma cópia aprovada pela triagem"
                            )
                    else:
                        with tempfile.TemporaryDirectory(dir=STATE) as folder:
                            target = Path(folder) / source.name
                            digest = t.copy_source(source, target)
                            t.scan(target)
                            t.validate_media(target)
                    newcache[relative] = {
                        "stamp": stamp,
                        "signature": signature,
                        "sha256": digest,
                    }
                    files.append(
                        {
                            "path": relative,
                            "size": stamp[1],
                            "sha256": digest,
                            "kind": "video"
                            if source.suffix.lower() in t.VIDEO
                            else "subtitle",
                        }
                    )
                except Exception as error:
                    rejected.append({"path": relative, "reason": str(error)[:500]})
    # Legendas só acompanham um vídeo aprovado com o mesmo nome base.
    videos = [Path(f["path"]) for f in files if f["kind"] == "video"]
    files = [
        f
        for f in files
        if f["kind"] == "video"
        or any(
            Path(f["path"]).parent == v.parent
            and Path(f["path"]).name.startswith(v.stem + ".")
            for v in videos
        )
    ]
    if only_prefix is not None:
        old_manifest = ROOT / ".publicacao/manifest.json"
        previous = (
            json.loads(old_manifest.read_text())["files"]
            if old_manifest.exists()
            else []
        )
        files = files + [
            f for f in previous if not f["path"].startswith(only_prefix + "/")
        ]
        newcache = {**cache, **newcache}
    manifest = {"schema": 1, "generated_at": t.now(), "files": files}
    target = ROOT / ".publicacao/manifest.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    tmp.chmod(0o440)
    tmp.replace(target)
    (STATE / "cache.json").write_text(json.dumps(newcache) + "\n")
    (STATE / "report.json").write_text(
        json.dumps(
            {"published": len(files), "held": rejected}, ensure_ascii=False, indent=2
        )
        + "\n"
    )
    print(json.dumps({"published": len(files), "held": len(rejected)}))


if __name__ == "__main__":
    import sys

    with (STATE / "export.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        main(sys.argv[1] if len(sys.argv) > 1 else None)
