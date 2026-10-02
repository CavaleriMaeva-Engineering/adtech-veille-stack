import os
import sys
import json
from typing import TypedDict, Annotated, List, Dict, Any

# Ajustement du chemin pour l'import des modules du projet
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from groq import Groq
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

from agent.guardrails import AgentGuardrail, GuardrailException
from agent.tools import get_competitor_stats, get_recent_alerts, send_slack_report

# REGISTRE GLOBAL DES FONCTIONS PYTHON
TOOL_REGISTRY = {
    "get_competitor_stats": get_competitor_stats,
    "get_recent_alerts": get_recent_alerts,
    "send_slack_report": send_slack_report,
}

# SCHÉMAS D'OUTILS SÉPARÉS ET ÉTANCHES PAR AGENT

# Outils réservés à l'Agent Extracteur / Scraper
SCRAPER_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_competitor_stats",
            "description": "Récupère les statistiques clés d'un concurrent (prix moyen, min, max, total d'alertes).",
            "parameters": {
                "type": "object",
                "properties": {
                    "competitor_name": {"type": "string", "description": "Nom du concurrent (ex: Nike, Adidas)"}
                },
                "required": ["competitor_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_alerts",
            "description": "Récupère les N dernières alertes enregistrées en base.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Nombre d'alertes à récupérer", "default": 3}
                },
            },
        },
    },
]

# Outils réservés à l'Agent Analyste / Rédacteur
REPORTER_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "send_slack_report",
            "description": "Envoie un rapport synthétique de veille sur le canal Slack de l'équipe.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Contenu du rapport à envoyer"}
                },
                "required": ["message"],
            },
        },
    },
]

# ÉTAT PARTAGÉ DU SYSTÈME MULTI-AGENTS (AgentState)
class MultiAgentState(TypedDict):
    messages: Annotated[List[Dict[str, Any]], add_messages]
    next_agent: str

# CLASSE PRINCIPALE DE L'ARCHITECTURE MULTI-AGENTS
class AdTechMultiAgentGraph:
    def __init__(self, max_iterations: int = 5):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("[ERREUR] La variable GROQ_API_KEY est manquante dans l'environnement.")
        
        self.client = Groq(api_key=api_key)
        self.model_name = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
        self.guardrail = AgentGuardrail(max_iterations=max_iterations)
        self.app = self._build_graph()

# NŒUD 1 : SUPERVISEUR 
    def _supervisor_node(self, state: MultiAgentState) -> Dict[str, Any]:
        print("\n[SUPERVISEUR] Analyse de l'état global et décision...")
        system_prompt = (
            "Tu es le Superviseur du pôle de veille AdTech. Tes agents spécialisés sont :\n"
            "- 'scraper_agent' : extrait les métriques et alertes BDD.\n"
            "- 'reporter_agent' : rédige la synthèse et envoie le rapport final sur Slack.\n"
            "Analyse l'historique :\n"
            "1. Si les données BDD n'ont pas encore été extraites, réponds exactement 'SCRAPER'.\n"
            "2. Si les données ont été extraites mais que le rapport Slack n'a pas été envoyé, réponds 'REPORTER'.\n"
            "3. Si la mission est terminée, réponds 'FIN'."
        )
        messages = [{"role": "system", "content": system_prompt}] + state["messages"]
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=0.0
        )
        decision = response.choices.message.content.strip().upper()
        
        if "SCRAPER" in decision:
            next_step = "scraper_agent"
        elif "REPORTER" in decision:
            next_step = "reporter_agent"
        else:
            next_step = "END"
            
        print(f"👉 Décision du Superviseur : Orientation vers '{next_step}'")
        return {"next_agent": next_step}

