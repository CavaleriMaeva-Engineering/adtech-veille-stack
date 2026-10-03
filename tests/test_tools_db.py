import pytest
import sqlite3
from agent.tools import get_competitor_stats, get_recent_alerts
from database import init_db

@pytest.fixture(autouse=True)
def setup_database():
    """Fixture réinitialisant la BDD SQLite avant chaque test."""
    init_db()

def test_get_competitor_stats_not_found():
    """Vérifie le message renvoyé si le concurrent n'existe pas en BDD."""
    result = get_competitor_stats("ConcurrentInexistant999")
    assert "message" in result
    assert "Aucune" in result["message"]

def test_get_recent_alerts_returns_list():
    """Vérifie que get_recent_alerts retourne une liste d'alertes."""
    alerts = get_recent_alerts(limit=3)
    assert isinstance(alerts, list)