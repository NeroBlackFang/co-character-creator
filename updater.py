"""The editor's updater: finds a newer release, downloads its installer and runs it, with fallback sources.

  python updater.py              say whether a newer version is out (asks the sources in order)
  python updater.py --install    and if so download, verify and run its installer (what the editor's Update button does)

Where to look is update_sources.json (shipped beside this file): manifest URLs tried in order until one answers
(GitHub's latest release, then the Codeberg mirror, then Google Drive). A manifest is latest.json, which
make_release.py writes and publish_release.py uploads to every source:

  {"version": "0.7.1", "file": "CO-Costume-Editor-0.7.1-Setup.exe", "size": 51234567,
   "sha256": "<hex>", "notes": "<release page>", "downloads": ["<GitHub url>", "<Codeberg url>", "<Drive url>"]}

The installer comes from the first of its downloads that works. Each download is checked against size and
sha256, so a broken or tampered file from one source falls through to the next. It is saved in
%LOCALAPPDATA%/CO Costume Editor/updates, then run silently in the editor's current install mode (all users or
only me). Setup closes the editor, updates it in place (settings and data are kept), and starts it again.

Nothing about the player or their costumes is sent: these are plain downloads.
"""
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
USER_DIR = os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'CO Costume Editor')
UPDATES = os.path.join(USER_DIR, 'updates')
SOURCES_FILE = os.path.join(HERE, 'update_sources.json')
AGENT = {'User-Agent': 'CO-Costume-Editor-Updater'}


def current_version():
    text = open(os.path.join(HERE, 'viewer', 'js', 'version.js'), encoding='utf-8').read()
    return re.search(r"VERSION = '([^']+)'", text).group(1)


def version_key(v):
    """'0.7.10' > '0.7.9'; a pre-release ('0.8.0-rc1') sorts before its release ('0.8.0')."""
    main, _, pre = str(v).strip().lstrip('vV').partition('-')
    nums = [int(n) for n in re.findall(r'\d+', main)][:4]
    return nums + [0] * (4 - len(nums)) + [0 if pre else 1, pre]


def is_newer(a, b):
    return version_key(a) > version_key(b)


def sources():
    """The manifest sources [{'name', 'url'}], in the order to try them (entries still holding a {placeholder}
    are skipped)."""
    try:
        with open(SOURCES_FILE, encoding='utf-8') as f:
            return [s for s in json.load(f).get('manifests', []) if s.get('url') and '{' not in s['url']]
    except (OSError, ValueError):
        return []


def _get(url, timeout):
    return urllib.request.urlopen(urllib.request.Request(url, headers=AGENT), timeout=timeout)


def valid_manifest(m):
    return bool(isinstance(m, dict) and isinstance(m.get('version'), str)
                and re.fullmatch(r'[0-9a-f]{64}', str(m.get('sha256', '')))
                and isinstance(m.get('size'), int) and m['size'] > 0
                and isinstance(m.get('downloads'), list) and m['downloads']
                and all(isinstance(u, str) and u.startswith('https://') for u in m['downloads'])
                and re.fullmatch(r'[A-Za-z0-9._-]+\.exe', str(m.get('file', ''))))


def fetch_manifest(log=print):
    """(manifest, source name) from the first source with a valid one, or (None, [errors])."""
    errors = []
    for s in sources():
        try:
            with _get(s['url'], 10) as r:
                m = json.loads(r.read(1 << 20))
            if not valid_manifest(m):
                raise ValueError('not a valid latest.json')
            return m, s['name']
        except Exception as e:  # any failure: try the next source
            errors.append(f"{s['name']}: {e}")
            log(f"Update source {s['name']} failed: {e}")
    return None, errors


