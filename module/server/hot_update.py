# This Python file uses the following encoding: utf-8
"""从 Git 仓库热更新 OAS 源码。

运行时里的 `/opt/oas` 是构建时用 tar 展开的，没有 `.git`，所以只能「拉一份新源码 → 覆盖 →
重启」，不能原地 `git pull`。覆盖只动源码树：用户配置、日志、虚拟环境、OCR 模型缓存与构建
产物一律保留；改动前用硬链接留一份快照，任一阶段失败都能整份还原。

热更新由 `/android/update/*` 驱动，重启靠退出码 75 交给 rootfs 入口进程 `android_host.py`
重新拉起 WebUI，App 不参与重启动作。

Hot-updates OAS source from a Git repository.

`/opt/oas` inside the runtime is a tar extraction without `.git`, so an in-place `git pull` is
impossible; the only path is fetch a fresh tree, overlay it, and restart. The overlay touches
source only: user config, logs, the virtualenv, the OCR model cache and build artifacts are all
preserved, and a hard-link snapshot taken beforehand lets any failure roll the tree back whole.
"""

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from module.logger import logger

ROOT = Path(__file__).resolve().parents[2]
# 与 ROOT 同一文件系统的暂存区，clone 与快照都放这里，避免跨设备复制
STAGE = ROOT.parent / 'oas-update'

STATE_FILE = 'config/oas-update-state.json'
CONFIG_FILE = 'config/oas-update.json'
COMMIT_FILE = 'OAS_SOURCE_COMMIT'

DEFAULT_REPO = 'https://github.com/LGG686/OnmyojiAutoScript'
DEFAULT_BRANCH = 'OASA'

# rootfs 入口进程认这个退出码，收到就重新拉起 WebUI
RESTART_EXIT_CODE = 75
GIT_TIMEOUT = 900
PROBE_TIMEOUT = 20
PROBE_CACHE_SECONDS = 60

# 覆盖与快照都不碰的顶层条目：用户数据、运行环境、构建产物、rootfs 注入的入口脚本
KEEP = frozenset({
    'config', 'configs', 'log', '.venv', '.git',
    'requirements-linux.txt', 'requirements-headless.txt',
    'BUILD_MANIFEST', COMMIT_FILE,
    'android_host.py', 'seed_oas.py',
})
# 模型缓存与字节码与源码无关：既不该覆盖，也不该进快照
SKIP_NAMES = shutil.ignore_patterns('__pycache__', '*.pyc', '.paddlex', '.paddle')

_URL_PATTERN = re.compile(r'^(?:https?://|ssh://|git://|git@)[^\s]+$')
_BRANCH_PATTERN = re.compile(r'^[A-Za-z0-9._/-]{1,120}$')

_LOCK = threading.Lock()
_PROBE = {'key': '', 'at': 0.0, 'head': '', 'error': ''}


