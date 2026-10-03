import pytest
from unittest.mock import patch, MagicMock
from agent.multi_agent import AdTechMultiAgentGraph

@patch("groq.Groq")
def test_supervisor_node_routing_to_scraper(mock_groq_client):
    """
    Vérifie que le Superviseur renvoie correctement 'scraper_agent'
    lorsque la BDD n'a pas encore été consultée.
    """
    # Simulation de la réponse du LLM pour le Superviseur
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content="SCRAPER"))
    ]
    
    # Injection du mock dans l'instance
    agent_system = AdTechMultiAgentGraph()
    agent_system.client.chat.completions.create = MagicMock(return_value=mock_response)

    state = {"messages": [{"role": "user", "content": "Analyse Nike"}]}
    result = agent_system._supervisor_node(state)

    assert result["next_agent"] == "scraper_agent"

def test_route_supervisor_end():
    """Vérifie le routage vers END quand la mission est marquée terminée."""
    agent_system = AdTechMultiAgentGraph()
    state = {"next_agent": "END"}
    decision = agent_system._route_supervisor(state)
    assert decision == "END"