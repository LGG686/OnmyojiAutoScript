# This Python file uses the following encoding: utf-8
# copy from alas https://github.com/LmeSzinc/AzurLaneAutoScript
import hashlib
import json
import os
from urllib.parse import urlparse

from deploy.config import DeployConfig
from deploy.logger import logger
from deploy.utils import *


class PipManager(DeployConfig):
    @cached_property
    def python(self):
        return self.filepath("PythonExecutable")

    @cached_property
    def requirements_file(self):
        if self.RequirementsFile == 'requirements.txt':
            return 'requirements.txt'
        else:
            return self.filepath("RequirementsFile")

    @cached_property
    def pip(self):
        return f'"{self.python}" -m pip'

    @cached_property
    def stamp_file(self):
        return os.path.join(os.path.dirname(self.python), '.oas_deps_stamp')

    def requirements_digest(self):
        """
        Returns:
            str: Digest of what decides the installed packages,
                or None if it cannot be computed.
        """
        try:
            with open(self.requirements_file, 'rb') as f:
                content = f.read()
        except OSError as e:
            logger.info(f'Read {self.requirements_file} failed: {e}')
            return None

        digest = hashlib.sha256()
        digest.update(self.python.encode('utf-8'))
        digest.update(content)
        return digest.hexdigest()

    def dependencies_installed(self, digest):
        if digest is None:
            return False
        try:
            with open(self.stamp_file, 'r', encoding='utf-8') as f:
                return json.load(f).get('digest') == digest
        except (OSError, ValueError, AttributeError):
            return False

    def mark_dependencies_installed(self, digest):
        if digest is None:
            return
        try:
            with open(self.stamp_file, 'w', encoding='utf-8') as f:
                json.dump({'digest': digest}, f)
        except OSError as e:
            logger.info(f'Write {self.stamp_file} failed: {e}')

    def pip_install(self):
        logger.hr('Update Dependencies', 0)

        if not self.InstallDependencies:
            logger.info('InstallDependencies is disabled, skip')
            return

        digest = self.requirements_digest()
        if self.dependencies_installed(digest):
            logger.hr('Update Dependencies', 1)
            logger.info('Requirements unchanged since last install, skip')
            return

        logger.hr('Check Python', 1)
        self.execute(f'"{self.python}" --version')

        arg = []
        if self.PypiMirror:
            mirror = self.PypiMirror
            arg += ['-i', mirror]
            # Trust http mirror or skip ssl verify
            if 'http:' in mirror or not self.SSLVerify:
                arg += ['--trusted-host', urlparse(mirror).hostname]
        elif not self.SSLVerify:
            arg += ['--trusted-host', 'pypi.org']
            arg += ['--trusted-host', 'files.pythonhosted.org']

        # Don't update pip, just leave it.
        # logger.hr('Update pip', 1)
        # self.execute(f'"{self.pip}" install --upgrade pip{arg}')
        arg += ['--disable-pip-version-check']

        logger.hr('Update Dependencies', 1)
        arg = ' ' + ' '.join(arg) if arg else ''
        self.execute(f'{self.pip} install -r {self.requirements_file}{arg}')
        self.mark_dependencies_installed(digest)
