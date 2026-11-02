# Rivendell Complete — Authoritative Product & Acceptance Contract

**Audience:** internet radio stations and terrestrial radio broadcast stations requiring a *complete* integrated Linux automation platform with built-in listener requests, stream encoding, and original-path NAS audio support. This is not restricted to FM operation. A station may be internet-only, broadcast-only, or simulcast.

**First qualification hardware:** Ubuntu 26.04 Desktop x86_64; one station per PC; 8 GiB RAM, 128 GB boot SSD; the existing music remains in its original NAS share/directory, read-only, with **zero library copy or move**. One machine handles complete automated playout, scheduling, encoders and local/studio broadcast output where required.

**Contract policy:** Every requirement below remains an obligation until it is independently verified. Code committed, source compiled, and package built are distinct evidence levels. A stage that passed a unit test is **not** production-ready. New requests, options, or corrections must be added here and reflected in the project README in the same branch. Preserve the upstream `v4` baseline; keep unqualified work in draft PRs.

Legend: **PARTIAL** = component/code exists but feature not end-to-end qualified; **MISSING** = not delivered; **UNVERIFIED** = behavior not demonstrated; **BLOCKED** = unresolved build/install defect. No item is fully qualified at this time.

## Station architecture, audience and installation

| ID | Requirement and mandatory acceptance behavior | Current status |
| --- | --- | --- |
| ST-01 | Full-purpose station product for **internet-only** stations, with no transmitter or FM hardware required. Includes playout, music clock, imaging, encoded stream and requests in the same system. | PARTIAL; full workflow unqualified |
| ST-02 | Full-purpose station product for **broadcast** stations, with independent local/studio audio and optional simultaneous internet stream. | PARTIAL; physical output unqualified |
| ST-03 | Single integrated Rivendell 4-based product; **not** a replacement fork such as Rivolution, and not RadioCentral. | PARTIAL; Rivendell 4 fork exists |
| ST-04 | First supported deployment: Ubuntu 26.04 Desktop x86_64, 8 GiB RAM, 128 GB boot SSD, **one station per PC**. Avoid unnecessary local music storage. | UNVERIFIED on hardware |
| ST-05 | Native Ubuntu 26.04 packages/dependencies, no Ubuntu 24.04 package mixing; Qt WebEngine and ImageMagick 7 compatibility. | PARTIAL; source port and dependency fix, package/install pending |
| ST-06 | Reliable single-command installation encompassing dependencies, database, services, station identity, audio, NAS, encoder, clocks, requests and recovery. No endless manual RDAdmin work. | MISSING; guarded experimental installer only |
| ST-07 | Install, upgrade, rollback and remove safely; preserve existing data, original source audio, config and previous station state. | MISSING; preflight guards only |
| ST-08 | Expose station configuration in a cohesive operator-friendly workflow; inputs validated with useful errors and progress. | MISSING |
| ST-09 | Fast deployment from fresh Ubuntu 26.04, urgent **under-four-hour operational target**, with measured result—not an invented ETA. | UNVERIFIED |
| ST-10 | Preserve professional Rivendell RDAirPlay, RDLibrary, RDLogManager, RDLogEdit, cartwall and other existing workflows unless deliberately enhanced. | PARTIAL; upstream GUI retained, integration unqualified |

## NAS library and metadata

| ID | Requirement and mandatory acceptance behavior | Current status |
| --- | --- | --- |
| NAS-01 | Music remains **exactly** where it is on the NAS: no moving, renaming, copying, re-encoding, deleting, reorganizing, or importing into a second managed music library. | PARTIAL; read-only resolver/indexer code |
| NAS-02 | Native configurable NFS/SMB mounts with read-only access, stable reconnect and safe mount behavior. | PARTIAL; mounting script and guard code |
| NAS-03 | Zero-copy indexing of thousands of original files; metadata retained, categorized and searchable. | PARTIAL; metadata indexer/catalog exporter |
| NAS-04 | Direct path playout through Rivendell/CAE, not symlinks pretending to be Rivendell cart storage; safe canonical paths. | PARTIAL; resolver; hardware play untested |
| NAS-05 | MP3, WAV, Ogg/Vorbis and FLAC as present in the existing music library, with reliable channel, bitrate, length and VBR support. | PARTIAL; FLAC/format coverage missing |
| NAS-06 | Normal library UI can search, edit catalog metadata, markers, cues, segues and intros **without changing audio originals**. | MISSING full RDLibrary integration |
| NAS-07 | Cart deletion/recording, edits/import/export, cleanup and maintenance never mutate source files; symlink traversal blocked. | UNVERIFIED for every code path |
| NAS-08 | Missing/corrupt audio, NAS latency/loss/reconnection, stale path and duplicate reference are identified and recovered without library damage or dead air. | MISSING complete resilience |
| NAS-09 | Local SSD holds DB, config, logs, indexes and bounded working storage; a small separate *emergency program* may exist but not a duplicate library. | PARTIAL |
| NAS-10 | Original NAS is shareable simultaneously with existing music systems; no ownership/exclusive-access assumptions. | UNVERIFIED |

