import json, os, re, subprocess, time, sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from settings import load_yaml


_crawl_cfg = load_yaml("crawl.yaml")
_ext_cfg = _crawl_cfg.get("external", {})

DATA_DIR = _crawl_cfg["Path_Data"]
OUT_DIR = f"{DATA_DIR}/external_files"
LOG_PATH = f"{OUT_DIR}/download_log.json"
SESSION = _ext_cfg.get("session", "huflit-sp")
CMD_TIMEOUT = int(_ext_cfg.get("command_timeout", 60))
POLITENESS_DELAY = float(_ext_cfg.get("politeness_delay", 1))

os.makedirs(OUT_DIR, exist_ok=True)


with open(f"{OUT_DIR}/links_manifest.json") as f:
    manifest = json.load(f)

sp_links = manifest["sharepoint"]
gd_links = manifest["google_drive"]

log = {"sharepoint": {}, "google_drive": {}, "stats": {}}


def run_cmd(cmd: str, timeout: int = 60) -> tuple[int, str]:
    """Chạy lệnh shell, trả về (exit_code, output)."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "AGENT_BROWSER_SESSION": SESSION},
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:
        return -1, str(e)


def safe_filename(url: str, source_id: str, idx: int) -> str:
    """Tạo tên file an toàn từ URL."""
    path = urlparse(url).path
    name = unquote(path.split("/")[-1]) if path else ""

    name = re.sub(r'[^\w\-. ]', '_', name).strip()
    if not name or len(name) < 3:
        name = f"file_{source_id}_{idx}"

    base, ext = os.path.splitext(name)
    if not ext:
        ext = ".pdf"
    return f"{source_id}_{base[:60]}{ext}"


def download_sharepoint(url: str, source_id: str, idx: int) -> dict:
    """Tải file SharePoint qua agent-browser."""
    filename = safe_filename(url, source_id, idx)
    out_path = f"{OUT_DIR}/{filename}"

    if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
        return {"status": "skipped", "file": filename, "reason": "already exists"}


    code, out = run_cmd(f'agent-browser open "{url}"', timeout=30)
    if code != 0:
        return {"status": "failed", "file": filename, "reason": f"open failed: {out[:100]}"}

    time.sleep(3)


    code, out = run_cmd("agent-browser snapshot -i", timeout=20)
    if code != 0:
        return {"status": "failed", "file": filename, "reason": f"snapshot failed: {out[:100]}"}


    dl_ref = None
    for line in out.split("\n"):
        if ("Tải tập tin" in line or "Download" in line or "Tải xuống" in line) and "ref=" in line:
            m = re.search(r"ref=(e\d+)", line)
            if m:
                dl_ref = m.group(1)
                break

    if not dl_ref:

        return {"status": "failed", "file": filename, "reason": "no download button found"}


    code, out = run_cmd(f'agent-browser download @{dl_ref} "{out_path}"', timeout=120)
    if code != 0:
        return {"status": "failed", "file": filename, "reason": f"download failed: {out[:100]}"}


    if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
        size = os.path.getsize(out_path)
        return {"status": "ok", "file": filename, "size": size}
    else:
        return {"status": "failed", "file": filename, "reason": "file too small or missing"}


def download_gdrive(url: str, source_id: str, idx: int) -> dict:
    """Tải file Google Drive qua curl."""

    m = re.search(r"/file/d/([^/]+)", url)
    if not m:
        return {"status": "failed", "file": "", "reason": "no file ID in URL"}
    file_id = m.group(1)

    filename = safe_filename(url, source_id, idx)
    out_path = f"{OUT_DIR}/{filename}"

    if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
        return {"status": "skipped", "file": filename, "reason": "already exists"}

    dl_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    code, out = run_cmd(
        f'curl -sL -m 60 -o "{out_path}" -A "Mozilla/5.0" "{dl_url}"',
        timeout=90,
    )

    if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:

        with open(out_path, "rb") as f:
            header = f.read(100)
        if b"<html" in header.lower() or b"<!doctype" in header.lower():
            os.remove(out_path)
            return {"status": "failed", "file": filename, "reason": "got HTML instead of file (virus scan page?)"}
        size = os.path.getsize(out_path)
        return {"status": "ok", "file": filename, "size": size}
    else:
        return {"status": "failed", "file": filename, "reason": "download failed or too small"}


print(f"Bắt đầu tải {len(sp_links)} SharePoint + {len(gd_links)} Google Drive files...")
print(f"Output: {OUT_DIR}")
print("=" * 60)


sp_ok = sp_fail = sp_skip = 0
for i, (url, info) in enumerate(sp_links.items()):
    sid = info["source_id"]
    result = download_sharepoint(url, sid, i)
    log["sharepoint"][url] = {**result, "source_id": sid, "category": info["category"], "title": info["title"][:60]}

    status = result["status"]
    if status == "ok":
        sp_ok += 1
        print(f"  [SP {i+1}/{len(sp_links)}] OK: {result['file']} ({result.get('size',0)//1024}KB)")
    elif status == "skipped":
        sp_skip += 1
    else:
        sp_fail += 1
        print(f"  [SP {i+1}/{len(sp_links)}] FAIL: {result.get('reason','')[:60]} | {info['title'][:40]}")


    if (i + 1) % 10 == 0:
        log["stats"] = {"sp_ok": sp_ok, "sp_fail": sp_fail, "sp_skip": sp_skip}
        with open(LOG_PATH, "w") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)

    time.sleep(POLITENESS_DELAY)


gd_ok = gd_fail = gd_skip = 0
for i, (url, info) in enumerate(gd_links.items()):
    sid = info["source_id"]
    result = download_gdrive(url, sid, i)
    log["google_drive"][url] = {**result, "source_id": sid, "category": info["category"], "title": info["title"][:60]}

    status = result["status"]
    if status == "ok":
        gd_ok += 1
        print(f"  [GD {i+1}/{len(gd_links)}] OK: {result['file']} ({result.get('size',0)//1024}KB)")
    elif status == "skipped":
        gd_skip += 1
    else:
        gd_fail += 1
        print(f"  [GD {i+1}/{len(gd_links)}] FAIL: {result.get('reason','')[:60]} | {info['title'][:40]}")

    time.sleep(0.5)


log["stats"] = {
    "sharepoint": {"ok": sp_ok, "failed": sp_fail, "skipped": sp_skip, "total": len(sp_links)},
    "google_drive": {"ok": gd_ok, "failed": gd_fail, "skipped": gd_skip, "total": len(gd_links)},
}
with open(LOG_PATH, "w") as f:
    json.dump(log, f, ensure_ascii=False, indent=2)

print("\n" + "=" * 60)
print(f"HOÀN TẤT!")
print(f"  SharePoint: {sp_ok} OK / {sp_fail} FAIL / {sp_skip} SKIP (tổng {len(sp_links)})")
print(f"  Google Drive: {gd_ok} OK / {gd_fail} FAIL / {gd_skip} SKIP (tổng {len(gd_links)})")
print(f"  Log: {LOG_PATH}")
