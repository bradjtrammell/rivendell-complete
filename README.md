# Rivendell Complete

**Complete radio automation for internet radio stations and terrestrial broadcast stations.**

Rivendell Complete is a fork of **Rivendell 4** designed to run an entire station from one integrated Linux automation system: **music and programming, live-assist playout, intelligent scheduling, station IDs, commercials, imaging, built-in listener requests, built-in streaming encoders, and native support for existing NAS music libraries.** An internet-only station must be able to operate without any terrestrial transmitter equipment; an FM or other broadcast station must be able to drive its local/studio output **and** any internet stream at the same time.

> **DEVELOPMENT STATUS — NOT A FINISHED OR PRODUCTION-QUALIFIED STATION.** The description above is the *target product*, not a claim that every feature is implemented or has passed end-to-end verification. [Read the complete, binding acceptance contract](docs/complete/ACCEPTANCE.md) for every requirement, status, and test gate.

## Who it is for

- **Internet radio stations:** complete scheduling, music playback, jingles, live assist, web listener requests, now-playing metadata, and built-in SHOUTcast/Icecast encoding, all on the station's Linux PC. No FM equipment is required.
- **Terrestrial radio stations:** everything above, plus reliable local audio for a studio/transmitter link or on-site air chain, timed station IDs and commercial breaks, operator control, and optional simultaneous online simulcasting.
- **Stations with NAS music libraries:** directly index and play the **original songs where they already are** on NFS/SMB storage. No forced import to Rivendell-owned carts, no parallel copy of the library, no moving or renaming source files.
- **Small, independent and unattended operators:** straightforward station setup, continuous clocks, scheduled content and requests, service recovery and visibility into station health. Professional broadcast controls remain available when an operator takes over.

**This is one product, not a pile of independent utilities, and it is not Rivolution or RadioCentral.** The objective is to preserve Rivendell's proven automation architecture while delivering an integrated, RadioDJ-comparable end-to-end station workflow on Linux.

## What “Complete” means — required product scope

| Area | Required integrated behavior | Current reality |
| --- | --- | --- |
| Ubuntu/Linux | Original Rivendell 4 native on Ubuntu **26.04 LTS**, with real packages and a reliable installer | **Partial** — source port, installer and packaging work in progress |
| Existing NAS music | Read original, unchanged files directly over read-only **NFS or SMB**, with zero library duplication | **Partial** — path resolver/indexer exist; full live playback and destructive-operation safety not qualified |
| Music formats and catalog | MP3, supported PCM WAV, Ogg Vorbis, **FLAC** and actual library formats; batch indexing; metadata, cue/intro/segue editing | **Partial** — several decoder/catalog paths exist; FLAC and full editing missing |
| Automation | Continuous station clocks, rotation by category, song/artist/album separation, automatic future logs and operator override | **Partial** — offline planners and scheduled log-generation utilities |
| Precise events | Real-time intelligent top-of-hour backtiming, hard legal/station IDs, spots/paid breaks, no dead air | **Partial** — offline protected events; live self-adjusting playout not qualified |
| Imaging | Jingles, liners, sweepers **over instrumental intros** without obscuring vocals, production controls | **Partial** — introductory PyPAD/SoundPanel integration, not on-air verified |
| Listener requests | **Built-in**, safe request intake, eligibility/rate limits, queue, approval, automated insertion, playback confirmation | **Partial** — API, queue and guarded insertions exist; end-to-end playback confirmation missing |
| Stream encoding | **Built-in** same-computer SHOUTcast v1/v2 and Icecast streams, metadata, reconnect independent of other outputs | **Partial** — supervised GlassCoder integration, real streams unverified |
| Local/studio output | Local audio, live assist, cartwall, segue/crossfade and optional studio-to-transmitter chain | **Partial** — Rivendell controls remain; full audio chain unqualified |
| All-in-one setup | Install/configure station, database, NAS, audio, clock, traffic, requests, encoding and recovery with minimal intervention | **Incomplete** — multiple manual configuration steps remain |
| Recovery | Auto-start after reboot, recover NAS/link/stream issues, monitored silence and emergency playout, preserve logs | **Incomplete** — some monitoring/reconnect mechanisms, no verified on-air failover |
| Production verification | Native package installation, full-day continuous playout, 8 GB/128 GB target hardware, real NAS/stream/hardware tests | **Not completed** |

**“Partial” means implemented source is *not* proof that a station works.** No feature may be marked complete until its operator-facing workflow and failure modes pass tests. Current authoritative state: [Acceptance contract and requirements ledger](docs/complete/ACCEPTANCE.md).

## Original-path, zero-copy NAS playback

This is a defining project rule, not an optional enhancement.

