import json
import os
import sys
import time
from typing import TypedDict, Annotated, List, Dict, Any

# Ajout du dossier parent au path Python pour importer correctement les modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
 
from groq import Groq
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
 
from agent.guardrails import AgentGuardrail, GuardrailException
from agent.tools import get_competitor_stats, get_recent_alerts, send_slack_report
 
# Modèle Groq utilisé par défaut (remplaçant officiel de llama-3.1-8b-instant, déprécié le 16/08/2026)
# Surchargeable sans modifier le code : export GROQ_MODEL="openai/gpt-oss-120b"
DEFAULT_MODEL = "openai/gpt-oss-20b"
 
# Registre des outils disponibles pour l'agent
TOOL_REGISTRY = {
    "get_competitor_stats": get_competitor_stats,
    "get_recent_alerts": get_recent_alerts,
    "send_slack_report": send_slack_report,
}
 
# Définition des schémas JSON Schema pour le Function Calling Groq
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_competitor_stats",
            "description": "Récupère les statistiques clés d'un concurrent (part de marché, dépenses, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "competitor_name": {
                        "type": "string",
                        "description": "Nom du concurrent (ex: Nike, Adidas)",
                    }
                },
                "required": ["competitor_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_alerts",
            "description": "Récupère les dernières alertes de veille AdTech.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Nombre maximum d'alertes à récupérer",
                        "default": 3,
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_slack_report",
            "description": "Envoie un message ou rapport synthétique sur un canal Slack.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Le texte du rapport à envoyer sur Slack",
                    }
                },
                "required": ["message"],
            },
        },
    },
]

# Définition de l'état du graphe (AgentState)
class AgentState(TypedDict):
    """
    État partagé du graphe.
    'messages' utilise 'add_messages' pour ajouter chaque nouveau message à l'historique
    sans écraser les précédents.
    """
    messages: Annotated[List[Dict[str, Any]], add_messages]

# Classe de l'agent LangGraph
class AdTechLangGraphAgent:
    def __init__(self, max_iterations: int = 5):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("[ERREUR] La variable GROQ_API_KEY est manquante.")
        
        self.client = Groq(api_key=api_key)
        self.model_name = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
        self.guardrail = AgentGuardrail(max_iterations=max_iterations)
        
        # Construction du graphe d'état
        self.app = self._build_graph()

    # Noeud 1 : appeler le modèle LLM
    def _call_model_node(self, state: AgentState) -> Dict[str, Any]:
        print(f"\n [NŒUD AGENT] Consultation de Groq ({self.model_name})...")
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=state["messages"],
            tools=TOOLS_SCHEMA,
            tool_choice="auto",
            temperature=0.0
        )
        response_message = response.choices.message
        
        # Conversion du message retourné pour mise à jour de l'état
        msg_dict = {"role": "assistant", "content": response_message.content}
        if response_message.tool_calls:
            msg_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                }
                for tc in response_message.tool_calls
            ]
            
        return {"messages": [msg_dict]}

    # Noeud 2 : Exécuter l'outil demandé (avec Garde-fou d'Action)   
    def _execute_tools_node(self, state: AgentState) -> Dict[str, Any]:
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
                print(f"THOUGHT/ACTION : Souhait d'exécuter '{tool_name}' avec {tool_args}")
                
                # Validation de sécurité via le garde-fou d'action
                try:
                    self.guardrail.check_execution_limits(tool_name, tool_args)
                except GuardrailException as e:
                    print(f"\n❌ [INTERCEPTION GARDE-FOU] : {e}\n")
                    observation = f"Action bloquée par le garde-fou : {e}"
                else:
                    print(f"ACTION : Exécution locale de {tool_name}({tool_args})")
                    if tool_name in TOOL_REGISTRY:
                        try:
                            observation = str(TOOL_REGISTRY[tool_name](**tool_args))
                        except Exception as err:
                            observation = f"Erreur lors de l'exécution de '{tool_name}' : {err}"
                    else:
                        observation = f"Erreur : Outil '{tool_name}' inconnu dans le registre."

            print(f"OBSERVATION : {observation}\n")

            # Formatage de la réponse de l'outil pour réinjection
            new_tool_messages.append({
                "tool_call_id": call["id"],
                "role": "tool",
                "name": tool_name,
                "content": observation
            })

        return {"messages": new_tool_messages}
    
    # Arête conditionnelle : Décider de continuer ou d'arêter
    def _should_continue(self, state: AgentState) -> str:
        last_message = state["messages"][-1]
        
        # Si le dernier message contient des appels d'outils -> Direction le nœud 'tools'
        if last_message.get("tool_calls"):
            return "tools"
        # Sinon -> Fin du graphe
        return END

    # Construction du stategraph
    def _build_graph(self):
        workflow = StateGraph(AgentState)

        # Ajout des deux nœuds principaux
        workflow.add_node("agent", self._call_model_node)
        workflow.add_node("tools", self._execute_tools_node)

        # Point d'entrée du graphe
        workflow.add_edge(START, "agent")

        # Arête conditionnelle après le nœud 'agent'
        workflow.add_conditional_edges(
            "agent",
            self._should_continue,
            {
                "tools": "tools",
                END: END
            }
        )

        # Boucle du nœud 'tools' vers le nœud 'agent' pour l'itération suivante
        workflow.add_edge("tools", "agent")

        # Compilation du graphe
        return workflow.compile()

    # Méthode d'exécution 
    def run(self, user_query: str):
        print(f"\n🚀 [AGENT LANGGRAPH ADTECH] Requête reçue : '{user_query}'\n")

        # 1. Garde-fou d'entrée
        try:
            self.guardrail.validate_input(user_query)
        except GuardrailException as e:
            print(f"❌ {e}")
            return

        initial_state = {
            "messages": [{"role": "user", "content": user_query}]
        }

        # 2. Exécution du graphe de bout en bout
        final_state = self.app.invoke(initial_state)

        # 3. Réponse finale et garde-fou de sortie
        final_message = final_state["messages"][-1]
        final_text = final_message.get("content", "")
        
        final_res = self.guardrail.validate_output(final_text, source_data_exists=True)
        print(f"✅ RÉPONSE FINALE : {final_res}\n")
        return final_res

 
if __name__ == "__main__":
    agent = AdTechLangGraphAgent()
    print("--- STRUCTURE DU GRAPHE LANGGRAPH ---")
    print(agent.app.get_graph().draw_ascii())
    print("-------------------------------------")
    agent.run("Analyse les statistiques du concurrent Nike, extrait les dernières alertes et envoie-les sur Slack.")
 
