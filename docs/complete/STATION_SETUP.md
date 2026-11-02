# Rivendell Complete — Ubuntu 26.04 single-station commissioning

**Status:** Experimental development branch; not approved for live broadcasting.
This procedure starts from a **fresh Ubuntu 26.04 Desktop x86_64** system,
with **8 GB RAM**, **128 GB boot SSD**, and one station per PC.

This does **not** migrate or copy existing NAS audio. The original NAS
library is mounted read-only. Rivendell's own `/var/snd` workspace remains
local and separate. Do not use a source directory containing original music
as `/var/snd`.

## 1. Native application build

As the normal desktop login user:

```bash
sudo apt-get update
sudo apt-get install -y git
git clone --branch dev \
  https://github.com/bradjtrammell/rivendell-complete.git
cd rivendell-complete
bash tools/install-ubuntu26.sh --build-only
```

The command compiles native packages. Review its output and ensure Ubuntu 26
CI completed successfully before proceeding. The full fresh installation path
is:

```bash
bash tools/install-ubuntu26.sh --install
```

The second command **builds again** and installs a local database and
Rivendell 4.5.0. It refuses an existing Rivendell installation and preserves
all pre-existing /var/snd data. It is not a migration tool.

After install, log out and back in for `rivendell` group membership, and
use RDAdmin to configure station identity, audio hardware, one service,
and music categories. None of these actions modifies existing NAS files.

## 2. Read-only NAS mount

Use the **actual** server/share location (not the examples below).
Only one protocol is necessary.

```bash
# NFS form:
sudo bash tools/setup-nas.sh --nfs 'SERVER:/export/path'
# OR SMB form (credentials prompted, protected on local SSD):
sudo bash tools/setup-nas.sh --smb '//SERVER/share'
```

The mount location is `/mnt/radio-music` by default. The script rejects
nonempty target directories, existing mount configurations and writable
media mount options. Verify the actual files appear after mounting:

```bash
findmnt -T /mnt/radio-music
find /mnt/radio-music -type f | head
```

## 3. External audio references

Create an **SSD-local reference directory** and add this section to
`/etc/rd.conf` as administrator:

```ini
[ExternalAudio]
Root=/mnt/radio-music
References=/var/lib/rivendell/external-media
```

```bash
sudo install -d -o root -g rivendell -m 0750 \
  /var/lib/rivendell/external-media
sudo systemctl restart rivendell
```

Create actual music groups in RDAdmin first (for example `POWER`,
`GOLD`). Run a dry run on a small number of files before committing:

```bash
python3 tools/rdexternal.py --root /mnt/radio-music \
  --group POWER --limit 10
```

Only when the group and source mapping have been checked:

```bash
sudo python3 tools/rdexternal.py --root /mnt/radio-music \
  --group POWER --limit 10 --commit
```

This creates Rivendell database CART/CUT rows and local `.ref` references.
It never edits or copies the NAS files. The importer **fails** if the source
is not mounted read-only. The current supported source types are MP3,
PCM WAV 16/24-bit and Ogg Vorbis; FLAC direct playout is pending.

## 4. Offline intelligent timing experiment

Export active, playable carts from the database (using your actual music
group names):

```bash
sudo python3 tools/rdcatalog.py --group POWER --group GOLD > music-catalog.json
```

Create a station timing configuration with your actual top-hour ID cart
number (that ID must already exist in the Rivendell catalog):

```json
{
  "service": "MUSIC",
  "rotation": ["POWER", "GOLD", "POWER"],
  "top_hour_cart": 900001,
  "artist_separation_minutes": 120,
  "album_separation_minutes": 60,
  "title_separation_minutes": 1440,
  "max_hour_gap_ms": 10000,
  "safety_margin_ms": 3000
}
```

The value `900001` above is a **configuration example**, not a cart created
by the installer. Replace it with a real ID. The example `MUSIC` service
and `GOLD` group must also exist.

To examine the generated day's log without modifying Rivendell:

```bash
python3 tools/rdsmartclock.py \
  --config station.json --catalog music-catalog.json \
  --date "$(date -d tomorrow +%Y-%m-%d)" \
  --id-duration-ms 10000 --log-name MUSIC_NEXT_DAY \
  > planned-log-commands.txt
```

Replace `10000` with the **measured ID length in milliseconds** and give
the log a unique valid name for each day. The planner refuses an hour when
it cannot satisfy category/separation/timing constraints. It is an *offline*
backtiming planner, not a continuous live queue adjustment. Execute with
`--commit` only after reviewing its output and when no log with that name
exists.

Alternatively, RDLogManager's normal clocks and grids can be used with
`tools/install-loggen.sh SERVICE` to protect and generate seven future
days twice daily. Do not run both log-generation approaches for the same
broadcast service without deliberately designing the interaction.

## 5. Streaming on this same PC

Install the separate monitored GlassCoder encoder as the studio desktop user:

```bash
bash tools/install-streaming.sh
```

Configure using the actual server address, source credentials, and protocol
(Shout1/Shout2/IceCast2), then verify before enabling the systemd service.
Passwords are prompted and stored at mode 0600, never placed in process
arguments. JACK/ALSA source routing and server handshakes are *not*
automatically established by this stage and must be tested with real hardware.

## Broadcast qualification still required

- Pass native Ubuntu 26.04 build and install; launch RDAdmin, RDLibrary,
  RDLogManager, and RDAirPlay.
- Verify audio out through your actual ALSA/JACK interface and stream encoder.
- Test NAS loss/recovery, read-only file protection, exact cue/segue markers,
  per-hour legal IDs, and musical separation for at least 24 hours.
- Implement and verify automatic listener requests, dynamic in-play
  backtiming, protected traffic/commercial event handling, sweeper overlays,
  metadata forwarding, and automatic failover.

No production claim is made for any of the remaining items.
