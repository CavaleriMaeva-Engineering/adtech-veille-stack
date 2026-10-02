import json
import os
import sys
import time
from typing import Any, Dict, List, TypedDict, Annotated

# Ajout du dossier parent au path Python
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from groq import Groq
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from agent.guardrails import AgentGuardrail, GuardrailException
from agent.tools import get_competitor_stats, get_recent_alerts, send_slack_report

# Modèle Groq principal utilisé hier
DEFAULT_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

# Registre des outils disponibles
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


class AgentState(TypedDict):
    messages: Annotated[List[Any], add_messages]


def format_messages_for_groq(messages: List[Any]) -> List[Dict[str, Any]]:
    formatted = []
    for msg in messages:
        if isinstance(msg, dict):
            formatted.append(msg)
            continue

        role = getattr(msg, "type", "user")
        if role == "human":
            role = "user"
        elif role == "ai":
            role = "assistant"

        formatted_msg = {"role": role, "content": msg.content or ""}

        if hasattr(msg, "additional_kwargs") and "tool_calls" in msg.additional_kwargs:
            formatted_msg["tool_calls"] = msg.additional_kwargs["tool_calls"]
        elif hasattr(msg, "tool_calls") and msg.tool_calls:
            formatted_msg["tool_calls"] = [
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc.get("name", ""),
                        "arguments": json.dumps(tc.get("args", {}))
                        if isinstance(tc.get("args"), dict)
                        else tc.get("args", "{}"),
                    },
                }
                for tc in msg.tool_calls
            ]

        if role == "tool" and hasattr(msg, "tool_call_id"):
            formatted_msg["tool_call_id"] = msg.tool_call_id

        formatted.append(formatted_msg)
    return formatted


class AdTechLangGraphAgent:
    def __init__(self, max_iterations: int = 5):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("[ERREUR] La variable GROQ_API_KEY est manquante.")

        self.client = Groq(api_key=api_key)
        self.model_name = DEFAULT_MODEL
        self.guardrail = AgentGuardrail(max_iterations=max_iterations)
        self.app = self._build_graph()

    def _call_model_node(self, state: AgentState) -> Dict[str, Any]:
        print(f"\n [NŒUD AGENT] Consultation de Groq ({self.model_name})...")
        formatted_messages = format_messages_for_groq(state["messages"])

        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=formatted_messages,
            tools=TOOLS_SCHEMA,
            tool_choice="auto",
            temperature=0.0,
        )

        response_message = response.choices[0].message

        msg_dict = {"role": "assistant", "content": response_message.content or ""}
        if response_message.tool_calls:
            msg_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in response_message.tool_calls
            ]

        return {"messages": [msg_dict]}

    def _execute_tools_node(self, state: AgentState) -> Dict[str, Any]:
        last_message = state["messages"][-1]

        tool_calls = []
        if isinstance(last_message, dict):
            tool_calls = last_message.get("tool_calls", [])
        elif hasattr(last_message, "additional_kwargs") and "tool_calls" in last_message.additional_kwargs:
            tool_calls = last_message.additional_kwargs["tool_calls"]
        elif hasattr(last_message, "tool_calls"):
            tool_calls = last_message.tool_calls

        new_tool_messages = []

        for call in tool_calls:
            if isinstance(call, dict) and "function" in call:
                tool_name = call["function"]["name"]
                tool_args_str = call["function"]["arguments"] or "{}"
                call_id = call.get("id", "")
            else:
                tool_name = call.get("name", "")
                tool_args_str = (
                    json.dumps(call.get("args", {}))
                    if isinstance(call.get("args"), dict)
                    else call.get("args", "{}")
                )
                call_id = call.get("id", "")

            try:
                tool_args = json.loads(tool_args_str) if isinstance(tool_args_str, str) else tool_args_str
            except json.JSONDecodeError as e:
                observation = f"Erreur : Arguments JSON invalides ({e})."
                tool_args = {}
            else:
                print(f"THOUGHT/ACTION : Souhait d'exécuter '{tool_name}' avec {tool_args}")

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

            new_tool_messages.append({
                "tool_call_id": call_id,
                "role": "tool",
                "name": tool_name,
                "content": observation,
            })

        return {"messages": new_tool_messages}

    def _should_continue(self, state: AgentState) -> str:
        last_message = state["messages"][-1]

        has_tools = False
        if isinstance(last_message, dict) and last_message.get("tool_calls"):
            has_tools = True
        elif hasattr(last_message, "tool_calls") and last_message.tool_calls:
            has_tools = True
        elif hasattr(last_message, "additional_kwargs") and "tool_calls" in last_message.additional_kwargs:
            has_tools = True

        if has_tools:
            return "tools"
        return END

    def _build_graph(self):
        workflow = StateGraph(AgentState)

        workflow.add_node("agent", self._call_model_node)
        workflow.add_node("tools", self._execute_tools_node)

        workflow.add_edge(START, "agent")

        workflow.add_conditional_edges(
            "agent",
            self._should_continue,
            {"tools": "tools", END: END},
        )

        workflow.add_edge("tools", "agent")

        return workflow.compile()

    def run(self, user_query: str):
        print(f"\n🚀 [AGENT LANGGRAPH ADTECH] Requête reçue : '{user_query}'\n")

        try:
            self.guardrail.validate_input(user_query)
        except GuardrailException as e:
            print(f"❌ {e}")
            return

        initial_state = {"messages": [{"role": "user", "content": user_query}]}

        final_state = self.app.invoke(initial_state)

        final_message = final_state["messages"][-1]
        final_text = (
            getattr(final_message, "content", "")
            if not isinstance(final_message, dict)
            else final_message.get("content", "")
        )

        final_res = self.guardrail.validate_output(final_text, source_data_exists=True)
        print(f"✅ RÉPONSE FINALE : {final_res}\n")
        return final_res


if __name__ == "__main__":
    agent = AdTechLangGraphAgent()
    print("--- STRUCTURE DU GRAPHE LANGGRAPH ---")
    try:
        print(agent.app.get_graph().draw_ascii())
    except ImportError:
        print("[INFO] Installe 'grandalf' via 'pip install grandalf' pour visualiser le graphe en ASCII.")
    print("-------------------------------------")
    agent.run("Analyse les statistiques du concurrent Nike, extrait les dernières alertes et envoie-les sur Slack.")