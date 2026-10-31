"""Portable n8n launcher: explicit local setup, localhost helpers, no schedule changes."""
import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIVATE = ROOT / '.local'
VENV = ROOT / '.venv'
PYTHON = VENV / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
N8N = ROOT / 'node_modules' / 'n8n' / 'bin' / 'n8n'
NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def dirs():
    for path in [PRIVATE / 'n8n', PRIVATE / 'logs', *(ROOT / 'outputs' / f'lab{i}' for i in range(3, 8))]:
        path.mkdir(parents=True, exist_ok=True)


def node_version():
    executable = shutil.which('node')
    if not executable:
        return None, None
    text = subprocess.check_output([executable, '--version'], text=True, timeout=5).strip()
    match = re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)', text)
    return executable, tuple(map(int, match.groups())) if match else None


def supported(version):
    return version is not None and (20, 19, 0) <= version < (25, 0, 0)


def setup(browser=False):
    node, version = node_version()
    if not node or not supported(version):
        raise RuntimeError('Установите Node.js 22 (поддерживаются версии 20.19–24).')
    npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
    if not npm:
        raise RuntimeError('npm не найден в PATH.')
    subprocess.run([sys.executable, '-m', 'venv', str(VENV)], cwd=ROOT, check=True)
    subprocess.run([str(PYTHON), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')], cwd=ROOT, check=True)
    subprocess.run([npm, 'install', '--no-audit', '--no-fund'], cwd=ROOT, check=True)
    if browser:
        subprocess.run([str(PYTHON), '-m', 'playwright', 'install', 'chromium'], cwd=ROOT, check=True)
    print('Локальные зависимости установлены.')


def check(no_helpers=False):
    node, version = node_version()
    version_text = '.'.join(map(str, version)) if version else 'не найден'
    print(f'Корень: {ROOT}\nPython: {sys.version.split()[0]}\nNode: {version_text} (рекомендуется 22)')
    print(f'Локальное окружение Python: {"есть" if PYTHON.is_file() else "нет"}')
    print(f'Локальный n8n: {"есть" if N8N.is_file() else "нет"}')
    package = ROOT / 'node_modules' / 'n8n' / 'package.json'
    installed = None
    if package.is_file():
        installed = json.loads(package.read_text(encoding='utf8')).get('version')
        print('Версия n8n:', installed or 'неизвестна')
    dependencies = False
    if PYTHON.is_file():
        result = subprocess.run([str(PYTHON), '-c', 'import requests,socks,pandas,psutil,bs4,playwright,brotli'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        dependencies = result.returncode == 0
    print('Python-зависимости:', 'готовы' if dependencies else 'нет')
    browser_ready = no_helpers
    if dependencies and not no_helpers:
        browser_test = (
            'import sys; from pathlib import Path; from playwright.sync_api import sync_playwright\n'
            'with sync_playwright() as p:\n'
            '    sys.exit(0 if Path(p.chromium.executable_path).is_file() else 1)\n'
        )
        result = subprocess.run([str(PYTHON), '-c', browser_test],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        browser_ready = result.returncode == 0
    if no_helpers:
        print('Chromium: не требуется при --no-helpers')
    else:
        print('Chromium:', 'готов' if browser_ready else 'нет; выполните python launch.py --setup --browser')
    input_ready = (ROOT / 'labs/lab6_3/nocode/input.json').is_file()
    print('Вход ЛР6:', 'есть' if input_ready else 'нет')
    for directory in (PRIVATE, ROOT / 'outputs'):
        with tempfile.TemporaryFile(dir=directory):
            pass
    print('Запись в outputs и .local проверена. Сетевые порты в --check не затрагиваются.')
    return 0 if node and supported(version) and dependencies and browser_ready and N8N.is_file() and installed == '1.121.3' and input_ready else 1


def listening(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(('127.0.0.1', port)) == 0


def health(port):
    try:
        with NO_PROXY.open(f'http://127.0.0.1:{port}/health', timeout=2) as response:
            return json.load(response)
    except Exception:
        return {}


def helper(port, script, identity, children):
    if listening(port):
        data = health(port)
        if data.get('service') == identity and Path(data.get('workspace', '')).resolve() == ROOT:
            print(f'{identity}: уже работает в этом комплекте на порту {port}.')
            return
        raise RuntimeError(f'Порт {port} занят другим сервисом или комплектом; освободите порт. Чужой процесс не изменён.')
    log = (PRIVATE / 'logs' / (script + '.log')).open('a', encoding='utf8')
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    try:
        child = subprocess.Popen([str(PYTHON), '-u', str(ROOT / 'services' / script)], cwd=ROOT,
                                 stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
    finally:
        log.close()
    children.append(child)
    for _ in range(80):
        if child.poll() is not None:
            raise RuntimeError(f'{identity} завершился; проверьте .local/logs/{script}.log')
        data = health(port)
        if data.get('service') == identity and Path(data.get('workspace', '')).resolve() == ROOT:
            print(f'{identity} запущен на {port}.')
            return
        time.sleep(0.25)
    raise RuntimeError(f'{identity} не ответил; проверьте .local/logs/{script}.log')


def stop_owned(children):
    for child in reversed(children):
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def start(port, no_helpers):
    node, version = node_version()
    if not node or not supported(version) or not PYTHON.is_file() or not N8N.is_file():
        raise RuntimeError('Не установлены зависимости: сначала выполните python launch.py --setup.')
    if listening(port):
        raise RuntimeError(f'Порт n8n {port} занят; выберите свободный через --port. Чужой процесс не изменён.')
    env = os.environ.copy()
    allowed_files = ';'.join(str(path) for path in (ROOT / 'outputs', ROOT / 'labs' / 'lab6_3' / 'nocode'))
    env.update(N8N_USER_FOLDER=str(PRIVATE / 'n8n'), N8N_RESTRICT_FILE_ACCESS_TO=allowed_files,
               N8N_LISTEN_ADDRESS='127.0.0.1', N8N_HOST='127.0.0.1', N8N_PORT=str(port),
               N8N_PROTOCOL='http', N8N_EDITOR_BASE_URL=f'http://127.0.0.1:{port}',
               N8N_SECURE_COOKIE='false', N8N_DIAGNOSTICS_ENABLED='false',
               N8N_VERSION_NOTIFICATIONS_ENABLED='false', N8N_TEMPLATES_ENABLED='false',
               NODE_FUNCTION_ALLOW_BUILTIN='crypto',
               NO_PROXY='127.0.0.1,localhost', no_proxy='127.0.0.1,localhost', PYTHONIOENCODING='utf-8')
    children = []
    try:
        if not no_helpers:
            helper(8894, 'render_api.py', 'lab4-renderer', children)
            helper(5686, 'notification_server.py', 'lab5-notifications', children)
        print(f'n8n: http://127.0.0.1:{port}/; остановка — Ctrl+C.', flush=True)
        child = subprocess.Popen([node, str(N8N), 'start'], cwd=ROOT, env=env)
        children.append(child)
        return child.wait()
    except KeyboardInterrupt:
        print('\nОстановка собственных дочерних процессов.')
        return 0
    finally:
        stop_owned(children)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', action='store_true', help='установить локальные Python и n8n зависимости')
    parser.add_argument('--browser', action='store_true', help='при --setup установить Chromium для Playwright')
    parser.add_argument('--check', action='store_true', help='проверить зависимости без запуска сервисов')
    parser.add_argument('--port', type=int, default=5679, help='порт n8n (по умолчанию 5679)')
    parser.add_argument('--no-helpers', action='store_true', help='запустить только n8n, без сервисов ЛР4 и ЛР5')
    args = parser.parse_args()
    if args.browser and not args.setup: parser.error('--browser применяется вместе с --setup')
    if not 1 <= args.port <= 65535: parser.error('Порт должен быть от 1 до 65535')
    try:
        os.chdir(ROOT)
        dirs()
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(PRIVATE / 'browsers')
        os.environ['PYTHONIOENCODING'] = 'utf-8'
        if args.setup:
            setup(args.browser)
            return 0
        if args.check:
            return check(args.no_helpers)
        return start(args.port, args.no_helpers)
    except (OSError, RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f'Ошибка: {exc}', file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
