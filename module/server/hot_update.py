# This Python file uses the following encoding: utf-8
"""基于 Git 的 OAS 源码热更新（与 OAS 自带更新机制同源）。

运行时里的 /opt/oas 初始是 tar 展开的开箱快照，没有 .git；第一次更新时在这里做一次性浅
引导（git init → fetch --depth 1 → reset --hard），此后它就是一个常规的 shallow 仓库，
每次更新只拉增量。更新源（仓库/分支）写在 config/deploy.yaml —— 与桌面端 OASX 部署页
编辑的是同一份配置；config/*.yaml 被 OAS 仓库的 .gitignore 忽略，reset --hard 永远不会
碰用户配置，log/.venv 等运行时数据也不在 Git 管理范围内，因此不再需要快照/覆盖/KEEP
那套机制，回滚就是 `git reset --hard <旧提交>`。

热更新由 /android/update/* 驱动，重启靠退出码 75 交给 rootfs 入口进程 `android_host.py`
重新拉起 WebUI，App 不参与重启动作。

Hot-updates the OAS source tree with plain Git, mirroring OAS's own update machinery.
`/opt/oas` starts as a tar extraction without `.git`; the first update bootstraps a shallow
repository in place (git init → fetch --depth 1 → reset --hard), and every later update only
pulls new objects. The update source lives in config/deploy.yaml — the same file the desktop
OASX deploy page edits. config/*.yaml is gitignored, so `git reset --hard` never touches user
configs, and log/.venv are outside Git's control entirely: no snapshot/overlay/KEEP machinery
is needed, and rollback is just `git reset --hard <old commit>`.
"""

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from module.logger import logger

ROOT = Path(__file__).resolve().parents[2]

# 与桌面端 OASX 部署页同源：更新源就是 config/deploy.yaml 的 Repository/Branch
DEPLOY_FILE = ROOT / 'config/deploy.yaml'
DEPLOY_TEMPLATE = ROOT / 'deploy/template'

STATE_FILE = 'oas-update-state.json'
COMMIT_FILE = 'OAS_SOURCE_COMMIT'

DEFAULT_REPO = 'https://github.com/LGG686/OnmyojiAutoScript'
DEFAULT_BRANCH = 'OASA'

# rootfs 入口进程认这个退出码，收到就重新拉起 WebUI
RESTART_EXIT_CODE = 75
GIT_TIMEOUT = 900
PROBE_TIMEOUT = 20
PROBE_CACHE_SECONDS = 60

# 旧版本把状态与更新源写在 config/*.json 里，会被配置列表误认成配置实例；启动时迁移并清掉
_LEGACY_STATE = (ROOT / 'config/oas-update-state.json', ROOT / 'oas-update-state.json')
_LEGACY_CONFIG = (ROOT / 'config/oas-update.json', ROOT / 'oas-update.json')

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


def _deploy_read() -> dict:
    """读 deploy.yaml（OAS 自带的 poor yaml 实现，不引入 pyyaml）。"""
    from deploy.utils import poor_yaml_read
    data = poor_yaml_read(str(DEPLOY_FILE))
    return data if isinstance(data, dict) else {}


def _deploy_write(values: dict) -> None:
    """把键写回 deploy.yaml；按 deploy 模板展开，保证文件完整、桌面端也能读。"""
    from deploy.utils import poor_yaml_write
    poor_yaml_write({**_deploy_read(), **values}, str(DEPLOY_FILE),
                    template_file=str(DEPLOY_TEMPLATE))


