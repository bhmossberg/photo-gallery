<!-- buffaloben-github-header -->
**Live:** https://buffaloben.com/gallery/gallery.html

This repository is part of [buffaloben.com](https://buffaloben.com).

---

# Photo gallery sync

This is a cron job that publishes photos dropped into the gallery folder on hp-server. Every 5 minutes it picks up new
images (JPEG, PNG, WebP and HEIC/HEIF). It moves each original **outside the web root**, writes a resized web copy
with EXIF stripped plus a thumbnail, orders photos by the date taken (EXIF, then a date in the file name, then the file
time) and rebuilds `gallery/gallery.json`, which the static `gallery.html` page reads in the browser. Web copies
are at most 2000 px and thumbnails 480 px, both at JPEG quality 82. Files modified in the last 60 s are skipped as
still uploading. Deleting a photo from `gallery/` removes it from the page.

- Live page: https://buffaloben.com/gallery/gallery.html. The gallery folder is `/var/www/html/site/Web Server Backup 18dec25/gallery/`.
- Originals: `~/gallery-originals/`. State: `~/site-tools/gallery-state.json`. Log: `~/site-tools/gallery-sync.log`.
- Crontab (user buffalo):

      */5 * * * * /usr/bin/nice -n 10 /usr/bin/python3 /home/buffalo/site-tools/gallery-sync.py >>/home/buffalo/site-tools/gallery-sync.log 2>&1

| File | What |
|---|---|
| `gallery-sync.py` | The job (documented). An `flock` lock file stops runs from overlapping |
| `gallery.html` | The live gallery page, which renders `gallery.json` (snapshot). The photos and `gallery.json` are live content, so they are not archived |

**Dependencies:** Python 3 plus **Pillow** and **pillow-heif**, installed privately in `~/site-tools/lib` (not system-wide).
The paths are hard-coded for hp-server, so read the constants at the top of the script before running it anywhere else.
The gallery is excluded from the site search index.
