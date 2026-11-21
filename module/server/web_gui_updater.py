# This Python file uses the following encoding: utf-8
"""网页控制台（OASX web）自动更新。

module/server/web/gui 是 OASX 的 web 构建产物，不在 OAS 仓库里，
源码热更（git reset --hard）既不会带来也不会更新它。这里在服务启动后
后台检查 OASX-self 的滚动 release `oasx-web-latest`，有新包就下载 zip
并替换 module/server/web/gui，Windows 桌面与安卓 runtime 共用这条链路。

新版判断优先走下载地址的 ETag（CDN 响应头，不受 GitHub API 限流影响），
release API 只用来补充 digest 与时间戳，失败不影响更新能力。

下载或解压失败只记日志，不影响服务；gui 目录在启动时不存在则不会挂载
/gui，更新后需要重启服务才会挂载。
"""
import hashlib
import json
import shutil
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from module.logger import logger

ROOT = Path(__file__).resolve().parents[2]
GUI_DIR = ROOT / 'module' / 'server' / 'web' / 'gui'
MARKER_FILE = GUI_DIR.parent / 'gui-update-marker.json'

DOWNLOAD_URL = 'https://github.com/LGG686/OASX-self/releases/download/oasx-web-latest/oasx-web.zip'
RELEASE_API = 'https://api.github.com/repos/LGG686/OASX-self/releases/tags/oasx-web-latest'
ASSET_NAME = 'oasx-web.zip'
CHECK_TIMEOUT = 15
DOWNLOAD_TIMEOUT = 600
DOWNLOAD_RETRIES = 3
AUTO_CHECK_DELAY = 60
_HEADERS = {'User-Agent': 'OAS-webgui-updater'}

_check_lock = threading.Lock()


def _release_asset() -> dict | None:
    """读取 release API 的资产信息（含官方 digest），失败返回 None。"""
    try:
        request = Request(RELEASE_API, headers={
            'Accept': 'application/vnd.github+json', **_HEADERS,
        })
        with urlopen(request, timeout=CHECK_TIMEOUT) as response:
            release = json.loads(response.read().decode('utf-8'))
    except Exception as e:
        logger.warning(f'webgui: check release api failed: {e}')
        return None
    for asset in release.get('assets', []):
        if asset.get('name') == ASSET_NAME and asset.get('size', 0) > 0:
            return {
                'url': asset['browser_download_url'],
                'updated_at': asset['updated_at'],
                'etag': '',
                'size': asset['size'],
                'digest': (asset.get('digest') or '').removeprefix('sha256:'),
            }
    logger.warning(f'webgui: release has no {ASSET_NAME} asset')
    return None


def _head_asset() -> dict | None:
    """HEAD 下载地址取 ETag/Last-Modified；API 限流时的回退方案。"""
    try:
        request = Request(DOWNLOAD_URL, method='HEAD', headers=_HEADERS)
        with urlopen(request, timeout=CHECK_TIMEOUT) as response:
            return {
                'url': DOWNLOAD_URL,
                'updated_at': response.headers.get('Last-Modified') or '',
                'etag': (response.headers.get('ETag') or '').strip('"'),
                'size': int(response.headers.get('Content-Length') or 0),
                'digest': '',
            }
    except Exception as e:
        logger.warning(f'webgui: head download url failed: {e}')
        return None


def _remote_info() -> dict | None:
    return _release_asset() or _head_asset()


def _is_same_bundle(marker: dict, asset: dict) -> bool:
    """比对本地标记与远端包是否同一个：API 与 HEAD 回退能拿到的字段不同，
    所以按 etag / updated_at / digest 任一字段能对上即视为同一个包。"""
    etag = asset.get('etag') or ''
    updated = asset.get('updated_at') or ''
    digest = asset.get('digest') or ''
    if etag and marker.get('asset_etag'):
        return etag == marker['asset_etag']
    if updated and marker.get('asset_updated_at'):
        return updated == marker['asset_updated_at']
    if digest and marker.get('asset_digest'):
        return digest == marker['asset_digest']
    return False