def _migrate_legacy() -> None:
    """旧版状态/更新源文件从 config/ 搬走：状态上移一层，更新源并入 deploy.yaml。"""
    legacy_state, state = _LEGACY_STATE
    if legacy_state.is_file():
        try:
            if state.is_file():
                legacy_state.unlink()
            else:
                os.replace(legacy_state, state)
        except OSError:
            pass
    for legacy in _LEGACY_CONFIG:
        if not legacy.is_file():
            continue
        try:
            data = json.loads(legacy.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = {}
        if isinstance(data, dict) and data.get('repo') and not _deploy_read().get('Repository'):
            _deploy_write({'Repository': str(data['repo']),
                           'Branch': str(data.get('branch') or DEFAULT_BRANCH)})
        try:
            legacy.unlink()
        except OSError:
            pass


_migrate_legacy()


def _truthy(value) -> bool:
    """deploy.yaml 里布尔可能被写成 true/True/"true"；统一按语义取值。"""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def load_config() -> dict:
    """当前的更新源；没配置过就是默认的公开仓库与 OASA 分支。"""
    data = _deploy_read()
    return {
        'repo': str(data.get('Repository') or DEFAULT_REPO),
        'branch': str(data.get('Branch') or DEFAULT_BRANCH),
        'keepLocalChanges': _truthy(data.get('KeepLocalChanges')),
    }


def save_config(repo: str, branch: str, keep_local_changes=None) -> None:
    """记住用户填的地址、分支与「保留本地修改」，下次更新直接用这一份。"""
    values = {'Repository': repo, 'Branch': branch}
    if keep_local_changes is not None:
        values['KeepLocalChanges'] = bool(keep_local_changes)
    _deploy_write(values)


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


def _read_commit_file() -> str:
    """构建时写入的 OAS_SOURCE_COMMIT；引导前的唯一提交来源。"""
    try:
        text = (ROOT / COMMIT_FILE).read_text(encoding='utf-8').strip()
    except OSError:
        return ''
    return text if re.fullmatch(r'[0-9a-f]{40}', text) else ''


def local_head() -> str:
    """当前源码对应的提交；引导后读 git，没引导过退回 OAS_SOURCE_COMMIT。"""
    try:
        if (ROOT / '.git').is_dir():
            return _git(ROOT, 'rev-parse', 'HEAD', timeout=15)
    except (OSError, subprocess.SubprocessError):
        pass
    return _read_commit_file()


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


def _drop_git_leftovers(git_dir: Path, locks_only: bool = False) -> None:
    """清掉被杀的 git 留下的锁与半个 pack。

    只在确认子进程已结束之后调用：单用户容器里没有并发 git，此刻还留着的锁必然是
    残留，半个 `tmp_pack_*` 也永远不会补完（真机踩过：多次超时堆出 50MB 垃圾）。
    Only call this after the child has exited: a single-user container never has a
    concurrent git, so any lock still present is stale and a half-written pack will
    never complete.
    """
    if not git_dir.is_dir():
        return
    for name in ('index.lock', 'shallow.lock'):
        (git_dir / name).unlink(missing_ok=True)
    if locks_only:
        return
    for pack in (git_dir / 'objects' / 'pack').glob('tmp_pack_*'):
        pack.unlink(missing_ok=True)


def _git(cwd, *args, timeout=GIT_TIMEOUT) -> str:
    """限时执行 Git，失败时把 stderr 尾部带进异常给状态文件用。

    进程被杀会留下 `.git/index.lock` / `.git/shallow.lock`，之后所有写操作都被
    “Another git process seems to be running”或“Unable to create ... File exists”
    挡死（真机发生过：提交历史永远远端拉取失败）。锁已存在超过 10 秒就当残留清掉
    重试一次——单用户容器里没有并发 git；更新鲜的锁可能属于正在跑的进程，不动。

    TimeoutExpired 的 stderr 是空的，但子进程已经被杀，锁必然是死的，一起清掉。
    """
    git_dir = Path(cwd) / '.git'
    locks = [git_dir / 'index.lock', git_dir / 'shallow.lock']

    def run() -> subprocess.CompletedProcess:
        return subprocess.run(
            ['git', '-c', 'http.lowSpeedLimit=1024', '-c', 'http.lowSpeedTime=30', *args],
            cwd=str(cwd), check=True, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=timeout,
            env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'},
        )

    try:
        return run().stdout.strip()
    except subprocess.TimeoutExpired:
        _drop_git_leftovers(git_dir)
        raise
    except subprocess.SubprocessError as caught:
        stderr = getattr(caught, 'stderr', '') or ''
        stale = [l for l in locks if l.is_file() and time.time() - l.stat().st_mtime > 10]
        if stale and ('index.lock' in stderr or 'shallow.lock' in stderr
                      or 'Another git process' in stderr):
            _drop_git_leftovers(git_dir)
            return run().stdout.strip()
        raise


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
        output = _git(ROOT, 'ls-remote', repo, f'refs/heads/{branch}', timeout=PROBE_TIMEOUT)
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
        'keepLocalChanges': config['keepLocalChanges'],
    }


