# Direct NAS audio: initial playback support

This branch adds a playback-only external audio resolver to Rivendell 4.5.0.
It does **not** change the managed audio storage or deletion paths. Original
NAS files are never copied, edited, renamed, or unlinked by this resolver.

## Configuration

Mount the existing NAS library read-only (NFS or SMB) at a stable path, e.g.
`/mnt/radio-music`. Keep `/var/snd` as Rivendell's managed workspace.
Add to `/etc/rd.conf`:

```ini
[ExternalAudio]
Root=/mnt/radio-music
References=/var/lib/rivendell/external-media
```

The references directory must be on the **local SSD**, only writable by the
administrator, and readable by the Rivendell audio daemon. Each external cut
has a file named `123456_001.ref` with one UTF-8 **relative** filename:

```text
Power/Artist Name/Track.mp3
```

The audio daemon resolves the file's canonical path, rejects references that
escape the configured root (including symlink escapes), and refuses playback
if the reference is invalid or the NAS file is unavailable. An unmapped cut
continues to use Rivendell's own managed `/var/snd` cart audio.


### Multiple NFS and SMB music sources

A single Rivendell Complete station may now connect **multiple read-only NFS
and SMB shares concurrently**. The Control Center's **Music & NAS** page lists
configured source names, types, actual mountpoints and online/read-only status.
Use **Add another read-only NFS or SMB source** for each share. Names are stable,
lowercase 1–32 characters (such as `current`, `archive`, `imaging`).

Each share receives its own exact mountpoint,
`/mnt/radio-music/NAME`, while the existing
`[ExternalAudio] Root=/mnt/radio-music` remains unchanged. Each SMB share has
separate protected credentials under
`/etc/rivendell-complete/nas-NAME.cred` (0600). NFS shares need none. Linux
`fstab` persists individual mounts using read-only network filesystem
options. No original file is copied or modified.

The **Import library** page selects one source at a time and stores a
qualified cart reference `NAME/path/to/song.mp3`. Files with identical names
on separate shares are distinct; existing references are never renamed. The
station's catalog exporter still resolves all qualified references through the
same native CAE external-audio root.

**Compatibility boundary:** Older installations with a NAS mounted directly
on `/mnt/radio-music` remain operational as a **legacy single mount**. Adding
named mounts on top of that existing mount is refused to prevent obscuring
audio. A deliberate, separate audited migration is required before combining
such a legacy root with named shares. The installer does **not** unmount,
replace or silently migrate the legacy library.

## Scope and limitations

This is a real playout-path change in `cae/cae.cpp`, not a symlink into the
original library. Existing ALSA/JACK drivers support WAV, MPEG/MP3, and Ogg
Vorbis decoding paths; FLAC playout through these drivers is **not** yet
implemented. The catalog must still contain an actual CART/CUTS record with
accurate metadata and duration. This commit does **not** automatically index
NAS files or generate catalog rows.

Critically: `RDCut::pathName()`, imports, waveform editing, export, and
Rivendell's other file-management routines still point at managed cart audio.
The external file is read-only and remains untouched by destructive cart
operations, but waveform and audio-editing interfaces are **not yet external
media-aware**. Do not invoke audio-editing operations on external carts.

A full installer, ingestion tool, scheduler, request bridge, stream encoder,
and qualification suite are subsequent work, **not already operational**.

## On-air qualification gates

1. Validate the exact Ubuntu 26.04 native build on target hardware.
2. Create a valid catalog CART and CUT, then map it to an original NAS MP3.
3. Verify ALSA/JACK playout, cue points, segue overlap, and duration accuracy.
4. Verify that deleting the Rivendell cart cannot remove the NAS original.
5. Verify missing mount, invalid relative path, and symlink escape fail closed.
6. Verify that restarts do not resume unsafely or replace protected events.

**Status: not production-qualified.**