def local_marker() -> dict:
    """读取本地更新标记；没有标记说明还是构建时打入的原始包。"""
    try:
        return json.loads(MARKER_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def check_update() -> dict:
    """对比本地标记与远端包标识，返回可直接展示的信息。"""
    asset = _remote_info()
    installed = local_marker()
    return {
        'installed_updated_at': installed.get('asset_updated_at'),
        'latest_updated_at': asset['updated_at'] if asset else None,
        'latest_etag': asset['etag'] if asset else None,
        'has_update': bool(asset and not _is_same_bundle(installed, asset)),
        'download_url': asset['url'] if asset else None,
        'size': asset['size'] if asset else None,
    }


def apply_update() -> dict:
    """下载 oasx-web.zip 并替换 web/gui 内容，返回结果摘要。"""
    with _check_lock:
        asset = _remote_info()
        if not asset:
            return {'success': False, 'message': 'release asset unavailable'}
        marker = local_marker()
        if _is_same_bundle(marker, asset) \
                and (not asset['digest'] or marker.get('asset_digest') == asset['digest']):
            return {'success': True, 'message': 'already up to date', 'changed': False}

        GUI_DIR.parent.mkdir(parents=True, exist_ok=True)
        zip_path = GUI_DIR.parent / f'{ASSET_NAME}.tmp'
        extract_dir = GUI_DIR.parent / 'gui.update-tmp'
        backup_dir = GUI_DIR.parent / 'gui.backup-tmp'
        try:
            logger.info(f'webgui: downloading {asset["url"]} ({asset["size"]} bytes)')
            # GitHub 下载链路经常中途重置，重试几次再放弃。
            last_error: Exception | None = None
            for attempt in range(1, DOWNLOAD_RETRIES + 1):
                try:
                    with urlopen(asset['url'], timeout=DOWNLOAD_TIMEOUT) as response, \
                            open(zip_path, 'wb') as file:
                        shutil.copyfileobj(response, file)
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    logger.warning(f'webgui: download attempt {attempt} failed: {e}')
            if last_error is not None:
                raise last_error
            digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
            if asset['digest'] and digest != asset['digest']:
                raise RuntimeError(f'digest mismatch: {digest} != {asset["digest"]}')

            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            extract_dir.mkdir(parents=True)
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(extract_dir)
            if not (extract_dir / 'index.html').exists():
                raise RuntimeError('bundle has no index.html')

            # 原地替换：先备份旧目录内容，再搬入新包，失败可从备份恢复。
            if GUI_DIR.exists():
                if backup_dir.exists():
                    shutil.rmtree(backup_dir)
                GUI_DIR.rename(backup_dir)
            extract_dir.rename(GUI_DIR)
            shutil.rmtree(backup_dir)
        except Exception as e:
            # 恢复旧目录，避免留下半更新的状态。
            if not GUI_DIR.exists() and backup_dir.exists():
                backup_dir.rename(GUI_DIR)
            logger.error(f'webgui: update failed: {e}')
            return {'success': False, 'message': str(e)}
        finally:
            if zip_path.exists():
                zip_path.unlink()
            if extract_dir.exists():
                shutil.rmtree(extract_dir, ignore_errors=True)

        marker = {
            'asset_etag': asset['etag'],
            'asset_updated_at': asset['updated_at'],
            'asset_digest': digest,
            'asset_size': asset['size'],
            'applied_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        }
        MARKER_FILE.write_text(json.dumps(marker, indent=2), encoding='utf-8')
        logger.info(f'webgui: updated to {asset["etag"] or asset["updated_at"] or digest[:12]}')
        return {'success': True, 'message': 'updated', 'changed': True, **marker}


def start_background_check() -> None:
    """启动后台线程延迟检查一次；失败静默，只在日志留痕。"""

    def worker():
        threading.Event().wait(AUTO_CHECK_DELAY)
        try:
            info = check_update()
            if info['has_update']:
                logger.info(f'webgui: new bundle {info["latest_etag"] or info["latest_updated_at"]}, applying')
                apply_update()
            else:
                logger.info('webgui: bundle is up to date')
        except Exception as e:
            logger.warning(f'webgui: background check failed: {e}')

    threading.Thread(target=worker, name='webgui-updater', daemon=True).start()