def _ensure_repo(repo: str, branch: str, timeout: int = GIT_TIMEOUT) -> None:
    """确保 /opt/oas 是能 fetch 的 shallow 仓库；没有 .git 就原地浅引导。

    每次都把 origin 指到当前配置的地址：设置页改了仓库后不需要删掉重来。
    `user.name/email` 只写进 .git/config：`git stash` 要建提交，缺身份会直接失败。
    Re-point origin at the configured address every time, so changing the repo in settings
    never requires deleting the repository. The identity is local-only: `git stash` creates a
    commit and fails outright without one.
    """
    if not (ROOT / '.git').is_dir():
        logger.hr('[HotUpdate] 首次引导：原地初始化 shallow 仓库')
        _git(ROOT, 'init', timeout=timeout)
        _git(ROOT, 'config', 'user.name', 'OAS', timeout=timeout)
        _git(ROOT, 'config', 'user.email', 'oas@localhost', timeout=timeout)
    try:
        _git(ROOT, 'remote', 'remove', 'origin', timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        pass
    _git(ROOT, 'remote', 'add', 'origin', repo, timeout=timeout)
    # 显式 refspec：裸分支名只写 FETCH_HEAD，不会建 origin/<branch> 引用，
    # 提交历史面板按 origin/<branch> 读日志就会空手而归。
    # An explicit refspec: a bare branch name only writes FETCH_HEAD and never creates the
    # origin/<branch> ref the commit-history panel reads from.
    _git(ROOT, 'fetch', '--depth', '1', '--no-tags', 'origin',
         f'refs/heads/{branch}:refs/remotes/origin/{branch}', timeout=timeout)


def _checkout(target: str, keep_changes: bool) -> None:
    """把工作区切到目标提交；开了「保留本地修改」就先 stash 再叠回来。

    deploy.yaml 的 KeepLocalChanges 与桌面端 OAS 同义：源码照常更新，自己改过的文件在更新
    后仍在。新版本改了同一行时以新版本为准，改动整份留在 stash 里不丢。

    Switches the work tree to the target commit. With KeepLocalChanges the local edits are stashed
    and re-applied afterwards, matching the desktop flag: conflicts keep the upstream side and the
    stashed copy stays intact instead of being discarded.
    """
    if not keep_changes:
        _git(ROOT, 'reset', '--hard', target)
        return
    dirty = _git(ROOT, 'status', '--porcelain')
    if not dirty:
        _git(ROOT, 'reset', '--hard', target)
        return
    logger.info('[HotUpdate] 保留本地修改：stash → reset → stash pop')
    _git(ROOT, 'stash', 'push', '--include-untracked')
    _git(ROOT, 'reset', '--hard', target)
    try:
        _git(ROOT, 'stash', 'pop')
    except (OSError, subprocess.SubprocessError) as caught:
        detail = (getattr(caught, 'stderr', None) or str(caught)).strip()[-200:]
        logger.warning(f'[HotUpdate] 本地修改与新版本冲突，改动保留在 git stash：{detail}')


def _deps_signature(text: str) -> list:
    """依赖签名：忽略注释与 Windows 专属项，Linux 侧本来就不装它们。"""
    return sorted(
        line.strip() for line in text.splitlines()
        if line.strip() and not line.strip().startswith('#') and not line.startswith('pywin32==')
    )


def _install_requirements() -> None:
    """依赖变化时同步虚拟环境；失败由调用方回滚并提示整包更新。

    镜像构建（build-oas.sh）对 requirements.txt 做过两处 Linux 化：去掉 pywin32、
    opencv-python 换 contrib-headless（ARM64 无 opencv-python 轮子）。运行期安装沿用同一
    规则，否则装回与镜像不一致的包。
    """
    lines = [
        line.strip() for line in (ROOT / 'requirements.txt').read_text(encoding='utf-8').splitlines()
        if line.strip() and not line.strip().startswith('#') and not line.startswith('pywin32==')
    ]
    filtered = ROOT / 'requirements-linux.txt'
    filtered.write_text(
        '\n'.join(
            line.replace('opencv-python==', 'opencv-contrib-python-headless==', 1)
            if line.startswith('opencv-python==') else line
            for line in lines
        ) + '\n',
        encoding='utf-8',
    )
    command = ['uv', 'pip', 'install', '--python', str(ROOT / '.venv/bin/python'),
               '-r', str(filtered)]
    subprocess.run(command, cwd=str(ROOT), check=True, capture_output=True, text=True,
                   encoding='utf-8', errors='replace', timeout=GIT_TIMEOUT)
    logger.info('[HotUpdate] 依赖已同步 / dependencies synced')


def _write_commit(target: str) -> None:
    """刷新 OAS_SOURCE_COMMIT；App 的「OAS 提交」读的就是它。"""
    (ROOT / COMMIT_FILE).write_text(target + '\n', encoding='utf-8')


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


def _run(repo: str, branch: str, keep_changes: bool = False) -> None:
    """完整一轮：fetch → 切到目标提交 → 依赖同步 → 重启；失败尽量回滚到旧提交。"""
    first_install = not (ROOT / '.git').is_dir()
    old_head = ''
    try:
        _write_state(phase='clone', result='', target='', error='', requiresRuntimeUpdate=False)
        if not first_install:
            old_head = local_head()
        old_requirements = ''
        try:
            old_requirements = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
        except OSError:
            pass

        _ensure_repo(repo, branch)
        target = _git(ROOT, 'rev-parse', 'FETCH_HEAD')

        if not first_install and target == old_head:
            _write_state(phase='done', result='updated', target=target, error='',
                         requiresRuntimeUpdate=False)
            logger.info(f'[HotUpdate] 已是最新 {target}（{repo}@{branch}）')
            return

        _write_state(phase='swap', target=target)
        # 首次引导还没有初始提交，stash 无从做起，也谈不上保留旧改动。
        _checkout(target, keep_changes and not first_install)
        _write_commit(target)

        new_requirements = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
        if _deps_signature(old_requirements) != _deps_signature(new_requirements):
            _write_state(phase='deps')
            try:
                _install_requirements()
            except (OSError, subprocess.SubprocessError) as caught:
                detail = (getattr(caught, 'stderr', None) or str(caught)).strip()[-300:]
                raise RuntimeError(f'依赖变化且安装失败，需整包更新：{detail}') from caught

        _write_state(phase='done', result='updated', target=target, error='',
                     requiresRuntimeUpdate=False)
        logger.info(f'[HotUpdate] 已更新到 {target}（{repo}@{branch}）')
        _restart()
    except Exception as caught:
        logger.exception('[HotUpdate] 更新失败')
        lines = [line.strip() for line in
                 (getattr(caught, 'stderr', None) or str(caught)).strip().splitlines() if line.strip()]
        fatal = [line for line in lines if line.startswith(('fatal:', 'error:'))]
        reason = (fatal[0] if fatal else (lines[0] if lines else caught.__class__.__name__))[:300]
        # 已经落到新提交才需要回滚；首次引导没有旧提交可退，只能提示整包更新
        restore_error = ''
        if old_head:
            try:
                _checkout(old_head, keep_changes)
                _write_commit(old_head)
                logger.info('[HotUpdate] 已回滚到旧版本 / rolled back')
            except Exception as rollback:
                logger.exception('[HotUpdate] 回滚失败')
                restore_error = f'，回滚失败：{rollback}'
        elif first_install:
            _write_state(requiresRuntimeUpdate=True)
        _write_state(phase='done', result='failed', error=reason + restore_error)


_LOG_FORMAT = '%H%x1f%h%x1f%an%x1f%ci%x1f%s'

# 历史面板的 git 网络操作限时：App 那边读超时只有 45 秒，补仓库与加深各占一半就顶到上限了。
HISTORY_GIT_TIMEOUT = 15


def _parse_log(output: str) -> list:
    """把 `git log` 输出按分隔符解析成 App 好消费的字典列表。"""
    rows = []
    for line in output.splitlines():
        parts = line.split('\x1f')
        if len(parts) != 5:
            continue
        full, short, author, date, subject = parts
        rows.append({
            'hash': full, 'short': short, 'author': author,
            'date': date[:10], 'subject': subject,
        })
    return rows


def _read_log(count: int, ref: str = 'HEAD') -> list:
    """读本地 git 日志；没引导过仓库或引用不存在时返回空表，不抛。

    面板打开时先看本地能给出什么，网络再慢也不至于连一条提交都显示不出来。
    Read the local log first: no repository or missing ref yields an empty list instead of
    raising, so a slow network never blanks the whole panel.
    """
    if not (ROOT / '.git').is_dir():
        return []
    try:
        return _parse_log(_git(ROOT, 'log', f'--format={_LOG_FORMAT}', '-n', str(count), ref,
                               timeout=10))
    except (OSError, subprocess.SubprocessError):
        return []


def _bundled_commit_row() -> list:
    """rootfs 不带 .git：镜像里打包的提交从 BUILD_MANIFEST 读出来补一条。

    没有这条时，还没做过首次更新的容器在提交历史面板的“当前版本”一节永远是空的。
    Without it the "current version" section stays empty for containers that never
    ran their first update.
    """
    try:
        manifest = json.loads((ROOT / 'BUILD_MANIFEST').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    commit = str(manifest.get('oas_commit') or '').strip()
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        return []
    return [{
        'hash': commit, 'short': commit[:12], 'author': 'OAS Android',
        'date': str(manifest.get('built_at_utc') or '')[:10],
        'subject': '内置镜像打包的版本（打开一次提交历史即可拉到完整列表）',
    }]


def _has_remote_ref(branch: str) -> bool:
    """本地是否已有 origin/<branch> 引用：没有就说明从没成功拉过一次远端。

    Whether the local repository already carries `origin/<branch>`; a miss means no
    successful fetch has ever completed here.
    """
    if not (ROOT / '.git').is_dir():
        return False
    try:
        _git(ROOT, 'rev-parse', '--verify', '--quiet',
             f'refs/remotes/origin/{branch}', timeout=10)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def history(repo: str = '', branch: str = '', count: int = 20) -> dict:
    """给 App 提交历史面板：当前版本与远端分支各自的最近提交。

    shallow 仓库默认只有 1 条，按需 `--deepen` 增量加深；deepen 失败（镜像不支持、
    网络中断）只回传已有部分并附原因，不阻塞面板打开。

    从没成功拉过远端时不做任何 fetch：首次 `--depth 1` 要下整棵树（数百 MB），
    面板只是点开看一眼，十几秒必然超时，还会留下 shallow.lock 与半个 pack，
    把之后的更新一起挡住（真机踩过）。首次拉取交给「立即更新」完成。

    The shallow clone only holds one commit; deepen it on demand. A failed deepen still
    returns whatever is already available plus the reason. No fetch happens before the
    first successful pull: the initial depth-1 download is the whole tree, far beyond a
    panel-open budget, and killing it leaves a stale lock and a half-written pack that
    block every later update.
    """
    try:
        count = max(1, min(int(count), 50))
    except (TypeError, ValueError):
        count = 20
    config = load_config()
    repo = (repo or '').strip() or config['repo']
    branch = (branch or '').strip() or config['branch']
    try:
        _validate(repo, branch)
    except ValueError as error:
        return {'ok': False, 'error': str(error), 'local': [], 'remote': []}
    # 先把本地能给的拿出来：这一半不碰网络，手机直连 GitHub 断流也照常显示
    local = _read_log(count) or _bundled_commit_row()
    if _busy():
        return {'ok': True, 'error': '已有更新在进行中', 'local': local, 'remote': []}
    remote, error = [], ''
    if not _has_remote_ref(branch):
        return {'ok': True, 'local': local, 'remote': [],
                'error': '本地还没有远端历史，完成一次更新后即可查看'}
    try:
        _git(ROOT, 'fetch', '--deepen', str(count), '--no-tags', 'origin',
             f'refs/heads/{branch}:refs/remotes/origin/{branch}',
             timeout=HISTORY_GIT_TIMEOUT)
        remote = _read_log(count, f'origin/{branch}')
        local = _read_log(count) or local
    except (OSError, subprocess.SubprocessError, ValueError) as caught:
        error = (getattr(caught, 'stderr', None) or str(caught)).strip()[-300:]
    return {'ok': True, 'error': error, 'local': local, 'remote': remote}


def save_requested(repo: str = '', branch: str = '', keep_local_changes=None) -> dict:
    """校验并保存更新源；留空的一项保留原值，方便只改地址或只改分支。"""
    config = load_config()
    repo = (repo or '').strip() or config['repo']
    branch = (branch or '').strip() or config['branch']
    _validate(repo, branch)
    save_config(repo, branch, keep_local_changes)
    # 目标变了，上一个仓库的探测结果作废
    _PROBE['key'] = ''
    return load_config()


def apply(repo: str = '', branch: str = '', keep_local_changes=None) -> dict:
    """接受一次热更新请求；参数留空就沿用上次保存的地址与分支。"""
    with _LOCK:
        if _busy():
            return {'ok': False, 'error': '已有更新在进行中'}
        config = save_requested(repo, branch, keep_local_changes)
        _write_state(phase='prepare', result='', target='', error='', requiresRuntimeUpdate=False)
        threading.Thread(
            target=_run,
            args=(config['repo'], config['branch'], config['keepLocalChanges']),
            name='oas-hot-update', daemon=True,
        ).start()
    return {'ok': True, **config}
