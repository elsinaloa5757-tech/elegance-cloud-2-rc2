from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIN = ROOT / 'server_windows'


def test_block9_windows_scripts_exist():
    for name in (
        'Actualizar-Bloque9.ps1',
        'Iniciar-Elegance-Bloque9.ps1',
        'Vigilar-Elegance-Bloque9.ps1',
        'Diagnosticar-Bloque9.ps1',
    ):
        assert (WIN / name).is_file(), name


def test_runner_uses_verified_uvicorn_command():
    text = (WIN / 'Iniciar-Elegance-Bloque9.ps1').read_text(encoding='utf-8')
    assert '-m uvicorn server:app' in text
    assert '--host 127.0.0.1' in text
    assert 'server.log' in text


def test_updater_preserves_data_and_registers_watchdog():
    text = (WIN / 'Actualizar-Bloque9.ps1').read_text(encoding='utf-8')
    assert "Join-Path $InstallRoot 'data'" in text
    assert 'Elegance Server Watchdog' in text
    assert 'New-ScheduledTaskTrigger -AtStartup' in text
    assert '/mobile-center' in text
    assert '/server-status' in text
