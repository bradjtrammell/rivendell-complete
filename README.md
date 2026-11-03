# Rivendell Complete

**Radio automation for internet stations, broadcast stations, and simulcasts — one integrated system.**

Rivendell Complete extends [Rivendell 4](https://github.com/ElvishArtisan/rivendell) into a full station automation platform. The intended product brings together music scheduling, professional playout, live assist, imaging, commercial traffic, listener requests, streaming encoders, and direct access to music already stored on a NAS.

**Internet-only stations do not need an FM transmitter or broadcast sound card.** Terrestrial stations can use the same platform for a local studio/transmitter feed and simultaneous internet streaming.

> **Branch policy:** `master` preserves the original Rivendell 4 source. `dev` is Rivendell Complete 5.0 development. All product engineering happens on `dev`. To finish removing the two superseded remote branches, a repository administrator can run `bash tools/normalize-branches.sh --apply` from a GitHub CLI-authenticated workstation after reviewing its ancestry guards.

> **Release status:** Active development. Some components exist and pass automated tests; a complete Ubuntu 26.04 installation and an uninterrupted on-air station have **not** been verified. This repository is not yet a production release. The [acceptance ledger](docs/complete/ACCEPTANCE.md) tracks every requirement, including unfinished work.

## One system for the entire station

| Station function | Intended experience | Current implementation |
| :-- | :-- | :-- |
| Library and NAS | Index and play original files from their existing NFS/SMB folders, without moving, renaming, re-encoding, or copying them | External playback references and zero-copy indexing implemented; real playout still unqualified |
| On-air automation | Automatic and live-assist programming with reliable logs, cues and crossfades | Rivendell 4 foundation retained; end-to-end automation unqualified |
| Music scheduling | Category rotations, artist/album/title separation, intelligent clocks and real-time top-hour backtiming | Offline planning implemented; continuous live reflow unfinished |
| Station imaging | IDs, liners, jingles and sweepers that can play over safe song intros | PyPAD/SoundPanel foundations; physical mix unverified |
| Commercial traffic | Protected paid spots, break groups and precise scheduled events | Offline protected spot breaks; aircheck proof missing |
| Listener requests | Built-in authenticated requests, eligibility, moderation, automatic queueing and verified playback | API and guarded insertion present; playback confirmation unfinished |
| Streaming | Built-in same-PC SHOUTcast v1/v2 and Icecast, with now-playing metadata and reconnect | GlassCoder integration implemented; server handshakes unverified |
| Local output | Studio audio / transmitter link alongside simultaneous streaming | Rivendell audio and JACK routing components; real hardware unverified |
| Recovery | Recover from NAS, service, audio and encoder failures without dead air | Partial monitoring and reconnection; emergency failover missing |
| Installation | One dependable setup on Ubuntu 26.04 with all station features configured | Development-only installer; Debian package and fresh-install qualification pending |

Every row above is part of the product scope. **Implemented code is not automatically a verified feature.** See [all 56 tracked requirements](docs/complete/ACCEPTANCE.md) for the precise acceptance criteria.

## Built for both kinds of radio

### Internet radio

Run a complete online station on one Linux PC: scheduled playlists, automation, jingles and IDs, request intake, and direct encoding to SHOUTcast or Icecast. No terrestrial transmission equipment is needed.

### AM / FM and other terrestrial radio

Operate local audio for studio or transmitter links while feeding one or more online listening streams. Keep protected legal IDs, traffic/commercial breaks, live assist and local on-air controls.

### Stations with existing NAS libraries

Keep the original music files **exactly where they are**. Rivendell Complete must treat an existing NAS share as a read-only source, with a separate local metadata catalog and small Rivendell-controlled workspace. A cart record may point to an original path, but that does not authorize modifying the source file.

```text
Existing music on NAS (read-only NFS / SMB)
                    |
     External media index and cart references
                    |
      Rivendell Complete automation
       /           |            \
  Live assist   Imaging / IDs   Scheduling
       \           |            /
                Audio mix
                 /     \
    Local studio output   SHOUTcast / Icecast
    (when applicable)     (internet listening)
```

**Zero-copy rule:** never duplicate the NAS music library, silently import songs into another audio store, or change an original file for playback, catalog edits, or deletion. Cue points, rotations and play history belong in station metadata. Supported media formats must include MP3, WAV, Ogg Vorbis and FLAC; remaining playback/format gaps are tracked in the acceptance ledger.

## Deployment target

The initial qualification profile is:

| Item | Specification |
| :-- | :-- |
| OS | Ubuntu **26.04 LTS**, x86-64 |
| Memory | **8 GB RAM** |
| Boot/system drive | **128 GB SSD** |
| Stations per computer | **One** |
| Music location | Existing NAS paths; NFS or SMB mounted **read-only** |
| Database | Local MariaDB, on the system SSD |
| Playout/encoding | Station PC, with configured local output and/or internet streams |

These specifications are an initial supported target, **not** a restriction that Rivendell Complete can only serve that hardware or terrestrial broadcasters.

### One-command installation on a fresh Ubuntu 26.04 workstation

Log in as the regular desktop user (not root). In your existing checkout,
paste this one command:

```bash
cd ~/rivendell-complete && git fetch origin dev && git switch dev && git merge --ff-only origin/dev && bash tools/one-shot-install.sh
```

If sudo expires after native compilation, rerun the command to reuse the
already compiled packages and resume installation without rebuilding them.
The installer also recognizes a previously interrupted database-initialization
stage only when its own first-install marker exists, the expected configuration
is present, and the database has zero tables. Fully installed stations are left
unchanged. Unexpected or inconsistent partial states are explicitly refused
without deleting or overwriting configuration or database records.

The installer runs directly in the current SSH shell, without a detached
session or terminal multiplexer. The streaming dependency installer waits up to
300 seconds for another APT/dpkg transaction instead of deleting lock files
or interrupting an Ubuntu update. The user service files are staged even when
an SSH-only session cannot contact the per-user systemd manager. It prompts for sudo, reuses existing native
packages when available (or builds from source), configures local MariaDB,
and stages streaming tools and user units without activating a live stream.
It also installs the implemented catalog, scheduler, request, live-request,
and diagnostic CLI tools in `~/.local/bin`, without enabling public services.
Development regression tests (including network/socket tests) run only in
explicit check-only mode, never in installation mode.
It saves a private log under `~/rivendell-install-logs/`; keep SSH connected
through installation. It refuses to overwrite an existing Rivendell
installation or database.

**Status:** Experimental. Native packaging and end-to-end fresh installation
have not passed qualification. A build/install error is possible; consult the
log rather than wiping the test workstation.

### Complete currently available station components after native installation

For an existing 4.5.0-1 Ubuntu 26.04 machine, run this **foreground** command
as the normal desktop user to stage the actual implemented components without
rebuilding Rivendell or resetting the database:

```bash
cd ~/rivendell-complete && git fetch origin dev && git switch dev && git merge --ff-only origin/dev && bash tools/finish-complete.sh
```

The completion command installs available command-line catalog, offline clock,
request and diagnostics tools, plus missing user desktop shortcuts for existing
Rivendell applications, before attempting GlassCoder/JACK installation.
The streaming scripts and disabled user service units are staged even if APT
is locked. Already-installed GlassCoder/JACK packages do not trigger APT. Ubuntu 26.04
ships `jack_lsp`, `jack_connect` and `jack_disconnect` in
`jack-example-tools` rather than `jack-tools`, so the installer explicitly
installs and verifies that fourth dependency even with no recommends.
Optional station group and service names are checked against the live database. If APT
is locked by another process it leaves that transaction alone and exits with
status 2; already-staged utilities remain intact. Use `--no-packages` to stage
only user tools while investigating the unrelated package manager.

When a real service and music group already exist in the Rivendell database,
the optional `--service EXISTING_SERVICE --request-group EXISTING_GROUP`
arguments stage (but do not enable) the log-generation timer and protected
loopback listener-request API. The names must be those actually configured in
RDAdmin. Public listener requests, stream credentials, NAS mount paths, audio
routing, live scheduling and GUI integration still require commissioning or
additional engineering; **this command is not a complete 5.0 release**.


### RDAirPlay listener request controls (native build required)

The native RDAirPlay source in `rdairplay/rdairplay.cpp` adds a **Requests**
button in the bottom operator control strip. Its dialog displays each
listener's name, requested song and artist, cart and approval status; the
operator can approve, reject or insert an approved request into the currently
loaded **Main Log**. Insertion uses Rivendell's native
`RDLogPlay::insert()`, not a database-only status change. Each request is
atomically reserved, deduplicated and reconciled. Automatic fulfillment is
**opt-in**, only runs while RDAirPlay is in **AUTO** mode with an operator
authorized to add to the log, and requires today's committed, protected
24-hour plan ledger. Automatic request insertion remains off by default and
stops when RDAirPlay exits.

**This is native C++ source code, NOT a feature of the previously installed
RDAirPlay 4.5.0-1 executable.** It requires a new native package build and
verified in-place upgrade. No successful physical playback/queue execution
has been claimed; until qualified, treat this as development functionality.


The enhanced RDAirPlay desktop executable has a separate guarded installer
(`tools/install-airplay-requests.sh`) which only stages a verified,
already-compiled native binary as
`/usr/local/libexec/rivendell-complete/rdairplay-requests`. It does **not**
reinstall the core Rivendell Debian package or invoke its automatic
database modification, service stop or restart hooks. The Control Center
prefers this separate enhanced executable when it is present and root-owned,
and otherwise continues launching the original Rivendell RDAirPlay.
Do not invoke this staging installer until a newly compiled binary has
passed native build and runtime dependency checks.

### NAS discovery, categories and scheduling

In **Music & NAS**, entering a hostname/IP and SMB credentials enables
**Discover server shares** using Samba's `smbclient`, with optional
subfolder browsing. NFS discovers advertised exports using `showmount`.
SMB discovery credentials go through stdin into a protected short-lived
credential file; they never appear in process arguments. Selecting a share
populates the read-only mount mapping, and the selected subfolder is saved
locally (without storing the password in this mapping).

In **Import library**, select a mounted source, browse its folders, and
choose any actual Rivendell destination group (e.g. MUSIC, IDENTS, STINGS,
or a JINGLES group created in RDAdmin). The importer creates CART/CUT
metadata and immutable source-prefixed reference files; original NAS files
are not copied or rewritten.

In **Programming & scheduling**, enter a rotation of actual imported
music groups and choose an existing legal ID cart. The helper measures ID,
jingle, and optional fill-bed lengths from real Rivendell CART records and
checks the associated audio files. Preview builds a protected 24-hour
program plan; only **Create future Rivendell log** writes a new log and
the date's request-safety ledger. Complex traffic/spot grids and clock rules
remain in RDLogManager, which is linked from the scheduling page.

**Limitations:** A category group must already exist; a single jingle cart
can be inserted at the selected interval, but arbitrary jingle rotations
and detailed traffic clocks are not yet a complete in-GUI experience.
Unfillable 24-hour plans correctly fail rather than fabricating audio.
The request status `scheduled` means inserted in the log, **not proof
that the audio actually played**.

### Native Qt station control center

A native **Rivendell Complete** desktop application is installed by
`tools/finish-complete.sh`, with a root-owned helper for NAS operations.
It uses Ubuntu 26.04 `python3-pyqt5` and `pkexec`, and launches from
the Ubuntu desktop applications menu as `rdcomplete-control`.

The GUI provides read-only station readiness checks, NFS/SMB NAS mounting,
external-media configuration, music scanning/import confirmation, request
catalog export, local request queue moderation, source stream configuration,
stereo JACK routing and log timer controls. Source audio is never copied or
rewritten; start/enable actions require explicit confirmation. Privileged
scripts are installed root-owned, not executed from the user-writable checkout.

This is an integration pass, **not proof of on-air qualification**.
FLAC external playout, waveform editing for NAS originals, live backtiming,
a WAN-qualified listener request portal, emergency silence failover, and production
rollback are still incomplete.


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

### Developer build (not a station installation)

```bash
sudo apt-get update
sudo apt-get install -y git
git clone --branch dev \
  https://github.com/bradjtrammell/rivendell-complete.git
cd rivendell-complete
bash tools/deploy-test-system.sh --build-only
```

The build mode runs local regression checks and attempts native compilation. To install on a fresh test workstation, run `bash tools/deploy-test-system.sh --install`. Optional `--nfs` or `--smb` mounts original music read-only. `--streaming` installs (but never activates) an encoder; `--request-group` installs (but never activates) the loopback request service. **The resulting test installation must still be commissioned and air-qualified.** The Ubuntu 26.04 build path has encountered real dependency, C++ and Debian packaging failures. Changes have been committed for those failures, but complete packaging and hardware verification must pass before an installation is recommended.

For commissioning details, see the [station setup guide](docs/complete/STATION_SETUP.md). **Do not use the experimental `--install` mode for a station carrying live programming yet.**

## Architecture and project files

The upstream Rivendell applications — **RDAirPlay, RDLibrary, RDAdmin, RDLogEdit, RDLogManager and RDPanel** — are the foundation. Rivendell Complete integrates new components rather than requiring a second music library or a separate internet-radio automation product.

| Area | Implementation |
| :-- | :-- |
| NAS path resolution | `lib/rdconfig.*`, `cae/cae.cpp` |
| Library mounts / catalog | `tools/setup-nas.sh`, `tools/rdexternal.py`, `tools/rdcatalog.py` |
| Scheduling / traffic / logs | `tools/rdsmartclock.py`, `tools/rdstationplan.py`, `tools/rdloggen.py` |
| Requests / safe insertion | `tools/rdrequests.py`, `tools/rdlive.py`, `rdairplay/local_macros.cpp` |
| Imaging / metadata | `tools/rdsweepers.py`, `tools/pypad_glasscoder.py`, `tools/rdmetadata.py` |
| Encoder / audio routes | `tools/rdstream.py`, `tools/rdjackroute.py` |
| Ubuntu provisioning / diagnostics | `tools/install-ubuntu26.sh`, `tools/rdselftest.py`, `debian/` |
| Automated checks | `tests/`, `.github/workflows/rivendell-complete-ci.yml` |

## Release acceptance — what has to work together

No public release is considered station-ready until **all** of the following work in a clean installation:

1. Native Ubuntu 26.04 package build and installation, MariaDB initialization, application launch, and repeatable upgrade/rollback.
2. Direct original-path NAS playback and full supported-format coverage with no change to source music, including during editing and deletion.
3. Continuous unattended logs, music separation, IDs, commercials, intro sweepers, top-hour backtiming and live-assist takeover.
4. End-to-end listener request intake, safe insertion, real playback confirmation and correct broadcast logs.
5. Working local output and/or streaming encoder, actual SHOUTcast/Icecast connections, metadata and recovery.
6. Reboots, NAS loss, encoder crashes and network interruptions handled safely; a full 24-hour real-hardware air test without dead air.

[**View the authoritative feature-by-feature acceptance contract**](docs/complete/ACCEPTANCE.md)

## Documentation

- [Full requirements and verification status](docs/complete/ACCEPTANCE.md)
- [Ubuntu 26.04 station setup and qualification](docs/complete/STATION_SETUP.md)
- [Direct NAS media design and limits](docs/complete/EXTERNAL_MEDIA.md)
- [Listener request API and safeguards](docs/complete/REQUESTS.md)
- [Original upstream Rivendell documentation](README)
- [Upstream installation guidance](INSTALL)

## Origins and licensing

Rivendell Complete is based on the open-source [Rivendell Project](https://github.com/ElvishArtisan/rivendell), created by Fred Gleason and contributors. It is an independent fork, **not** an official Rivendell or Paravel Systems release. Upstream copyright notices and the applicable terms in [`LICENSES/`](LICENSES) are retained. Original project documentation is preserved in [`README`](README).

The project name **Complete** represents the committed product goal; it must not be used to conceal incomplete functionality or unverified deployment claims.