## Automation and programming

| ID | Requirement and mandatory acceptance behavior | Current status |
| --- | --- | --- |
| AUTO-01 | 24/7 unattended and live-assist playout, loading daily logs without manual operator intervention. | PARTIAL |
| AUTO-02 | Automatic clock-driven music rotation by category, with artist/album/title/song/cart separation and configurable repeat windows. | PARTIAL; offline planner |
| AUTO-03 | Continuously maintain logs with predictable, configurable events and priority; operator can edit/override. | PARTIAL; timer and offline planner |
| AUTO-04 | **Intelligent dynamic live backtiming**: automatically choose suitable shorter songs near top of hour to hit fixed IDs without silence or arbitrarily cutting active music. | MISSING live reflow |
| AUTO-05 | Hard top-of-hour legal/station IDs scheduled and **actually fired** at intended wall clock times; never displaced by requests. | PARTIAL; offline hard IDs and conservative insertion guard |
| AUTO-06 | Commercials, paid traffic, break grouping, booked spot verification and protected timed breaks. | PARTIAL; planned breaks, no on-air verification |
| AUTO-07 | Station liners, jingles, imaging and sweepers in automatic programming. | PARTIAL |
| AUTO-08 | Sweeper voice-over instrumentals/intro with marker-aware timing, preserving vocal onset and mixing correctly into output. | PARTIAL; PyPAD SoundPanel bridge, on-air unverified |
| AUTO-09 | Professional cueing, segues/crossfades, level consistency, manual/automatic mode changes and live assist. | PARTIAL; Rivendell controls, external playout integration unverified |
| AUTO-10 | Real-time now/next/playing metadata, logs and play history for reports, requests and streaming. | PARTIAL; PyPAD metadata integration |
| AUTO-11 | Reliable emergency/silence fallback, never dead air from missing NAS, bad logs or stream interruptions. | MISSING |

## Built-in listener requests

| ID | Requirement and mandatory acceptance behavior | Current status |
| --- | --- | --- |
| REQ-01 | Station-integrated listener request experience; internet listeners can submit requests safely. | PARTIAL; loopback API only |
| REQ-02 | Allow eligible categories, request rules, rate limits, moderation, explicit approval/rejection and abuse controls. | PARTIAL; queue/auth/rate controls |
| REQ-03 | Auto-insert eligible requests without colliding with legal IDs, commercials, protected events or artist/title separation. | PARTIAL; offline planner and guarded live PX |
| REQ-04 | Live request insertion has true acknowledgment/error handling and no duplicate dispatch after uncertain acknowledgment. | PARTIAL; RML ACK code, hardware unqualified |
| REQ-05 | Confirm the song was **audibly played**, not just inserted, and mark requests complete only then; reconcile restarts. | MISSING |
| REQ-06 | Integrated station setup/admin UI and suitable public request front end; secure exposure through approved TLS/reverse proxy. | MISSING full integration |
| REQ-07 | Requests cannot halt airplay or overload a station or expose control/stream credentials. | PARTIAL, not load tested |

## Built-in streaming and routing

| ID | Requirement and mandatory acceptance behavior | Current status |
| --- | --- | --- |
| STR-01 | Encode on **the same station PC** to SHOUTcast v1/v2 and Icecast, with configurable stream bitrate/format and destinations. | PARTIAL; GlassCoder wrapper |
| STR-02 | Internet-only station runs full automation + encoder without requiring FM/local transmitter hardware. | UNVERIFIED |
| STR-03 | Terrestrial/simulcast station can send FM/studio and online audio simultaneously. | UNVERIFIED |
| STR-04 | JACK/ALSA routing configured within product; stable ports/connectivity and reconnection after restart. | PARTIAL; route utility, manual setup |
| STR-05 | Correct current artist/title and now-playing information transmitted to streams without embedding credentials in parameters. | PARTIAL; PyPAD-to-FIFO |
| STR-06 | Encode/reconnect after short link interruptions; stream reconnection independent of local playout. | PARTIAL; systemd restart, no real endurance tests |
| STR-07 | Multiple output/bitrate configurations as station requires, monitored state and operator diagnostics. | MISSING integrated multistream workflow |
| STR-08 | Avoid station disruption on encoder crash, NAS failure or transient studio/transmitter path loss. | UNVERIFIED |

## Recovery, security and verification

