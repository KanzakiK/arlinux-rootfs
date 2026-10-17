# GitHub installer downloads

OpenCode's right-edge hold entry and its desktop icon both call
`arlinux-opencode`, which uses `runtime/tools/shared.py`. The same downloader
serves Windows installers and Bionic Wine. Keep routing policy here rather than
adding a separate proxy in an app installer.

The host writes `/etc/arlinux-steam-language` for every prepared instance, even
when Steam is not installed. Only `zh` enables SteamCommunity302 GitHub routes;
other languages retain direct requests. Routes preserve the original HTTPS host,
SNI and certificate checks. Final artifacts must match their manifest SHA-256.

Release metadata queries also use these routes: direct and four accelerated
requests run concurrently with a 5-second curl limit and a 6-second process
limit. A response must identify the requested asset and match its digest when
GitHub supplies one. A failed lookup falls back to the original release URL.

Asset routes are compared with parallel full-response transfers bounded to four
seconds (five-second process timeout). Range responses can use different CDN
caches and overstate the speed of the actual installer; small bursts also favor
a quick handshake over sustained throughput. The original release URL is probed only after the selected API
asset routes fail, avoiding an unused second round of startup probes. Direct
access remains a candidate because acceleration availability varies by network.

When a probe exceeds 64 KiB/s, its download connection must sustain at least a
quarter of that rate (capped at 256 KiB/s) over 15 seconds. Otherwise curl stops
and the downloader resumes on a new connection, then the next route. Disable
curl's internal retries for these adaptive attempts so they cannot multiply the
low-speed wait; the downloader owns the retry. An unrestricted direct attempt
remains last in case every probe was optimistic. Final SHA-256 verification still
applies to the resumed file.

Run `python3 tests/test-github-routes.py` and `python3 tests/test-download-cdn.py`
for language gating, metadata validation, lazy fallback, route ranking, checksum
validation and interrupted-download coverage. Real speed measurements must use
the target device's network; a workstation and phone can select different routes.

## Device acceptance, 2026-10-17

Xiaomi 15 (`3fad759`, `io.taowen.arlinux.dev`), fresh imported instance
`yibu-3376434d`, started from the right-edge hold gesture. The instance contained
no previous OpenCode installation or installer cache. Device `shared.py` matched
the tested source SHA-256
`8983964a3811dd2c3095f52c4a464e979be1c22fdd2b80f1f668e6a3bb92355d`.

OpenCode Desktop 1.18.31 downloaded 116,386,736 bytes. Independent on-device
hashing matched manifest SHA-256
`4433503efeb792c4a807979cbebe9dd300f32df941c85d203644c706201745df`.
Dependency installation and extraction finished automatically; the OpenCode
New session screen and prompt rendered successfully. Local text entry was
verified and cleared without submitting a model request. Low-speed reconnects and
cross-route resumes were observed without restarting the file at zero.

The cache-lock creation to final payload modification interval was 668 seconds,
including metadata and route selection: approximately 170 KiB/s overall.
Short probes reached several MiB/s, but sustained throughput was much lower.
This validates routing, resume, integrity, installation and launch; it does not
establish a comparable sustained speedup. The remaining network variability
needs separate performance work rather than reporting probe peaks as results.
All 20 GitHub routing, CDN recovery and Wine latest-cache regression checks passed.
