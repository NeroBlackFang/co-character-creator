// About: who made the editor, thanks, and the legal notice. A centred dialog over a darkened page.
// It also tells the player when a newer version is out: serve.py asks the update sources (GitHub, then Codeberg,
// then Google Drive) at most once a day (/api/update, off in Settings). A newer version shows in the version
// label in the corner and at the top of the About box, which in an installed editor has an Update button.
import { VERSION } from './version.js';
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

const INSTALLER = 'https://github.com/NeroBlackFang/co-character-creator/releases/latest/download/CO-Costume-Editor-Setup.exe';
let aboutButton = null, versionLabel = null, newer = null;  // newer: {version, url} of a release newer than this one

// is version a (0.6.10) newer than b (0.6.4)?
function isNewer(a, b) {
  const pa = String(a).split('.').map(n => parseInt(n, 10) || 0), pb = String(b).split('.').map(n => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) > (pb[i] || 0);
  return false;
}

function showVersion() {
  if (!versionLabel) return;
  versionLabel.replaceChildren('v' + VERSION);
  versionLabel.classList.toggle('hasUpdate', !!newer);
  aboutButton?.classList.toggle('hasUpdate', !!newer);
  if (aboutButton) aboutButton.title = newer ? `Version ${newer.version} is available. Who made this, thanks, and the legal notice`
    : 'Who made this, thanks, and the legal notice';
  if (!newer) return;
  const link = el('button', 'updateLink', `v${newer.version} is available`); link.type = 'button';
  link.onclick = () => aboutButton?.click();
  versionLabel.append(' · ', link);
}

// Ask the server for the newest release (not under the test page, which runs offline); quietly does nothing
// when it can't tell. Called at start, and again when Settings turns checking back on.
export async function checkForUpdate() {
  if (new URLSearchParams(location.search).has('test')) return;
  try {
    const r = await fetch('api/update');
    const rel = r.ok ? await r.json() : {};
    newer = rel.version && isNewer(rel.version, VERSION) ? rel : null;
  } catch { newer = null; }
  showVersion();
}
export function clearUpdate() { newer = null; showVersion(); }

export function setupAbout(button, label) {
  aboutButton = button; versionLabel = label;
  showVersion();
  checkForUpdate();
  button.onclick = () => {
    document.querySelector('.aboutBackdrop')?.remove();
    const back = el('div', 'modalBackdrop aboutBackdrop'), box = el('div', 'palette aboutDialog');
    box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true'); box.setAttribute('aria-labelledby', 'aboutHead');
    const head = el('div', 'phead', 'CO Costume Editor ' + VERSION); head.id = 'aboutHead';

    // a newer version: where to get it, and that updating keeps everything
    const stops = [];
    let update = null;
    if (newer) {
      update = el('div', 'aboutUpdate');
      const notes = el('a', null, "what's new");
      notes.href = newer.url || 'https://github.com/NeroBlackFang/co-character-creator/releases/latest';
      notes.target = '_blank'; notes.rel = 'noopener noreferrer';
      const line = el('p');
      if (newer.canInstall) {
        // the installed editor updates itself: updater.py downloads Setup (GitHub, else Codeberg, else Google
        // Drive), checks it and runs it; the editor closes and Setup opens it again
        const go = el('button', null, `Update to ${newer.version}`); go.type = 'button';
        const status = el('p', 'aboutSub');
        line.append(el('span', 'aboutSub', 'New version!'), ' ', go, ' (', notes, ')');
        update.append(line, status, el('p', null, 'Your settings and the editor\'s data are kept. Windows may ask for permission; the editor closes and opens again when the update is done.'));
        go.onclick = async () => {
          go.disabled = true;
          const show = s => {
            status.textContent = s.state === 'checking' ? 'Finding the update…'
              : s.state === 'downloading' ? `Downloading from ${s.source || 'the update source'}… ${s.total ? Math.floor(100 * s.done / s.total) : 0}%`
              : s.state === 'installing' ? 'Starting the installer…'
              : s.state === 'started' ? 'Updating. The editor will reopen by itself; you can close this window.'
              : s.state === 'current' ? 'You already have the newest version.'
              : s.state === 'error' ? 'The update failed: ' + s.error : '';
          };
          try {
            const r = await fetch('api/update/install', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
            let s = await r.json();
            if (!r.ok) { show({ state: 'error', error: s.error || r.statusText }); go.disabled = false; return; }
            while (['checking', 'downloading', 'installing', 'idle'].includes(s.state)) {
              show(s);
              await new Promise(res => setTimeout(res, 500));
              s = await (await fetch('api/update/status')).json();
            }
            show(s);
            if (s.state === 'error') go.disabled = false;
          } catch {  // the server stopped: Setup has taken over
            show({ state: 'started' });
          }
        };
        stops.push(go, notes);
      } else {
        const get = el('a', null, `Download version ${newer.version}`);
        get.href = INSTALLER; get.target = '_blank'; get.rel = 'noopener noreferrer';
        line.append(el('span', 'aboutSub', 'New version!'), ' ', get, ' (', notes, ').');
        update.append(line, el('p', null, 'Run the installer to update. It keeps your settings and the editor\'s data, so it starts straight away.'));
        stops.push(get, notes);
      }
    }

    const made = el('p');
    made.append('Made by ', el('b', null, '@sadders1'), '. Feel free to hit me up in-game!');
    // bugs and ideas: the project's GitHub issues, as on the website
    const bugs = el('p'), bugLink = el('a', null, 'Open an issue on GitHub.');
    bugLink.href = 'https://github.com/NeroBlackFang/co-character-creator/issues';
    bugLink.target = '_blank'; bugLink.rel = 'noopener noreferrer';
    bugs.append('Found a bug or have an idea? ', bugLink);

    const thanks = el('div', 'aboutThanks');
    const logo = el('img'); logo.src = 'img/adventurers.svg'; logo.alt = 'Adventurers supergroup emblem';
    const link = el('a', null, 'codexheroes.com/co/adventurers');
    link.href = 'https://codexheroes.com/co/adventurers/'; link.target = '_blank'; link.rel = 'noopener noreferrer';
    const words = el('div');
    const said = el('p');
    said.append(el('span', 'aboutSub', 'Special thanks'), ' to the Adventurers supergroup for their help with testing.');
    words.append(said, link);
    thanks.append(logo, words);

    const legal = el('div', 'aboutLegal');
    legal.append(
      el('p', null, 'Champions Online, its characters, costume pieces, artwork and other game content are the property of their respective owners.'),
      el('p', null, 'The CO Costume Editor is an unofficial fan project. It is not affiliated with, endorsed by or supported by Cryptic Studios, Arc Games or any owner of Champions Online.'),
      el('p', null, 'It reads the game files from your own installation and does not include or redistribute them. Use it at your own risk.'));

    const row = el('div', 'row'), close = el('button', null, 'Close'); close.type = 'button';
    row.append(close);
    box.append(head, ...(update ? [update] : []), made, bugs, thanks, legal, row);
    back.append(box);
    document.body.append(back);
    const done = () => { back.remove(); button.focus(); };
    close.onclick = done;
    back.addEventListener('mousedown', e => { if (e.target === back) done(); });  // click outside closes
    stops.push(bugLink, link, close);
    back.addEventListener('keydown', e => {
      if (e.key === 'Escape') done();
      else if (e.key === 'Tab') {  // keep focus in the dialog: its links, then Close
        e.preventDefault();
        const i = stops.indexOf(document.activeElement);
        stops[(i + (e.shiftKey ? stops.length - 1 : 1)) % stops.length].focus();
      }
    });
    close.focus();
  };
}
