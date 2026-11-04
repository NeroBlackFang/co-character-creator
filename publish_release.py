"""Publish a release to all three update sources: python publish_release.py [--build] [--notes "text"] [--skip github,codeberg,drive]

  --build   run "make_release.py --installer" first (otherwise dist/ must already hold this version's Setup.exe)

Uses release_config.json. For version <v> (viewer/js/version.js) it:
  1. writes dist/latest.json: version, size and SHA-256 of CO-Costume-Editor-<v>-Setup.exe, and its three download
     URLs (GitHub release, Codeberg release, Google Drive), the manifest updater.py reads
  2. GitHub (gh CLI, signed in): pushes the code, tags v<v>, creates the release with the Setup.exe, a copy named
     CO-Costume-Editor-Setup.exe (the README's always-newest link), the zip and latest.json
  3. Codeberg (env CODEBERG_TOKEN, an access token with repository write access): pushes the code and tag,
     creates the release and uploads the same files
  4. Google Drive (Drive for desktop's synced folder, release_config drive_folder): overwrites
     CO-Costume-Editor-Setup.exe and latest.json there (overwriting keeps their Drive IDs, which updater.py and
     latest.json use), and keeps a versioned backup: releases/<v>/ with the Setup.exe, the zip and a git bundle
     of the whole repository
  5. commits latest.json into the repository and pushes it to both remotes (Codeberg's raw latest.json is that
     source's manifest), last, so no manifest points at files not uploaded yet

The Drive files must be shared "anyone with the link" once (they keep it when overwritten).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_release  # noqa: E402

DIST = os.path.join(HERE, 'dist')
STABLE = 'CO-Costume-Editor-Setup.exe'
GH = shutil.which('gh') or r'C:\Program Files\GitHub CLI\gh.exe'


def run(*cmd, **kw):
    print('>', ' '.join(cmd), flush=True)
    return subprocess.run(cmd, cwd=HERE, check=True, **kw)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def config():
    c = json.load(open(os.path.join(HERE, 'release_config.json'), encoding='utf-8'))
    if '{' in c['github']:
        sys.exit('release_config.json: set "github" (owner/repo)')
    c['use_codeberg'] = '{' not in c.get('codeberg', '{')  # not set up yet: skipped
    return c


def remotes(c):
    return ['origin'] + (['codeberg'] if c['use_codeberg'] else [])


def drive_url(file_id):
    return f'https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t'


def manifest(c, v, exe, notes):
    tag, name = f'v{v}', os.path.basename(exe)
    downloads = [f'https://github.com/{c["github"]}/releases/download/{tag}/{name}']
    if c['use_codeberg']:
        downloads.append(f'https://codeberg.org/{c["codeberg"]}/releases/download/{tag}/{name}')
    if c.get('drive_installer_id'):
        downloads.append(drive_url(c['drive_installer_id']))
    return {'version': v, 'file': name, 'size': os.path.getsize(exe), 'sha256': sha256(exe),
            'notes': f'https://github.com/{c["github"]}/releases/tag/{tag}', 'summary': notes,
            'published': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'downloads': downloads}


def tag_and_push(c, v):
    tag = f'v{v}'
    if subprocess.run(['git', 'rev-parse', '-q', '--verify', f'refs/tags/{tag}'], cwd=HERE, capture_output=True).returncode:
        run('git', 'tag', '-a', tag, '-m', f'CO Costume Editor {v}')
    for remote in remotes(c):
        run('git', 'push', remote, 'HEAD:main', tag)


def github(c, v, files, notes):
    run(GH, 'release', 'create', f'v{v}', *files, '--repo', c['github'], '--title', f'CO Costume Editor {v}',
        '--notes', notes or f'CO Costume Editor {v}', '--verify-tag')


def codeberg(c, v, files, notes):
    token = os.environ.get('CODEBERG_TOKEN')
    if not token:
        sys.exit('Set CODEBERG_TOKEN (Codeberg -> Settings -> Applications -> access token with repository write access)')
    api = f'https://codeberg.org/api/v1/repos/{c["codeberg"]}'
    auth = {'Authorization': f'token {token}', 'User-Agent': 'co-costume-editor-publish'}

    def call(url, body=None, ctype='application/json', method='POST'):
        req = urllib.request.Request(url, data=body, method=method, headers={**auth, 'Content-Type': ctype})
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read() or b'{}')
    rel = call(f'{api}/releases', json.dumps({'tag_name': f'v{v}', 'name': f'CO Costume Editor {v}',
                                               'body': notes or f'CO Costume Editor {v}'}).encode())
    for path in files:
        print(f'Uploading {os.path.basename(path)} to Codeberg...', flush=True)
        boundary = 'coeditor' + hashlib.md5(path.encode()).hexdigest()
        data = open(path, 'rb').read()
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="attachment"; filename="{os.path.basename(path)}"\r\n'
                f'Content-Type: application/octet-stream\r\n\r\n').encode() + data + f'\r\n--{boundary}--\r\n'.encode()
        call(f'{api}/releases/{rel["id"]}/assets?name={urllib.parse.quote(os.path.basename(path))}', body,
             f'multipart/form-data; boundary={boundary}')


def drive(c, v, exe, zipped, latest):
    folder = c['drive_folder']
    if not os.path.isdir(os.path.dirname(folder)):
        sys.exit(f'Google Drive for desktop is not mounted ({os.path.dirname(folder)} is missing)')
    backup = os.path.join(folder, 'releases', v)
    os.makedirs(backup, exist_ok=True)
    for f in (exe, zipped):
        shutil.copy2(f, backup)
    run('git', 'bundle', 'create', os.path.join(backup, f'co-character-creator-{v}.bundle'), '--all')
    # the stable files: copying over them keeps their Drive IDs
    shutil.copyfile(exe, os.path.join(folder, STABLE))
    shutil.copyfile(latest, os.path.join(folder, 'latest.json'))
    print(f'Copied to {folder} (Drive for desktop uploads it in the background)')


def main():
    args = sys.argv[1:]
    skip = set(args[args.index('--skip') + 1].split(',')) if '--skip' in args else set()
    notes = args[args.index('--notes') + 1] if '--notes' in args else ''
    c, v = config(), make_release.version()
    if '--build' in args:
        run(sys.executable, os.path.join(HERE, 'make_release.py'), '--installer')
    exe = os.path.join(DIST, f'CO-Costume-Editor-{v}-Setup.exe')
    zipped = os.path.join(DIST, f'CO-Costume-Editor-{v}.zip')
    if not os.path.isfile(exe):
        sys.exit(f'{exe} is missing: run with --build (or make_release.py --installer)')
    if subprocess.run(['git', 'status', '--porcelain'], cwd=HERE, capture_output=True, text=True).stdout.strip():
        sys.exit('Commit your changes first: the release is tagged from the current commit')
    m = manifest(c, v, exe, notes)
    latest = os.path.join(DIST, 'latest.json')
    json.dump(m, open(latest, 'w', encoding='utf-8'), indent=2)
    stable = os.path.join(DIST, STABLE)
    shutil.copyfile(exe, stable)
    files = [exe, stable, zipped, latest] if os.path.isfile(zipped) else [exe, stable, latest]
    tag_and_push(c, v)
    if 'github' not in skip:
        github(c, v, files, notes)
    if 'codeberg' not in skip and c['use_codeberg']:
        codeberg(c, v, files, notes)
    if 'drive' not in skip:
        drive(c, v, exe, zipped, latest)
    # last: the repository's own latest.json (Codeberg's manifest source)
    shutil.copyfile(latest, os.path.join(HERE, 'latest.json'))
    run('git', 'add', 'latest.json')
    run('git', 'commit', '-m', f'Release {v}: latest.json')
    for remote in remotes(c):
        run('git', 'push', remote, 'HEAD:main')
    print(f'\nPublished {v}: {m["sha256"]}')


if __name__ == '__main__':
    main()
