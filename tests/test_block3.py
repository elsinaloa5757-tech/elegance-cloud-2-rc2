from __future__ import annotations


def test_deployment_readiness_development(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEGANCE_ENV", "development")
    monkeypatch.setenv("ELEGANCE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from services.deployment_readiness import deployment_readiness
    result = deployment_readiness(check_database=False)
    assert result["ready"] is True
    assert result["checks"]["persistentStorage"]["ok"] is True


def test_deployment_readiness_production_rejects_incomplete(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEGANCE_ENV", "production")
    monkeypatch.setenv("ELEGANCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ELEGANCE_ALLOWED_ORIGINS", "https://panel.example.com")
    monkeypatch.setenv("ELEGANCE_PUBLIC_URL", "https://panel.example.com")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    from services.deployment_readiness import deployment_readiness
    result = deployment_readiness(check_database=False)
    assert result["ready"] is False
    assert result["checks"]["postgresql"]["ok"] is False
    assert result["checks"]["supabase"]["ok"] is False
