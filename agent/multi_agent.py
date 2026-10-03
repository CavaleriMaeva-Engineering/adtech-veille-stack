import json
import os
import sys
from typing import Any, Dict, List, TypedDict, Annotated

# Ajout du dossier parent au path Python
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from groq import Groq
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from agent.guardrails import AgentGuardrail, GuardrailException
from agent.tools import get_competitor_stats, get_recent_alerts, send_slack_report

DEFAULT_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

SCRAPER_TOOLS = {
    "get_competitor_stats": get_competitor_stats,
    "get_recent_alerts": get_recent_alerts,
}

REPORTER_TOOLS = {
    "send_slack_report": send_slack_report,
}

ALL_TOOLS = {**SCRAPER_TOOLS, **REPORTER_TOOLS}

SCRAPER_SCHEMA = [
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
]

REPORTER_SCHEMA = [
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


class MultiAgentState(TypedDict):
    messages: Annotated[List[Any], add_messages]
    next: str


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

        formatted_msg = {"role": role, "content": getattr(msg, "content", "") or ""}

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


class AdTechMultiAgentSystem:
    def __init__(self, max_iterations: int = 5):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("[ERREUR] La variable GROQ_API_KEY est manquante.")

        self.client = Groq(api_key=api_key)
        self.model_name = DEFAULT_MODEL
        self.guardrail = AgentGuardrail(max_iterations=max_iterations)
        self.app = self._build_graph()

    def _supervisor_node(self, state: MultiAgentState) -> Dict[str, Any]:
        print("\n[SUPERVISEUR] Analyse de l'état global et décision...")

        system_prompt = (
            "Tu es le chef d'orchestre d'un système multi-agents AdTech.\n"
            "Rôles disponibles :\n"
            "- scraper_agent : pour extraire/récupérer les données brutes (stats, alertes).\n"
            "- reporter_agent : pour synthétiser les données et les envoyer sur Slack via son outil.\n"
            "- FINISH : uniquement si le rapport a DÉJÀ été rédigé ET envoyé sur Slack.\n\n"
            "DIRECTIVES DE SORTIE :\n"
            "Tu dois répondre PAR UN SEUL MOT brut, sans balises, sans JSON, sans fonction :\n"
            "Soit 'scraper_agent', soit 'reporter_agent', soit 'FINISH'."
        )

        formatted_history = format_messages_for_groq(state["messages"])
        messages = [{"role": "system", "content": system_prompt}] + formatted_history

        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=0.0,
            max_tokens=20,  # Empêche la génération de longs payloads ou d'hallucinations de fonctions
        )

        decision = response.choices[0].message.content.strip().lower()
        print(f"[SUPERVISEUR] Décision brute : '{decision}'")

        if "reporter" in decision:
            next_step = "reporter_agent"
        elif "scraper" in decision:
            next_step = "scraper_agent"
        elif "finish" in decision:
            next_step = END
        else:
            # Sécurité si la réponse est ambiguë : analyse simple sur l'historique
            has_slack_sent = any("send_slack_report" in str(m) for m in state["messages"])
            if has_slack_sent:
                next_step = END
            else:
                next_step = "reporter_agent"

        print(f"[SUPERVISEUR] Aiguillage retenu : {next_step}")
        return {"next": next_step}

    def _scraper_agent_node(self, state: MultiAgentState) -> Dict[str, Any]:
        print("\n[AGENT SCRAPER] Analyse des besoins de collecte...")
        formatted_messages = format_messages_for_groq(state["messages"])

        system_instruction = {
            "role": "system",
            "content": "Tu es un agent spécialisé dans l'extraction de données de veille AdTech. Utilise tes outils pour collecter les statistiques ou alertes demandées.",
        }

        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[system_instruction] + formatted_messages,
            tools=SCRAPER_SCHEMA,
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

    def _reporter_agent_node(self, state: MultiAgentState) -> Dict[str, Any]:
        print("\n[AGENT REPORTER] Préparation de la synthèse et de l'envoi Slack...")
        formatted_messages = format_messages_for_groq(state["messages"])

        system_instruction = {
            "role": "system",
            "content": "Tu es un agent chargé de rédiger un rapport clair à partir des données récoltées et de l'envoyer IMPÉRATIVEMENT sur Slack avec l'outil 'send_slack_report'.",
        }

        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[system_instruction] + formatted_messages,
            tools=REPORTER_SCHEMA,
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

    def _execute_tools_node(self, state: MultiAgentState) -> Dict[str, Any]:
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
                print(f"ACTION : Exécution de '{tool_name}' avec {tool_args}")

                try:
                    self.guardrail.check_execution_limits(tool_name, tool_args)
                except GuardrailException as e:
                    print(f"\n❌ [INTERCEPTION GARDE-FOU] : {e}\n")
                    observation = f"Action bloquée par le garde-fou : {e}"
                else:
                    if tool_name in ALL_TOOLS:
                        try:
                            observation = str(ALL_TOOLS[tool_name](**tool_args))
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

    def _should_continue_agent(self, state: MultiAgentState) -> str:
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
        return "supervisor"

    def _route_supervisor(self, state: MultiAgentState) -> str:
        return state.get("next", END)

    def _build_graph(self):
        workflow = StateGraph(MultiAgentState)

        workflow.add_node("supervisor", self._supervisor_node)
        workflow.add_node("scraper_agent", self._scraper_agent_node)
        workflow.add_node("reporter_agent", self._reporter_agent_node)
        workflow.add_node("tools", self._execute_tools_node)

        workflow.add_edge(START, "supervisor")

        workflow.add_conditional_edges(
            "supervisor",
            self._route_supervisor,
            {
                "scraper_agent": "scraper_agent",
                "reporter_agent": "reporter_agent",
                END: END,
            },
        )

        workflow.add_conditional_edges(
            "scraper_agent",
            self._should_continue_agent,
            {"tools": "tools", "supervisor": "supervisor"},
        )

        workflow.add_conditional_edges(
            "reporter_agent",
            self._should_continue_agent,
            {"tools": "tools", "supervisor": "supervisor"},
        )

        workflow.add_edge("tools", "supervisor")

        return workflow.compile()

    def run(self, user_query: str):
        print(f"\n🚀 [SYSTEME MULTI-AGENTS LANGGRAPH] Requête reçue : '{user_query}'\n")

        try:
            self.guardrail.validate_input(user_query)
        except GuardrailException as e:
            print(f"❌ {e}")
            return

        initial_state = {
            "messages": [{"role": "user", "content": user_query}],
            "next": "supervisor",
        }

        final_state = self.app.invoke(initial_state)

        final_message = final_state["messages"][-1]
        final_text = (
            getattr(final_message, "content", "")
            if not isinstance(final_message, dict)
            else final_message.get("content", "")
        )

        final_res = self.guardrail.validate_output(final_text, source_data_exists=True)
        print(f"✅ RÉPONSE FINALE MULTI-AGENTS : {final_res}\n")
        return final_res


if __name__ == "__main__":
    agent_system = AdTechMultiAgentSystem()
    print("--- STRUCTURE DU GRAPHE MULTI-AGENTS ---")
    try:
        print(agent_system.app.get_graph().draw_ascii())
    except ImportError:
        print("[INFO] Installe 'grandalf' via 'pip install grandalf' pour visualiser le graphe en ASCII.")
    print("----------------------------------------")
    agent_system.run("Analyse les statistiques du concurrent Nike, extrait les dernières alertes et envoie-les sur Slack.")