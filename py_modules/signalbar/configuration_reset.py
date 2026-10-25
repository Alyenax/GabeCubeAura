"""Explicit local factory reset. The legacy reset RPC stays settings-only."""
from pathlib import Path
import shutil
import time

FACTORY_RESET_CONFIRMATION = 'delete-gca-settings-content-and-access'


def factory_reset(plugin, confirmation):
    if confirmation != FACTORY_RESET_CONFIRMATION:
        raise ValueError('Confirm the complete reset before deleting GCA data')
    manager, engine, jobs = plugin.update_manager, plugin.engine, plugin.faceplate_artwork_jobs
    # An installer must never lose its settings or authorization mid-transaction.
    if not manager._operation_lock.acquire(blocking=False):
        raise ValueError('Wait for the current update operation before resetting GCA')
    try:
        if manager.status().get('phase') in {
                'downloading', 'verifying', 'preparing_install', 'installing', 'restart_pending'}:
            raise ValueError('Finish or cancel the current update before resetting GCA')
        library = engine.faceplate.steamgriddb
        cache = Path(engine._faceplate_scene_cache)
        if library.root.is_symlink() or cache.is_symlink():
            raise ValueError('Cannot reset linked GCA data directories')
        with jobs.lock, engine._settings_apply_lock:
            jobs.cancel()
            engine.reset_settings_only()
            # Reset parks the matrix worker while its new setup is pending.
            # Wait for its current reader before deleting prepared background packs.
            deadline = time.monotonic() + 5
            with engine.faceplate_worker.condition:
                while engine.faceplate_worker.busy:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ValueError('Display cleanup is still running; retry the complete reset')
                    engine.faceplate_worker.condition.wait(remaining)
            library.reset_user_data()
            jobs.progress_path = None
            jobs.job_id = ''
            engine.ambience.reset()
            engine.artwork.reset_cache()
            engine.launch_palette.reset_cache()
            engine.launch_artwork.clear_palettes()
            engine._artwork_identity = None
            if cache.is_dir():
                shutil.rmtree(cache)
            manager.disconnect_private_authorization()
            draft = getattr(plugin, 'onboarding_draft', None)
            if draft is not None:
                draft.discard()
    finally:
        manager._operation_lock.release()
