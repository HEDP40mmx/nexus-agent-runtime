# Resume Nexus implementation

Start from branch `manus/nexus-v1-complete-20261023` at head `97974a9639bcc89cf3a00cc0ac9c94c30b8b247b`, based on main `aa6eead48329fc154aba803d41935a1ad75a623d`. Do not reset or merge main. The draft PR is https://github.com/HEDP40mmx/nexus-agent-runtime/pull/5.

Create a fresh external Python 3.12 environment, install `-e '.[test]'`, run `pip check`, `bash scripts/check_required_files.sh`, `python -m compileall -q nexus tests`, and `python -m pytest -q`. The current local result is 83 passing tests on Python 3.12.3 and SQLite 3.45.1.

The next implementation slice should replace in-process handler calls in `nexus/engine.py` with a supervised shell-free child protocol, add independent heartbeat and real lease-expiry reconciliation, then implement durable signal insertion and FIFO consumption. After that, add the authenticated loopback API, preflight, full CLI, installed wheel/sdist tests, and the remaining complete-product controls.

Use `/tmp/nexus-evidence` or another external directory for databases, reports, wheels, logs and test XML. Never commit virtual environments, SQLite files, WAL/SHM files, generated metadata, credentials, or build output. Before delivery, rebuild wheel and sdist in clean environments, run the offline demo outside the checkout, query hosted CI for the exact current head, create a source patch and incremental Git bundle, update `DELIVERY_REPORT.md`, and package the source plus evidence in one ZIP.
