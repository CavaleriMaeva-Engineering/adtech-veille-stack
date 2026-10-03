import pytest
from pydantic import ValidationError
from main import CompetitorAlert

def test_competitor_alert_valid():
    """Vérifie la création d'un objet Pydantic valide."""
    alert = CompetitorAlert(
        competitor_name="Nike",
        ad_title="Promo Running",
        ad_url="https://www.nike.com/running",
        price_detected=89.99
    )
    assert alert.competitor_name == "Nike"
    assert alert.price_detected == 89.99

def test_competitor_alert_invalid_price():
    """Vérifie que Pydantic rejette un prix négatif ou nul (Fail-Fast)."""
    with pytest.raises(ValidationError):
        CompetitorAlert(
            competitor_name="Nike",
            ad_title="Promo",
            ad_url="https://www.nike.com",
            price_detected=-10.0
        )