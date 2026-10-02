import json
import os
import sys
import time
 
# Ajout du dossier parent au path Python pour importer correctement les modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
 
from groq import Groq
 
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
 
 
class AdTechReActAgent:
    """
    Agent IA de veille AdTech basé sur la boucle de raisonnement ReAct
    et connecté à l'API Groq (modèle configurable, par défaut gpt-oss-20b).
    """
 
    def __init__(self, max_iterations: int = 5):
        # Vérification de la clé API Groq
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("[ERREUR] La variable d'environnement GROQ_API_KEY est manquante.")
 
        # Initialisation du client officiel Groq et choix du modèle (variable d'environnement ou défaut)
        self.client = Groq(api_key=api_key)
        self.model_name = os.getenv("GROQ_MODEL", DEFAULT_MODEL)
        self.guardrail = AgentGuardrail(max_iterations=max_iterations)
 
    def _call_llm(self, messages: list):
        """
        Appelle l'API Groq avec des retries limités aux erreurs transitoires.
        Retourne la réponse, ou None si l'appel est définitivement impossible.
        """
        # Paramètres pour la gestion des retries
        max_retries = 3
        base_delay = 3
 
        for attempt in range(1, max_retries + 1):
            try:
                return self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    tools=TOOLS_SCHEMA,
                    tool_choice="auto",
                    temperature=0.0,
                )
 
            except Exception as e:
                # Code HTTP de l'erreur (None si erreur réseau sans réponse HTTP)
                status = getattr(e, "status_code", None)
 
                # Erreur client non récupérable (404 modèle inconnu, 400, 401...) : inutile de réessayer
                # Seul le 429 (limite de débit) est considéré comme transitoire parmi les 4xx
                if status is not None and 400 <= status < 500 and status != 429:
                    print(f"❌ [ERREUR API NON RÉCUPÉRABLE] (modèle : {self.model_name}) : {e}")
                    return None
 
                # Erreur transitoire (429, 5xx, timeout, réseau) : nouvelle tentative avec délai croissant
                print(f"⚠️ [ERREUR API] Tentative {attempt}/{max_retries} : {e}")
                if attempt < max_retries:
                    time.sleep(base_delay * attempt)
 
        return None
 
    def _execute_tool(self, tool_name: str, tool_args: dict) -> str:
        """
        Exécute l'outil local demandé par le modèle et retourne l'observation sous forme de texte.
        Les erreurs sont renvoyées au modèle comme observation plutôt que de faire planter l'agent.
        """
        # Outil absent du registre
        if tool_name not in TOOL_REGISTRY:
            return f"Erreur : Outil '{tool_name}' inconnu dans le registre."
 
        # Exécution protégée de la fonction Python locale
        try:
            return str(TOOL_REGISTRY[tool_name](**tool_args))
        except Exception as e:
            return f"Erreur lors de l'exécution de '{tool_name}' : {e}"
 
    def run(self, user_query: str):
        print(f"\n[AGENT ADTECH] Requête reçue : '{user_query}' (modèle : {self.model_name})\n")
 
        # Validation de la requête d'entrée via le garde-fou
        try:
            self.guardrail.validate_input(user_query)
        except GuardrailException as e:
            print(f" {e}")
            return
 
        # Historique des messages pour la session ReAct
        messages = [
            {"role": "user", "content": user_query}
        ]
 
        # Boucle principale ReAct
        while True:
            # Appel du modèle (avec gestion des retries)
            response = self._call_llm(messages)
 
            # Si l'appel a échoué définitivement
            if response is None:
                print("❌ [ÉCHEC EXÉCUTION] Impossible de contacter l'API.")
                return
 
            response_message = response.choices[0].message
            tool_calls = response_message.tool_calls
 
            # Ajout de la réponse de l'assistant à l'historique
            messages.append(response_message)
 
            # Cas où le modèle décide de déclencher un ou plusieurs outils (Tool Calling)
            if tool_calls:
                for tool_call in tool_calls:
                    tool_name = tool_call.function.name
 
                    # Décodage des arguments JSON générés par le modèle (arguments vides = dict vide)
                    try:
                        tool_args = json.loads(tool_call.function.arguments or "{}")
                    except json.JSONDecodeError as e:
                        print(f"❌ [ERREUR] Arguments JSON invalides pour '{tool_name}' : {e}")
                        messages.append({
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": tool_name,
                            "content": f"Erreur : arguments JSON invalides ({e}).",
                        })
                        continue
 
                    print(f"THOUGHT/ACTION : le modèle souhaite exécuter '{tool_name}' avec {tool_args}")
 
                    # Passage par le garde-fou d'action
                    try:
                        self.guardrail.check_execution_limits(tool_name, tool_args)
                    except GuardrailException as e:
                        print(f"\n INTERCEPTION GARDE-FOU : {e}\n")
                        return
 
                    # Exécution réelle de la fonction Python locale
                    print(f"ACTION : Exécution locale de {tool_name}({tool_args})")
                    observation = self._execute_tool(tool_name, tool_args)
                    print(f"OBSERVATION : {observation}\n")
 
                    # Réinjection de l'observation dans l'historique sous forme de rôle 'tool'
                    messages.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": tool_name,
                        "content": str(observation),
                    })
            else:
                # Réponse finale de l'agent une fois le raisonnement terminé
                final_text = response_message.content
                final_res = self.guardrail.validate_output(final_text, source_data_exists=True)
                print(f"RÉPONSE FINALE : {final_res}\n")
                return final_res
 
 
if __name__ == "__main__":
    agent = AdTechReActAgent()
    agent.run("Analyse les statistiques du concurrent Nike, extrait les dernières alertes et envoie-les sur Slack.")
 
