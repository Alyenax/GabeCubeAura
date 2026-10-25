# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""JSAUX broker wire 1.0 / revision 4: bounded extended coordinated start."""
PROTOCOL = "jsaux-broker"
VERSION = "1.0"
CONTRACT_REVISION = 4
CONTRACT_SHA256 = "480b8abaa9ee5669106f55fae46bb9acf0213abf4d28eb05568c499eccc4c11f"
PROFILE = "gca-collection-rgb332-opaque-v1"
LIMITS = dict(message_bytes=65536, chunk_bytes=24576, max_content_bytes=196608,
              canvas_width=64, canvas_height=54, max_frames=6000,
              max_loop_duration_cs=2400000, min_frame_delay_cs=1,
              max_frame_delay_cs=65535, max_contents=4,
              max_cached_content_bytes=786432, max_uploads=1,
              max_staging_bytes=196608, max_total_content_staging_bytes=1048576,
              min_free_disk_bytes=67108864, validator_memory_bytes=67108864,
              validator_cpu_ms=5000, validator_wall_ms=10000, upload_idle_ms=60000,
              max_connections=2, max_resident_clients=4, client_gc_idle_ms=10000,
              max_requests_per_second=20, request_burst=40, rpc_deadline_ms=2000,
              idle_read_ms=5000, renew_interval_ms=2000, lease_ms=8000,
              steam_freshness_ms=5000, sync_wait_ms=15000,
              max_clock_uncertainty_ms=50, clock_sample_max_age_ms=30000,
              screensaver_min_attempt_interval_ms=5000)
OPERATIONS = ("hello", "status", "register_content", "content_chunk", "commit_content",
              "abort_content", "acquire_display", "player_ready", "renew_display",
              "operation_status", "tv_started", "release_display", "goodbye")
CAPABILITIES = dict(operations=list(OPERATIONS), content_profiles=[PROFILE],
                    modes=["sync", "async"], serial_owner="GabeCubeAura",
                    tv_only_independent=True, hardware_fallback=False,
                    software_coordinated_start=True, physical_alignment_measured=False,
                    content_registration_without_usb=True)
