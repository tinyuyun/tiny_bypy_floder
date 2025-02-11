import os
import logging
import errno
from fusepy import FUSE, FuseOSError, Operations
from subprocess import Popen, PIPE
import tempfile

# 配置日志
logging.basicConfig(level=logging.DEBUG)


class ByPyFuse(Operations):
    def __init__(self):
        self.root = '/'  # 虚拟根目录
        self.temp_dir = tempfile.mkdtemp()  # 临时下载目录
        self.cached_files = {}  # 缓存文件和目录列表

    def _run_bypy(self, command):
        """执行bypy命令并返回结果"""
        try:
            cmd = f'bypy {command}'
            logging.debug(f"Running command: {cmd}")
            process = Popen(cmd, shell=True, stdout=PIPE, stderr=PIPE)
            stdout, stderr = process.communicate(timeout=60)
            if process.returncode != 0:
                logging.error(f"bypy error: {stderr.decode()}")
                # 使用正确的错误码（例如 errno.EIO）
                raise FuseOSError(errno.EIO)
            return stdout.decode().strip()
        except Exception as e:
            logging.error(f"Error running bypy command: {e}")
            # 使用正确的错误码（例如 errno.EIO）
            raise FuseOSError(errno.EIO) from e

    def _list_files(self, path):
        """列出路径下的文件和目录"""
        if path in self.cached_files:
            return self.cached_files[path]  # 返回缓存的文件列表

        remote_path = path.lstrip('/')
        result = self._run_bypy(f'list {remote_path}')
        files = []
        for line in result.split('\n'):
            if line.strip() and not line.startswith('/'):  # 忽略第一行
                parts = line.split()
                if len(parts) >= 2:
                    file_type = parts[0]  # D 或 F
                    name = parts[1]  # 文件或目录名称
                    is_dir = (file_type == 'D')
                    files.append((name, is_dir))
        self.cached_files[path] = files  # 缓存文件列表
        return files

    def getattr(self, path, fh=None):
        """获取文件/目录属性"""
        logging.debug(f"getattr: {path}")
        st = {
            'st_mode': 0,
            'st_nlink': 1,
            'st_size': 4096,
            'st_ctime': 0,
            'st_mtime': 0,
            'st_atime': 0,
            'st_uid': os.getuid(),
            'st_gid': os.getgid()
        }

        if path == '/':
            st['st_mode'] = 0o40755  # 根目录权限
            return st

        parent_dir = os.path.dirname(path)
        name = os.path.basename(path)
        files = self._list_files(parent_dir)
        for file_name, is_dir in files:
            if file_name == name:
                if is_dir:
                    st['st_mode'] = 0o40755
                else:
                    st['st_mode'] = 0o100644
                    # 获取文件大小（需要实际下载文件，此处简化为4096）
                return st
        raise FuseOSError(os.errno.ENOENT)

    def readdir(self, path, fh):
        """读取目录内容"""
        logging.debug(f"readdir: {path}")
        entries = ['.', '..']
        files = self._list_files(path)
        entries.extend([name for name, _ in files])
        return entries

    def read(self, path, size, offset, fh):
        """读取文件内容（仅支持小文件）"""
        remote_path = path.lstrip('/')
        local_path = os.path.join(self.temp_dir, os.path.basename(path))

        # 如果文件尚未下载，则下载文件
        if not os.path.exists(local_path):
            self._run_bypy(f'download {remote_path} {local_path}')

        with open(local_path, 'rb') as f:
            f.seek(offset)
            return f.read(size)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('mountpoint', help='挂载点路径')
    args = parser.parse_args()

    # 启动FUSE
    FUSE(ByPyFuse(), args.mountpoint, foreground=True, allow_other=True, nonempty=True)
