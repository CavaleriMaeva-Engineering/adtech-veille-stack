import os
import pytest
from unittest.mock import patch, MagicMock
from agent.multi_agent import AdTechMultiAgentSystem


@patch.dict(os.environ, {"GROQ_API_KEY": "gsk_dummy_test_key_for_pytest"})
@patch("groq.Groq")
def test_supervisor_node_routing_to_scraper(mock_groq_class, mock_env):
    """
    Vérifie que le Superviseur renvoie correctement 'scraper_agent'
    lorsque la BDD n'a pas encore été consultée.
    """
    # Instanciation avec la clé factice en environnement
    agent_system = AdTechMultiAgentSystem()

    # Simulation de la réponse du LLM pour le Superviseur
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content="scraper_agent"))
    ]
    agent_system.client.chat.completions.create = MagicMock(return_value=mock_response)

    state = {"messages": [{"role": "user", "content": "Analyse Nike"}]}
    result = agent_system._supervisor_node(state)

    assert result["next"] == "scraper_agent"


@patch.dict(os.environ, {"GROQ_API_KEY": "gsk_dummy_test_key_for_pytest"})
@patch("groq.Groq")
def test_route_supervisor_end(mock_groq_class, mock_env):
    """Vérifie le routage vers END quand la mission est marquée terminée."""
    agent_system = AdTechMultiAgentSystem()
    state = {"next": "__end__"}
    decision = agent_system._route_supervisor(state)
    assert decision == "__end__"