\`\`\`text
Existing NAS music directory (UNCHANGED)
        |
        +--- read-only NFS or SMB mount
                 |
        external file references + metadata database on local SSD
                 |
        Rivendell Complete playback / automation / imaging
                      |
               output / mixer
                /          \
  local radio/studio audio   built-in SHOUTcast/Icecast encoding
     (broadcast stations)       (internet and simulcast stations)
\`\`\`

The originals must **not** be moved, renamed, converted, copied into a second Rivendell library, or written/deleted by cart-management operations. The computer may maintain a separate **small local managed cart/workspace** and **purpose-built emergency programming**; that is not permission to duplicate the original music library. The mounted source must be read-only, and errors or broken NAS references must not corrupt database durations or source content.

## First deployment: Ubuntu 26.04 single-station workstation

The **first qualification target** is a fresh **Ubuntu 26.04 Desktop, x86_64**, with **8 GB RAM**, **128 GB boot SSD**, **one station per PC**, and music on the existing NAS at its original paths. This is a required supported deployment profile **not** a limitation to FM-only, internet-only, or this particular operator. Independent internet stations can run with no local transmitter output.

The project was requested as an urgent deployment because Windows automation workstations can hang and take stations off-air. The initial goal was to deploy a *fully functioning* station in under four hours. **That time is not yet demonstrated**; do not present a successful build as a complete on-air installation.

### Development checkout — inspect/build only

\`\`\`bash
sudo apt-get update
sudo apt-get install -y git
git clone --branch feat/ubuntu26-external-nas-media \
  https://github.com/bradjtrammell/rivendell-complete.git
cd rivendell-complete
bash tools/install-ubuntu26.sh --build-only
\`\`\`

**Important:** \`--build-only\` tests a source/package-build path; it does **not** install or configure an operational station. The native Debian packaging error reported on the actual Ubuntu 26 workstation is being fixed on this branch. **Do not run \`--install\` on a production station until package build and fresh-install qualification pass.** The workbench and original NAS must remain separate.

Read [Station commissioning](docs/complete/STATION_SETUP.md) and [NAS integration](docs/complete/EXTERNAL_MEDIA.md) before configuring mounts or external cuts.

## What currently exists in code

| Component | Source |
| --- | --- |
| Original-path external cut resolver and guarded CAE playback | \`lib/rdconfig.{h,cpp}\`, \`cae/cae.cpp\` |
| NFS/SMB read-only setup; external music indexing and catalog export | \`tools/setup-nas.sh\`, \`tools/rdexternal.py\`, \`tools/rdcatalog.py\` |
| Rotation/artist/album/title separation; hard IDs, spot breaks and timed offline logs | \`tools/rdsmartclock.py\`, \`tools/rdstationplan.py\`, \`tools/rdloggen.py\` |
| Authenticated listener requests, persistent queue and guarded live \`PX\` insertion | \`tools/rdrequests.py\`, \`tools/rdlive.py\`, \`rdairplay/local_macros.cpp\` |
| Imaging, local stream metadata and same-PC encoders | \`tools/rdsweepers.py\`, \`tools/pypad_glasscoder.py\`, \`tools/rdstream.py\`, \`tools/rdmetadata.py\` |
| Audio routing and recovery foundations | \`tools/rdjackroute.py\`, \`tools/rdselftest.py\`, systemd service files |
| Native Ubuntu 26 port and experimental packaging | \`configure.ac\`, \`debian/\`, \`rdairplay/messagewidget.*\`, \`tools/install-ubuntu26.sh\` |
| Regression checks and CI | \`tests/\`, \`.github/workflows/rivendell-complete-ci.yml\` |

**These are committed components, not yet a verified integrated station.** In particular, direct FLAC playout, continuous live backtiming, guaranteed hard-event playback, comprehensive failure recovery, turnkey administration, and full real-world acceptance remain outstanding.

## Definition of done

Rivendell Complete is **not ready** simply because it compiles, has a GitHub Actions green check, accepts a request, produces a plan, or connects to a stream encoder. It is ready **only after** the complete installation, original NAS playout, live scheduling, imaging, listener requests, paid/ID events, internet encoding, relevant broadcast outputs and recovery are demonstrated **together**, including reboot and outage tests, on actual Ubuntu 26.04 hardware.

The binding [acceptance contract](docs/complete/ACCEPTANCE.md) enumerates **every requested feature** and the exact qualification evidence required. Changes must update the contract/README and add tests when the implementation changes. No scope may be silently dropped; no unverified behavior may be marked complete.

## Upstream, licenses and contributors

Rivendell Complete is a community fork of the [Rivendell Project](https://github.com/ElvishArtisan/rivendell), originally developed by Fred Gleason and contributors. This project preserves applicable upstream notices and the licenses in [LICENSES](LICENSES). The original upstream command-line/application documentation remains applicable where unchanged; see [README](README), [INSTALL](INSTALL), and [UPGRADING](UPGRADING). The fork is independently adapted for the integrated goals above and should not be mistaken for an official Rivendell/Paravel Systems release.
