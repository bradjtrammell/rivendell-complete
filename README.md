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