# NŒUD 2 : AGENT EXTRACTEUR / SCRAPER
    def _scraper_agent_node(self, state: MultiAgentState) -> Dict[str, Any]:
        print("\n[AGENT SCRAPER] Consultation des outils d'extraction BDD...")
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=state["messages"],
            tools=SCRAPER_TOOLS_SCHEMA,
            tool_choice="auto",
            temperature=0.0
        )
        msg = response.choices.message
        msg_dict = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            msg_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                }
                for tc in msg.tool_calls
            ]
        return {"messages": [msg_dict]}

    # NŒUD 3 : AGENT ANALYSTE / RÉDACTEUR
    def _reporter_agent_node(self, state: MultiAgentState) -> Dict[str, Any]:
        print("\n[AGENT RÉDACTEUR] Préparation et publication du rapport Slack...")
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=state["messages"],
            tools=REPORTER_TOOLS_SCHEMA,
            tool_choice="auto",
            temperature=0.0
        )
        msg = response.choices.message
        msg_dict = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            msg_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                }
                for tc in msg.tool_calls
            ]
        return {"messages": [msg_dict]}

    # NŒUD 4 : EXÉCUTEUR D'OUTILS AVEC GARDE-FOUS
    def _execute_tools_node(self, state: MultiAgentState) -> Dict[str, Any]:
        last_message = state["messages"][-1]
        tool_calls = last_message.get("tool_calls", [])
        new_tool_messages = []

        for call in tool_calls:
            tool_name = call["function"]["name"]
            tool_args_str = call["function"]["arguments"] or "{}"
            try:
                tool_args = json.loads(tool_args_str)
            except json.JSONDecodeError as e:
                observation = f"Erreur : Arguments JSON invalides ({e})."
                tool_args = {}
            else:
                print(f"THOUGHT/ACTION : Exécution de '{tool_name}' avec {tool_args}")
                
                # Passage par le garde-fou d'action
                try:
                    self.guardrail.check_execution_limits(tool_name, tool_args)
                except GuardrailException as e:
                    print(f"\n❌ INTERCEPTION GARDE-FOU : {e}\n")
                    observation = f"Action bloquée par le garde-fou : {e}"
                else:
                    if tool_name in TOOL_REGISTRY:
                        try:
                            observation = str(TOOL_REGISTRY[tool_name](**tool_args))
                        except Exception as err:
                            observation = f"Erreur lors de l'exécution de '{tool_name}' : {err}"
                    else:
                        observation = f"Erreur : Outil '{tool_name}' inconnu dans le registre."

            print(f"OBSERVATION : {observation}\n")
            new_tool_messages.append({
                "tool_call_id": call["id"],
                "role": "tool",
                "name": tool_name,
                "content": observation
            })

        return {"messages": new_tool_messages}

    # ARÊTES CONDITIONNELLES (Routage)
    def _route_supervisor(self, state: MultiAgentState) -> str:
        return state.get("next_agent", "END")

    def _route_agent_tools(self, state: MultiAgentState) -> str:
        last_message = state["messages"][-1]
        if last_message.get("tool_calls"):
            return "tools"
        return "supervisor"

    # CONSTRUCTEUR DU GRAPHE LANGGRAPH
    def _build_graph(self):
        workflow = StateGraph(MultiAgentState)

        # 1. Ajout des nœuds du graphe
        workflow.add_node("supervisor", self._supervisor_node)
        workflow.add_node("scraper_agent", self._scraper_agent_node)
        workflow.add_node("reporter_agent", self._reporter_agent_node)
        workflow.add_node("tools", self._execute_tools_node)

        # 2. Point d'entrée vers le Superviseur
        workflow.add_edge(START, "supervisor")

        # 3. Routage dynamique depuis le Superviseur
        workflow.add_conditional_edges(
            "supervisor",
            self._route_supervisor,
            {
                "scraper_agent": "scraper_agent",
                "reporter_agent": "reporter_agent",
                "END": END
            }
        )

        # 4. Routage des sous-agents (vers l'exécuteur d'outils ou retour au Superviseur)
        workflow.add_conditional_edges(
            "scraper_agent",
            self._route_agent_tools,
            {"tools": "tools", "supervisor": "supervisor"}
        )
        workflow.add_conditional_edges(
            "reporter_agent",
            self._route_agent_tools,
            {"tools": "tools", "supervisor": "supervisor"}
        )

        # 5. Retour automatique des outils vers le Superviseur
        workflow.add_edge("tools", "supervisor")

        return workflow.compile()

    def run(self, user_query: str):
        print(f"\n🚀 [SYSTEME MULTI-AGENTS LANGGRAPH] Requête reçue : '{user_query}'\n")

        # Garde-fou d'entrée
        try:
            self.guardrail.validate_input(user_query)
        except GuardrailException as e:
            print(f"❌ {e}")
            return

        initial_state = {
            "messages": [{"role": "user", "content": user_query}],
            "next_agent": "supervisor"
        }

        # Exécution du graphe multi-agents
        final_state = self.app.invoke(initial_state)

        # Réponse finale et garde-fou de sortie
        final_message = final_state["messages"][-1]
        final_text = final_message.get("content", "")
        
        final_res = self.guardrail.validate_output(final_text, source_data_exists=True)
        print(f"✅ RÉPONSE FINALE DU SYSTÈME MULTI-AGENTS : {final_res}\n")
        return final_res

if __name__ == "__main__":
    agent_system = AdTechMultiAgentGraph()
    
    # Affichage ASCII de la structure du graphe
    print("--- STRUCTURE DU GRAPHE MULTI-AGENTS ---")
    print(agent_system.app.get_graph().draw_ascii())
    print("----------------------------------------")

    agent_system.run("Analyse les statistiques du concurrent Nike, extrait les dernières alertes et envoie-les sur Slack.")