# This Python file uses the following encoding: utf-8
# copy from alas https://github.com/LmeSzinc/AzurLaneAutoScript
import subprocess
import time

from deploy.config import DeployConfig
from deploy.logger import logger
from deploy.utils import *

# 启动器可能在本进程启动前刚 fetch 过，这段时间内直接复用 FETCH_HEAD。
FETCH_HEAD_MAX_AGE = 300


class GitManager(DeployConfig):
    @cached_property
    def git(self):
        return self.filepath('GitExecutable')

    @staticmethod
    def remove(file):
        try:
            os.remove(file)
            logger.info(f'Removed file: {file}')
        except FileNotFoundError:
            logger.info(f'File not found: {file}')

    def reuse_fetched_branch(self, repo, branch):
        """
        启动器可能在本进程启动前刚 fetch 过配置的分支，此时 FETCH_HEAD
        已经指向远端最新提交，再 fetch 一次只是多一次网络往返。

        Args:
            repo (str): Repository url.
            branch (str): Branch name.

        Returns:
            bool: If FETCH_HEAD can be reused.
        """
        path = './.git/FETCH_HEAD'
        try:
            if time.time() - os.path.getmtime(path) > FETCH_HEAD_MAX_AGE:
                return False
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except OSError:
            return False

        repo = repo.replace('\\', '/').rstrip('/')
        for line in content.splitlines():
            if f"branch '{branch}' of " not in line:
                continue
            url = line.split(' of ', 1)[-1].strip()
            url = url.replace(r'\\', '/').replace('\\', '/').rstrip('/')
            if url == repo:
                logger.info(f'Reuse previous fetch of branch {branch}')
                return True
        return False

    def has_local_changes(self):
        """
        Returns:
            bool: If the working tree has tracked or untracked changes.
        """
        try:
            result = subprocess.run(
                f'"{self.git}" status --porcelain',
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                shell=True,
            )
        except OSError as e:
            logger.info(f'Check local changes failed: {e}')
            return True
        return bool(result.stdout.strip())

    def git_repository_init(
            self, repo, source='origin', branch='master',
            proxy='', ssl_verify=True, keep_changes=False
    ):
        logger.hr('Git Init', 1)
        if not os.path.exists('./.git'):
            if not self.execute(f'"{self.git}" init', allow_failure=True):
                self.remove('./.git/config')
                self.remove('./.git/index')
                self.remove('./.git/HEAD')
                self.execute(f'"{self.git}" init')

        logger.hr('Set Git Proxy', 1)
        if proxy:
            self.execute(f'"{self.git}" config --local http.proxy {proxy}')
            self.execute(f'"{self.git}" config --local https.proxy {proxy}')
        else:
            self.execute(f'"{self.git}" config --local --unset http.proxy', allow_failure=True)
            self.execute(f'"{self.git}" config --local --unset https.proxy', allow_failure=True)

        if ssl_verify:
            self.execute(f'"{self.git}" config --local http.sslVerify true', allow_failure=True)
        else:
            self.execute(f'"{self.git}" config --local http.sslVerify false', allow_failure=True)

        logger.hr('Set Git Repository', 1)
        if not self.execute(f'"{self.git}" remote set-url {source} {repo}', allow_failure=True):
            self.execute(f'"{self.git}" remote add {source} {repo}')

        logger.hr('Fetch Repository Branch', 1)
        if not self.reuse_fetched_branch(repo=repo, branch=branch):
            self.execute(f'"{self.git}" fetch --no-tags {source} {branch}')

        logger.hr('Pull Repository Branch', 1)
        # Remove git lock
        for lock_file in [
            './.git/index.lock',
            './.git/HEAD.lock',
            './.git/refs/heads/master.lock',
        ]:
            if os.path.exists(lock_file):
                logger.info(f'Lock file {lock_file} exists, removing')
                os.remove(lock_file)
        if keep_changes:
            if self.has_local_changes():
                if self.execute(f'"{self.git}" stash', allow_failure=True):
                    self.execute(f'"{self.git}" merge --ff-only FETCH_HEAD')
                    if self.execute(f'"{self.git}" stash pop', allow_failure=True):
                        pass
                    else:
                        # No local changes to existing files, untracked files not included
                        logger.info('Stash pop failed, there seems to be no local changes, skip instead')
                else:
                    logger.info('Stash failed, this may be the first installation, drop changes instead')
                    self.execute(f'"{self.git}" reset --hard FETCH_HEAD')
            else:
                self.execute(f'"{self.git}" merge --ff-only FETCH_HEAD')
        else:
            self.execute(f'"{self.git}" reset --hard FETCH_HEAD')

        logger.hr('Show Version', 1)
        self.execute(f'"{self.git}" --no-pager log --no-merges -1')

    def git_install(self):
        logger.hr('Update OAS', 0)

        if not self.AutoUpdate:
            logger.info('AutoUpdate is disabled, skip')
            return

        self.git_repository_init(
            repo=self.Repository,
            source='origin',
            branch=self.Branch,
            proxy=self.GitProxy,
            ssl_verify=self.SSLVerify,
            keep_changes=self.KeepLocalChanges,
        )
