# Listener requests

Run `bash tools/install-requests.sh POWER GOLD` with real music groups.
Export request-eligible music catalog to `~/.local/state/rivendell-complete/request-catalog.json`.
Start the loopback service using `systemctl --user enable --now rdcomplete-requests.service`.
Clients POST JSON `{ "cart":123456, "requester":"Listener" }` to `/api/v1/requests`
with `Authorization: Bearer <listener token>` from the mode-0600 token file.
Administrator token is separate. Approval and rejection endpoints exist.
Use `rdstationplan.py --requests-db .../requests.sqlite` to include approved
requests in a new future log without displacing protected IDs or spots.

External use needs TLS reverse proxy, source restrictions, and authentication.
Never forward raw port 8787 to the Internet or embed the token in public HTML.
Automatic insertion into an already loaded *live* Rivendell log is not yet qualified.