#!/usr/bin/env python3
#: ARCHIVE NOTES - gallery sync, run every 5 minutes from buffalo's crontab on hp-server:
#:   */5 * * * * /usr/bin/nice -n 10 /usr/bin/python3 /home/buffalo/site-tools/gallery-sync.py >>/home/buffalo/site-tools/gallery-sync.log 2>&1
#: Needs Pillow and pillow-heif, installed privately in ~/site-tools/lib (not system-wide). An flock lock file stops
#: two runs overlapping. Originals are moved outside the web root; only stripped web copies are published.
"""Buffalo gallery sync (runs from buffalo's crontab every 5 min).

Drop photos into the site's gallery/ folder. Each new photo is:
  1. moved (original, untouched) to ~/gallery-originals/  (outside the web root)
  2. replaced in gallery/ by a web copy: rotation applied, EXIF/GPS stripped,
     max 2000px long edge, JPEG q82
  3. given a thumbnail in gallery/thumbs/
gallery/gallery.json is then rebuilt; gallery/gallery.html reads it.
Deleting a photo from gallery/ removes it (and its thumbnail) from the page.
Log: ~/site-tools/gallery-sync.log
"""
import os, sys, json, re, time, fcntl, tempfile, datetime, shutil
HOME = os.path.expanduser('~')
sys.path.insert(0, os.path.join(HOME, 'site-tools/lib'))
from PIL import Image, ImageOps
try:
    import pillow_heif; pillow_heif.register_heif_opener()
except Exception:
    pass

GAL = '/var/www/html/site/Web Server Backup 18dec25/gallery'
THUMBS = os.path.join(GAL, 'thumbs')
ORIG = os.path.join(HOME, 'gallery-originals')
STATE = os.path.join(HOME, 'site-tools/gallery-state.json')
LOG = os.path.join(HOME, 'site-tools/gallery-sync.log')
EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif')
MAX, THUMB, Q, SETTLE = 2000, 480, 82, 60   # SETTLE: skip files modified < 60 s ago (still uploading)

def log(msg):
    with open(LOG, 'a') as f:
        f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + msg + '\n')

#: When a photo was taken: EXIF date, else a date in the file name, else the file time.
def taken(im, name, path):
    try:
        ex = im.getexif()
        v = ex.get_ifd(0x8769).get(0x9003) or ex.get(0x0132)
        if v:
            return datetime.datetime.strptime(str(v).strip()[:19], '%Y:%m:%d %H:%M:%S').strftime('%Y-%m-%dT%H:%M:%S')
    except Exception:
        pass
    m = re.search(r'(20\d\d)[-_]?(\d\d)[-_]?(\d\d)[ _T-]?(\d\d)?[.:_-]?(\d\d)?[.:_-]?(\d\d)?', name)
    if m:
        try:
            parts = [int(x) if x else 0 for x in m.groups()]
            return datetime.datetime(*parts).strftime('%Y-%m-%dT%H:%M:%S')
        except ValueError:
            pass
    return datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%dT%H:%M:%S')

#: Write to a temp file in the same folder, then rename over the destination (no half-written images are ever served).
def atomic_save(im, dest, **kw):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dest), prefix='.tmp_', suffix='.jpg'); os.close(fd)
    im.save(tmp, 'JPEG', **kw); os.chmod(tmp, 0o644); os.replace(tmp, dest)

def unique(path):
    if not os.path.exists(path): return path
    b, e = os.path.splitext(path); n = 2
    while os.path.exists(f'{b}-{n}{e}'): n += 1
    return f'{b}-{n}{e}'

#: One sync pass: process new photos (rotate, strip EXIF/GPS, resize, thumbnail), drop deleted ones, rebuild gallery.json.
def main():
    os.makedirs(THUMBS, exist_ok=True); os.makedirs(ORIG, mode=0o700, exist_ok=True)
    lock = open(os.path.join(HOME, 'site-tools/.gallery.lock'), 'w')
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError: return
    try: state = json.load(open(STATE))
    except Exception: state = {}
    now = time.time(); changed = False
    files = sorted(f for f in os.listdir(GAL) if f.lower().endswith(EXTS) and not f.startswith('.') and os.path.isfile(os.path.join(GAL, f)))
    for f in files:
        p = os.path.join(GAL, f); st = os.stat(p); s = state.get(f)
        if s and s['size'] == st.st_size and int(s['mtime']) == int(st.st_mtime):
            continue                                   # already processed
        if now - st.st_mtime < SETTLE:
            continue                                   # still uploading; next run
        try:
            im = Image.open(p); im.load()
        except Exception as e:
            log(f'SKIP {f}: cannot read ({e})'); continue
        when = taken(im, f, p)
        icc = im.info.get('icc_profile')
        im = ImageOps.exif_transpose(im)
        if im.mode not in ('RGB', 'L'):
            bg = Image.new('RGB', im.size, (17, 17, 17))
            im = im.convert('RGBA'); bg.paste(im, mask=im.split()[-1]); im = bg
        web = im.copy(); web.thumbnail((MAX, MAX), Image.LANCZOS)
        out = f if f.lower().endswith(('.jpg', '.jpeg')) else os.path.splitext(f)[0] + '.jpg'
        if out != f and os.path.exists(os.path.join(GAL, out)): out = os.path.basename(unique(os.path.join(GAL, out)))
        dst_orig = unique(os.path.join(ORIG, f))
        shutil.move(p, dst_orig); os.chmod(dst_orig, 0o600)
        kw = dict(quality=Q, optimize=True, progressive=True)
        if icc: kw['icc_profile'] = icc
        atomic_save(web, os.path.join(GAL, out), **kw)
        th = im.copy(); th.thumbnail((THUMB, THUMB), Image.LANCZOS)
        atomic_save(th, os.path.join(THUMBS, os.path.splitext(out)[0] + '.jpg'), quality=78, optimize=True, progressive=True)
        st2 = os.stat(os.path.join(GAL, out))
        state.pop(f, None)
        state[out] = {'size': st2.st_size, 'mtime': st2.st_mtime, 'w': web.size[0], 'h': web.size[1], 'date': when, 'orig': dst_orig}
        changed = True
        log(f'ADD {f} -> {out} ({web.size[0]}x{web.size[1]}), original kept at {dst_orig}')
    present = set(os.listdir(GAL))
    for f in list(state):
        if f not in present:
            t = os.path.join(THUMBS, os.path.splitext(f)[0] + '.jpg')
            if os.path.exists(t): os.remove(t)
            del state[f]; changed = True; log(f'REMOVE {f} (deleted from gallery/; original stays in {ORIG})')
    listing = os.path.join(GAL, 'gallery.json')
    if changed or '--rebuild' in sys.argv or not os.path.exists(listing):
        items = [{'src': f, 'thumb': 'thumbs/' + os.path.splitext(f)[0] + '.jpg', 'w': v['w'], 'h': v['h'], 'date': v['date'], 'v': int(v['mtime'])}
                 for f, v in state.items()]
        items.sort(key=lambda x: x['date'], reverse=True)
        fd, tmp = tempfile.mkstemp(dir=GAL, prefix='.tmp_', suffix='.json'); os.close(fd)
        with open(tmp, 'w') as fh: json.dump({'updated': time.strftime('%Y-%m-%dT%H:%M:%S'), 'photos': items}, fh, indent=0)
        os.chmod(tmp, 0o644); os.replace(tmp, listing)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(STATE)); os.close(fd)
        with open(tmp, 'w') as fh: json.dump(state, fh)
        os.replace(tmp, STATE)

if __name__ == '__main__':
    main()