| ID | Requirement and mandatory acceptance behavior | Current status |
| --- | --- | --- |
| OPS-01 | Resume station services, protected logs, audio routes and encoding safely after cold boot or process crash. | PARTIAL |
| OPS-02 | Detect and recover NAS interruption and hanging services; emergency audio is independent of NAS; alert on dead air. | MISSING |
| OPS-03 | Limit admin, request and remote surfaces with authentication, least privilege, validated configuration and private secrets. | PARTIAL |
| OPS-04 | Honor read-only source policy, refuse unsafe mounts, preserve log/DB audit trail and never silently discard config/data. | PARTIAL |
| OPS-05 | Verify Linux build, all Debian packages and postinst DB schema creation, GUI launch, and sound card playout. | BLOCKED / UNVERIFIED |
| OPS-06 | Full realistic 24-hour on-air schedule: hard IDs, commercial breaks, category rotation, requests, jingles, sweepers, live assist and metadata; observe with actual audio. | NOT PERFORMED |
| OPS-07 | Inject network outages, NAS failure, stream loss and system reboots; test no stuck audio/dead air and source unchanged. | NOT PERFORMED |
| OPS-08 | Reproducible release, commit-linked assets and hashes, build and hardware/rollback qualification evidence. | INCOMPLETE |
| OPS-09 | Every requested feature must be committed, tested and documented before declaring fully completed. No placeholders, dummy buttons or undocumented deferrals. | MANDATORY |
| OPS-10 | Preserve existing Rivendell attribution/licensing, the project's defined purpose and established GUI rather than gratuitous redesign. | MANDATORY |

## Evidence hierarchy and release gate

Evidence must be reported distinctly: **inspected → syntax/static checks → unit tests → native compilation → Debian packages → fresh install / schema creation → GUI/planning → actual NAS playout / JACK routing → actual streaming/request and imaging operation → power/network failure simulations → full-day unattended on-air qualification → deployment/rollback**. A green unit-test job cannot be used to claim later stages.

### Actual workstation incidents (must be regression-tested)

1. Fresh Ubuntu 26.04 installer originally stopped at **`libid3-dev`**. Correction: native **`libid3-3.8.3-dev`**, changed in installer and CI. Preflight lists **all** missing packages rather than failing at one. **No incompatible Ubuntu repositories**.
2. Native build originally failed in the request-driven RDAirPlay C++ `PX` switch case. Scoping corrected; must rerun in native CI.
3. After installing dependencies, the real workstation reached `dpkg-buildpackage --build=binary --no-sign` and failed at **`debian/rules:15`** because `librivwebcapi.so.*` had never been built. The `debian/rules.src` `binary` target now depends on `build`; *do not treat this as fixed until Debian package CI and the actual machine pass*.
4. Avoid telling operators to rerun installation repeatedly on guesses. An updated build command is justified only when the exact failing revision has successful independent verification at the corresponding gate.
5. Native Ubuntu 26.04 Debian package build failed on November 2 with `cannot parse ../../helpers/docbook/template/titlepage.xsl`. Packaging did not export `DOCBOOK_STYLESHEETS`, so `helpers/docbook` was never created by configure. Debian packaging rules now export the distro stylesheet location and fail early if it is absent. **CI package build and fresh-host installation must still be rerun; this change alone does not qualify deployment.**

6. Native 4.5.0-1 packages and both desktop executables were observed installed
   on the user's November 2 workstation, with an existing MariaDB schema.
   This does **not** verify all GUI applications or any on-air feature.
7. Stream staging encountered an unrelated APT frontend lock held by PID 6507
   across multiple attempts. Preserve the lock and live package transaction;
   do not terminate it or declare its owner stale without process diagnostics.
   The post-install component command now stages independent tools and desktop
   shortcuts before checking APT contention.

8. Ubuntu 26.04 ships `jack_lsp`, `jack_connect` and `jack_disconnect`
   in the `jack-example-tools` package. A real workstation installed
   GlassCoder, jack-tools and jackd2 successfully but the operator's subsequent
   `command -v jack_lsp` failed. Because the installer intentionally uses
   `--no-install-recommends`, `jack-example-tools` must be an explicit
   dependency with an executable preflight. Actual audio routing remains
   unqualified until tested on the workstation.

## Implementation references

- [Ubuntu 26.04 commissioning](STATION_SETUP.md)
- [External NAS playback](EXTERNAL_MEDIA.md)
- [Request API and safety](REQUESTS.md)
- [Source-level regressions and packaging CI](../../.github/workflows/rivendell-complete-ci.yml)
- [Current development PR](https://github.com/bradjtrammell/rivendell-complete/pull/1)

**Change-control requirement:** Add new features, defaults, options, corrections and acceptance tests to this file **and** update the README product summary with each relevant branch change. Do not leave the README describing an older or narrower project. Do not mark requested functionality finished without evidence.
