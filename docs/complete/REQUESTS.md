# Listener requests

Run `bash tools/install-requests.sh POWER GOLD` with real music groups.
Export request-eligible music catalog to `~/.local/state/rivendell-complete/request-catalog.json`.
Public requests are moderated and available from the local station page
`http://127.0.0.1:8787/requests` when the unit is configured with
`--public-portal --moderated`. The page serves only sanitized MUSIC
catalog metadata; listeners never receive the private API bearer tokens.
Existing generated request unit files are upgraded idempotently during the
Control Center installation, with a 0600 recovery copy and without changing
the tokens or starting the request service. Custom service files are refused
rather than silently overwritten. The endpoint is still loopback-only. Do not publish it without TLS, trusted
proxy configuration and a sound per-listener rate-limiting design.
All listeners behind one local proxy share a rate-limit identity by default,
so this is **not yet a qualified WAN-facing website**.

Start the loopback service using `systemctl --user enable --now rdcomplete-requests.service`.
Clients POST JSON `{ "cart":123456, "requester":"Listener" }` to `/api/v1/requests`
with `Authorization: Bearer <listener token>` from the mode-0600 token file.
Administrator token is separate. Approval and rejection endpoints exist.
Use `rdstationplan.py --requests-db .../requests.sqlite` to include approved
requests in a new future log without displacing protected IDs or spots.

External use needs TLS reverse proxy, source restrictions, and authentication.
Never forward raw port 8787 to the Internet or embed the token in public HTML.
Automatic insertion into an already loaded *live* Rivendell log is not yet qualified.
## RDAirPlay operator panel (development)

A native **Requests** button and queue view have been added to the RDAirPlay
source. The panel shows a listener name, song, artist, cart, pending/approved
status, and operator **Approve / Reject / Add to Main Log** actions.
The Add action reserves the approved request and uses \`RDLogPlay::insert()\`
rather than claiming a request was scheduled merely because a backend row
changed.

Automatic fulfillment is explicitly opt-in. It requires:
- RDAirPlay AUTO mode, authorized add-to-log permissions and a loaded main log.
- An already approved request, an actual playable cart, and enough time
  before the next protected hard event.
- A committed future program log and a matching current-day
  \`~/.local/state/rivendell-complete/plans/YYYY-MM-DD.plan.json\` ledger.
- No ambiguous previously attempted queue delivery. Unknown outcomes
  require an operator to reconcile them manually.

Closing the dialog does not turn off an operator-enabled auto session;
restarting RDAirPlay resets the setting to OFF.

**Not yet live-qualified:** the patched RDAirPlay binary has not been built
and installed on the user's workstation. The native on-air queue action and
actual played-status feedback need hardware acceptance. "Scheduled" is not
the same as "Played."

**Manual queueing** (operator actively clicks **Add to Main Log**) may
insert an approved playable cart without a precomputed daily plan, after
explicit confirmation and native ADD permission validation. It rejects an
immediate hard-timed next event, and operators remain responsible for
checking upcoming IDs and paid breaks. **Automatic queueing** never receives
this manual override: it requires the committed protected date ledger AND
a matching loaded Production log.