def check(log=print):
    """{'current', 'version', 'newer', 'notes', 'source', 'manifest'}, or {'current', 'error'} if no source answered."""
    cur = current_version()
    m, src = fetch_manifest(log)
    if not m:
        return {'current': cur, 'error': 'No update source could be reached. ' + '; '.join(src or ['None are configured.'])}
    return {'current': cur, 'version': m['version'], 'newer': is_newer(m['version'], cur),
            'notes': m.get('notes', ''), 'source': src, 'manifest': m}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def download(manifest, progress=lambda done, total, source: None, log=print):
    """The installer, from the first download URL that gives exactly the right file; returns its path."""
    os.makedirs(UPDATES, exist_ok=True)
    dest = os.path.join(UPDATES, manifest['file'])
    if os.path.isfile(dest) and os.path.getsize(dest) == manifest['size'] and sha256_file(dest) == manifest['sha256']:
        return dest  # downloaded already
    total, errors = manifest['size'], []
    for url in manifest['downloads']:
        source = urllib.parse.urlsplit(url).hostname or url
        part = dest + '.part'
        try:
            h, done = hashlib.sha256(), 0
            with _get(url, 30) as r, open(part, 'wb') as f:
                if 'text/html' in (r.headers.get('Content-Type') or ''):
                    raise ValueError('got a web page instead of the installer')  # e.g. a Drive sign-in or warning page
                while True:
                    block = r.read(1 << 16)
                    if not block:
                        break
                    done += len(block)
                    if done > total:
                        raise ValueError('larger than the release says')
                    h.update(block)
                    f.write(block)
                    progress(done, total, source)
            if done != total or h.hexdigest() != manifest['sha256']:
                raise ValueError(f'the file does not match the release (got {done} of {total} bytes, or the checksum differs)')
            os.replace(part, dest)
            return dest
        except Exception as e:
            errors.append(f'{source}: {e}')
            log(f'Download from {source} failed: {e}')
            try:
                os.remove(part)
            except OSError:
                pass
    raise RuntimeError('The update could not be downloaded from any source:\n' + '\n'.join(errors))


def install_mode():
    """Inno Setup's switch for the editor's current install mode: Program Files means all users, else only me."""
    pf = {os.path.normcase(os.environ[k]) for k in ('ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432') if os.environ.get(k)}
    return '/ALLUSERS' if any(os.path.normcase(HERE).startswith(p + os.sep) for p in pf) else '/CURRENTUSER'


def run_installer(path):
    """Start Setup silently. Windows asks for admin rights for an all-users install. /UPDATE=1 makes Setup start
    the editor again when it's done. Returns at once; Setup closes the running editor itself."""
    import ctypes
    args = f'/SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS {install_mode()} /UPDATE=1'
    rc = ctypes.windll.shell32.ShellExecuteW(None, 'open', path, args, os.path.dirname(path), 1)
    if rc <= 32:
        raise RuntimeError('Setup could not be started' + (' (administrator permission was refused)' if rc == 5 else f' (error {rc})'))
    for n in os.listdir(UPDATES):  # older downloads aren't needed now
        if n != os.path.basename(path):
            try:
                os.remove(os.path.join(UPDATES, n))
            except OSError:
                pass


class Job:
    """One update in the background, for the editor's page to follow (serve.py's /api/update/...)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.state = {'state': 'idle'}

    def status(self):
        with self.lock:
            return dict(self.state)

    def _set(self, **kw):
        with self.lock:
            self.state = {**self.state, **kw}

    def start(self, on_installer_started=None):
        with self.lock:
            if self.state['state'] in ('checking', 'downloading', 'installing', 'started'):
                return False
            self.state = {'state': 'checking'}
        threading.Thread(target=self._run, args=(on_installer_started,), daemon=True).start()
        return True

    def _run(self, on_installer_started):
        try:
            info = check()
            if 'error' in info:
                raise RuntimeError(info['error'])
            if not info['newer']:
                self._set(state='current', version=info['version'])
                return
            m = info['manifest']
            self._set(state='downloading', version=m['version'], done=0, total=m['size'], source=info['source'])
            path = download(m, lambda d, t, s: self._set(done=d, total=t, source=s))
            self._set(state='installing')
            run_installer(path)
            self._set(state='started')
            if on_installer_started:
                on_installer_started()
        except Exception as e:
            self._set(state='error', error=str(e))


def main():
    info = check()
    if 'error' in info:
        sys.exit(info['error'])
    print(f"Installed {info['current']}, newest {info['version']} (from {info['source']})")
    if not info['newer']:
        print('Up to date.')
        return
    if '--install' in sys.argv:
        last = [0.0]

        def show(d, t, s):
            if time.time() - last[0] > 0.5 or d == t:
                last[0] = time.time()
                print(f'\rDownloading from {s}: {d * 100 // t}%', end='', flush=True)
        path = download(info['manifest'], show)
        print(f'\nVerified {path}; starting Setup.')
        run_installer(path)


if __name__ == '__main__':
    main()
