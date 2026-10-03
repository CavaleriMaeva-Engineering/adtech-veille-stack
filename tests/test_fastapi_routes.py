import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_health_check_endpoint():
    """Vérifie que la route /health renvoie un statut 200 OK."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_receive_alert_success():
    """Vérifie le succès d'une alerte valide transmise sur POST /api/v1/alerts."""
    payload = {
        "competitor_name": "Nike",
        "ad_title": "Offre Running",
        "ad_url": "https://www.nike.com/promo",
        "price_detected": 89.99,
        "source": "pytest_unit_test"
    }
    response = client.post("/api/v1/alerts", json=payload)
    assert response.status_code == 200
    json_data = response.json()
    assert json_data["status"] == "success"
    assert "inserted_id" in json_data

def test_receive_alert_pydantic_validation_error():
    """Vérifie que l'API renvoie bien un code HTTP 422 si les données sont invalides."""
    payload = {
        "competitor_name": "Nike",
        "ad_title": "Offre Running",
        "ad_url": "invalid-url-format", # URL invalide
        "price_detected": -10.0 # Prix négatif interdit par Field(..., gt=0)
    }
    response = client.post("/api/v1/alerts", json=payload)
    assert response.status_code == 422