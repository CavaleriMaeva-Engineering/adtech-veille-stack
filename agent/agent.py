import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from google import genai
from google.genai import types

from agent.tools import get_competitor_stats, get_recent_alerts, send_slack_report
from agent.guardrails import AgentGuardrail, GuardrailException

#registre des outils disponibles pour l'agent
TOOL_REGISTRY = {
    "get_competitor_stats": get_competitor_stats,
    "get_recent_alerts": get_recent_alerts,
    "send_slack_report": send_slack_report
}

class AdTechReActAgent :
    """
    Agent IA de veille AdTech basé sur la boucle de raisonnement ReAct
    et connecté à l'API Google Gemini.
    """

    def __init__(self, max_iterations: int = 5) :
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key :
            raise ValueError("[ERREUR] La variable d'environnement GEMINI_API_KEY est manquante.")

        #Initialisation du client officiel Google GenAI
        self.client = genai.Client(api_key=api_key)
        self.model_name = "gemini-2.5-flash"
        self.guardrail = AgentGuardrail(max_iterations=max_iterations)

    def run(self, user_query: str) :
        print(f"\n [AGENT ADTECH] Requête reçue : '{user_query}'\n")

        #Validation de la requête d'entrée via le garde-fou
        try :
            self.guardrail.validate_input(user_query)
        except GuardrailException as e :
            print(f" {e}")
            return

        #Configuration des outils transmis à Gemini
        #Gemini (contrairement à Claude) accepte directement les fonctions Python natives dont il extrait la signature
        #Pas besoin de développer le JSON Schema
        config = types.GenerateContentConfig(
            tools=[get_competitor_stats, get_recent_alerts, send_slack_report],
            temperature=0.0
        )

        #Création de la session de dialogue ReAct
        chat = self.client.chats.create(model=self.model_name, config=config)
        current_prompt = user_query

        #Boucle ReAct 
        while True :
            response = chat.send_message(current_prompt)

            #cas où Gemini décide de déclencher un ou plusieurs outils
            if response.function_calls :
                for call in response.function_calls :
                    tool_name = call.name
                    tool_args = dict(call.args)
                    print(f"THOUGHT/ACTION : Gemini souhaite exécuter '{tool_name}' avec {tool_args}")

                    #passage par le garde-fou d'action
                    try :
                        self.guardrails.check_execution_limits(tool_name, tool_args)
                    except GuardrailException as e :
                        print(f"\n INTERCEPTION GARDE-FOU : {e}\n")
                        return

                    #Exécution réelle de la fonction Python locale
                    print(f"ACTION : Exécution locale de {tool_name}({tool_args})")
                    if tool_name in TOOL_REGISTRY :
                        observation = TOOL_REGISTRY[tool_name](**tool_args)
                    else :
                        observation = f"Erreur : Outil '{tool_name}' inconnu dans le registre."
                    print(f"OBSERVATION : {observation}\n")

                    #Réinjection de l'observation dans la session Gemini pour l'itération suivante 
                    current_prompt = types.Part.from_function_response(
                        name=tool_name,
                        response={"result": observation}
                    )
            else :
                #Réponse finale de l'agent 
                final_text = response.text
                final_res = self.guardrails.validate_output(final_text, source_data_exists=True)
                print(f"RÉPONSE FINALE : {final_res}\n")
                return final_res

if __name__=="__main__":
    agent = AdTechReActAgent()
    agent.run("Analyse les statistiques du concurrent Nike et extrait les dernières alertes.")