def _now() -> str:
    """当前 UTC 时间，写进状态文件给 App 展示。"""
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _read_json(path, default):
    """读 JSON；缺失或损坏都退回默认值，状态文件不该让接口 500。"""
    try:
        return json.loads((ROOT / path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def _write_json(path, value) -> None:
    """原子写 JSON：先落临时文件再替换，进程被杀不会留下半个文件。"""
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(target)


def load_config() -> dict:
    """当前的更新源；没配置过就是默认的公开仓库与 OASA 分支。"""
    data = _read_json(CONFIG_FILE, {})
    if not isinstance(data, dict):
        data = {}
    return {
        'repo': str(data.get('repo') or DEFAULT_REPO),
        'branch': str(data.get('branch') or DEFAULT_BRANCH),
    }


def save_config(repo: str, branch: str) -> None:
    """记住用户填的地址与分支，下次「检查更新」直接用这一份。"""
    _write_json(CONFIG_FILE, {'repo': repo, 'branch': branch, 'updatedAt': _now()})


def _state() -> dict:
    data = _read_json(STATE_FILE, {})
    return data if isinstance(data, dict) else {}


def _write_state(**fields) -> None:
    current = _state()
    current.update(fields)
    current['updatedAt'] = _now()
    _write_json(STATE_FILE, current)


def _busy() -> bool:
    """阶段值不是 idle/done 就说明有任务在跑（或上次被杀留下未清状态）。"""
    return _state().get('phase') not in (None, 'idle', 'done')


def local_head() -> str:
    """当前源码对应的提交；构建时就写进 OAS_SOURCE_COMMIT，热更成功后跟着更新。"""
    try:
        text = (ROOT / COMMIT_FILE).read_text(encoding='utf-8').strip()
    except OSError:
        return ''
    return text if re.fullmatch(r'[0-9a-f]{40}', text) else ''


def _validate(repo: str, branch: str) -> None:
    """只放行网络地址与合法分支名。

    `git` 会把以 `-` 开头的参数当选项，本地路径还能指向任意目录，所以地址必须显式带协议，
    分支名限定字符集。Git also treats a leading `-` as an option and a plain path as any
    local directory, so the URL must carry an explicit scheme and the branch stays alphanumeric.
    """
    if not _URL_PATTERN.match(repo or ''):
        raise ValueError('仓库地址必须是 https:// 或 git@ 开头的网络地址')
    if not _BRANCH_PATTERN.match(branch or '') or branch.startswith('-') or '..' in branch:
        raise ValueError('分支名不合法')


def _git(cwd, *args, timeout=GIT_TIMEOUT) -> str:
    """限时执行 Git，失败时把 stderr 尾部带进异常给状态文件用。"""
    result = subprocess.run(
        ['git', '-c', 'http.lowSpeedLimit=1024', '-c', 'http.lowSpeedTime=30', *args],
        cwd=str(cwd), check=True, capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=timeout,
        env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'},
    )
    return result.stdout.strip()


def upstream_head(repo: str, branch: str, force: bool = False) -> str:
    """远端分支的 HEAD；60 秒内复用结果，检查失败只记原因不抛。

    缓存按「仓库@分支」分开：设置页改了地址再点检查，不能拿到上一个仓库的结果。
    The cache is keyed by repository and branch, so checking a different address never reuses
    the previous target's answer.
    """
    key = f'{repo}@{branch}'
    cached = _PROBE
    if (not force and cached['key'] == key and cached['head']
            and time.monotonic() - cached['at'] < PROBE_CACHE_SECONDS):
        return cached['head']
    head, error = '', ''
    try:
        output = _git(STAGE if STAGE.exists() else ROOT,
                      'ls-remote', repo, f'refs/heads/{branch}', timeout=PROBE_TIMEOUT)
        head = output.split()[0] if output else ''
    except (OSError, subprocess.SubprocessError) as caught:
        detail = (getattr(caught, 'stderr', None) or str(caught)).strip()
        error = detail[-300:]
    _PROBE.update(key=key, at=time.monotonic(),
                  head=head if re.fullmatch(r'[0-9a-f]{40}', head or '') else '', error=error)
    return _PROBE['head']


def _probe_error(key: str) -> str:
    """只回传与当前目标相关的探测失败，避免把上一个仓库的错误显示给用户。"""
    return _PROBE['error'] if _PROBE['key'] == key else ''


def status(force: bool = False, repo: str = '', branch: str = '') -> dict:
    """给 App 的热更状态：本地/远端提交、是否有新版、当前阶段与失败原因。

    字段名沿用 App 已有的 `localHead/upstreamHead/available` 契约，只额外补 repo/branch。
    `repo`/`branch` 只用于本次探测，不落盘——设置页要在保存前先「检查」用户刚填的地址。
    """
    config = load_config()
    if repo.strip() or branch.strip():
        probe_repo = repo.strip() or config['repo']
        probe_branch = branch.strip() or config['branch']
        _validate(probe_repo, probe_branch)
    else:
        probe_repo, probe_branch = config['repo'], config['branch']
    local = local_head()
    busy = _busy()
    state = _state()
    upstream = local if busy else upstream_head(probe_repo, probe_branch, force)
    return {
        'enabled': True,
        'localHead': local or None,
        'upstreamHead': upstream or None,
        'available': bool(upstream and local and upstream != local and not busy),
        'distReady': True,
        'busy': busy,
        'phase': state.get('phase') or 'idle',
        'target': state.get('target') or None,
        'error': state.get('error')
        or ('' if busy else _probe_error(f'{probe_repo}@{probe_branch}')),
        'result': state.get('result') or '',
        'updatedAt': state.get('updatedAt'),
        'requiresRuntimeUpdate': bool(state.get('requiresRuntimeUpdate')),
        'repo': probe_repo,
        'branch': probe_branch,
    }


def _rmtree(path: Path) -> None:
    """删目录并强制清掉只读位。

    Git 的对象文件是只读的，Windows 上 `shutil.rmtree` 会直接失败；运行时的 `ignore_errors`
    又会让残留的暂存区把下一次更新挡在 `mkdir` 上。
    Git object files are read-only, which makes a plain `shutil.rmtree` fail on Windows; the
    runtime's `ignore_errors` would then leave a stale stage that blocks the next update.
    """

    def retry(func, target, _error=None):
        try:
            os.chmod(target, 0o700)
        except OSError:
            pass
        try:
            func(target)
        except OSError:
            pass

    if not path.exists():
        return
    try:
        shutil.rmtree(path, onexc=retry)
    except TypeError:
        # Python 3.10/3.11 只有 onerror 这个名字
        shutil.rmtree(path, onerror=retry)


def _place(source: Path, destination: Path) -> None:
    """写临时文件再原子替换。

    不能直接覆盖：快照里是硬链接，原地截断会把备份一起改掉。
    Never write in place — the snapshot holds hard links, so truncating would corrupt the backup.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + '.hotupdate-tmp')
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


def _overlay(source_root: Path, destination_root: Path) -> None:
    """把 source_root 的顶层条目铺到 destination_root，跳过 KEEP 与缓存。"""
    for name in sorted(os.listdir(source_root)):
        if name in KEEP:
            continue
        source = source_root / name
        destination = destination_root / name
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True,
                            ignore=SKIP_NAMES, copy_function=_place)
        elif source.is_file():
            _place(source, destination)


def _snapshot(destination_root: Path) -> None:
    """硬链接快照：只占目录项，回滚时读的是未被替换的旧 inode。"""
    for name in sorted(os.listdir(ROOT)):
        if name in KEEP:
            continue
        source = ROOT / name
        destination = destination_root / name
        if source.is_dir():
            shutil.copytree(source, destination, ignore=SKIP_NAMES, copy_function=os.link)
        elif source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.link(source, destination)


def _deps_signature(text: str) -> list:
    """依赖签名：忽略注释与 Windows 专属项，Linux 侧本来就不装它们。"""
    return sorted(
        line.strip() for line in text.splitlines()
        if line.strip() and not line.strip().startswith('#') and not line.startswith('pywin32==')
    )


def _install_requirements() -> None:
    """依赖变化时同步虚拟环境；失败由调用方回滚并提示整包更新。"""
    command = ['uv', 'pip', 'install', '--python', str(ROOT / '.venv/bin/python'),
               '-r', str(ROOT / 'requirements-linux.txt')]
    subprocess.run(command, cwd=str(ROOT), check=True, capture_output=True, text=True,
                   encoding='utf-8', errors='replace', timeout=GIT_TIMEOUT)
    logger.info('[HotUpdate] 依赖已同步 / dependencies synced')


def _restart() -> None:
    """完成态在调用前就已落盘，这里只管退出：新进程起来时 phase 必须是 done。

    只有 rootfs 入口进程 `android_host.py` 认得退出码 75 并重新拉起 WebUI；在 PC 上直接跑
    的 OAS 没有这个父进程，退出就真的退出了，所以那种情况只提示手动重启。

    Reaching `done` before exiting keeps a restarting runtime from inheriting a busy flag. Only
    the rootfs entry process understands code 75 and respawns the WebUI; a plain desktop OAS has
    no such parent, so it is told to restart by hand instead of being killed.
    """
    if not os.environ.get('OAS_ANDROID_HOST'):
        logger.warning('[HotUpdate] 源码已更新；当前没有接管重启的入口进程，请手动重启 OAS')
        return
    logger.info('[HotUpdate] 退出码 %d，交给入口进程重启 WebUI', RESTART_EXIT_CODE)
    timer = threading.Timer(0.8, lambda: os._exit(RESTART_EXIT_CODE))
    timer.daemon = False
    timer.start()


def _run(repo: str, branch: str) -> None:
    """完整一轮：克隆 → 校验 → 快照 → 覆盖 → 依赖 → 重启；异常则回滚。"""
    stage = STAGE
    snapshot_dir = stage / 'snapshot'
    try:
        _write_state(phase='clone', result='', target='', error='', requiresRuntimeUpdate=False)
        _rmtree(stage)
        stage.mkdir(parents=True)
        source = stage / 'src'
        _git(stage, 'clone', '--depth', '1', '--branch', branch, '--single-branch',
             '--quiet', repo, str(source))
        for marker in ('server.py', 'module/server/app.py', 'requirements.txt'):
            if not (source / marker).is_file():
                raise RuntimeError(f'仓库不像 OAS 源码：缺少 {marker}')
        target = _git(source, 'rev-parse', 'HEAD')

        old_requirements = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
        new_requirements = (source / 'requirements.txt').read_text(encoding='utf-8')
        deps_changed = _deps_signature(old_requirements) != _deps_signature(new_requirements)

        _write_state(phase='backup', target=target)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        _snapshot(snapshot_dir)

        _write_state(phase='swap')
        _overlay(source, ROOT)
        (ROOT / COMMIT_FILE).write_text(target + '\n', encoding='utf-8')

        if deps_changed:
            _write_state(phase='deps')
            try:
                _install_requirements()
            except (OSError, subprocess.SubprocessError) as caught:
                _write_state(requiresRuntimeUpdate=True)
                detail = (getattr(caught, 'stderr', None) or str(caught)).strip()[-300:]
                raise RuntimeError(f'依赖变化且安装失败，需整包更新：{detail}') from caught

        _write_state(phase='done', result='updated', target=target, error='',
                     requiresRuntimeUpdate=False)
        logger.info(f'[HotUpdate] 已更新到 {target}（{repo}@{branch}）')
        _rmtree(stage)
        _restart()
    except Exception as caught:
        logger.exception('[HotUpdate] 更新失败')
        lines = [line.strip() for line in
                 (getattr(caught, 'stderr', None) or str(caught)).strip().splitlines() if line.strip()]
        fatal = [line for line in lines if line.startswith(('fatal:', 'error:'))]
        reason = (fatal[0] if fatal else (lines[0] if lines else caught.__class__.__name__))[:300]
        restore_error = ''
        if (snapshot_dir / 'server.py').is_file():
            try:
                _overlay(snapshot_dir, ROOT)
                logger.info('[HotUpdate] 已回滚到旧版本 / rolled back')
            except Exception as rollback:
                logger.exception('[HotUpdate] 回滚失败')
                restore_error = f'，回滚失败：{rollback}'
        _write_state(phase='done', result='failed', error=reason + restore_error)
        _rmtree(stage)


def save_requested(repo: str = '', branch: str = '') -> dict:
    """校验并保存更新源；留空的一项保留原值，方便只改地址或只改分支。"""
    config = load_config()
    repo = (repo or '').strip() or config['repo']
    branch = (branch or '').strip() or config['branch']
    _validate(repo, branch)
    save_config(repo, branch)
    # 目标变了，上一个仓库的探测结果作废
    _PROBE['key'] = ''
    return {'repo': repo, 'branch': branch}


def apply(repo: str = '', branch: str = '') -> dict:
    """接受一次热更新请求；参数留空就沿用上次保存的地址与分支。"""
    with _LOCK:
        if _busy():
            return {'ok': False, 'error': '已有更新在进行中'}
        config = save_requested(repo, branch)
        _write_state(phase='prepare', result='', target='', error='', requiresRuntimeUpdate=False)
        threading.Thread(target=_run, args=(config['repo'], config['branch']),
                         name='oas-hot-update', daemon=True).start()
    return {'ok': True, **config}
