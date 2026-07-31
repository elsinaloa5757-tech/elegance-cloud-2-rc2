from services.security_platform import is_public


def test_pwa_assets_are_public() -> None:
    assert is_public("/manifest.webmanifest")
    assert is_public("/sw.js")
    assert is_public("/pwa-icon.svg")
    assert is_public("/pwa-icon-192.png")
    assert is_public("/pwa-icon-512.png")
