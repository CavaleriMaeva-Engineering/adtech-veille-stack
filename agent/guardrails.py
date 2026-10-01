import json
from typing import Dict, Any

class GuardrailException(Exception):
    """
    Exception levée lorsqu'un garde-fou est violé.
    """
    pass

class AgentGuardrail:
    """
    Garde-fou d'exécution pour superviser la boucle de raisonnement de l'agent.
    """

    def __init__(self, max_iterations: int = 5):
        self.max_iterations = max_iterations
        self.history = []

    def validate_input(self, user_query: str) -> bool:
        """
        Garde-fou d'entrée : Vérifie que la requête ne dépasse pas une certaine taille 
        et ne contient pas de mots-clés suspects de prompt injection.
        """
        if not user_query or len(user_query.strip())==0 :
            raise GuardrailException("[GARDE_FOU ENTRÉE] La requête utilisateur est vide.")

        forbidden_keywords = ["IGNORE PREVIOUS INSTRUCTIONS", "DROP TABLE", "DELETE FROM"]
        for kw in forbidden_keywords :
            if kw.lower() in user_query.lower() :
                raise GuardrailException(f"[GARDE-FOU ENTRÉE] Instruction interdite détectée : '{kw}'")
        return True 

    def check_execution_limits(self, tool_name:str, tool_args:Dict[str, Any]):
        """
        Garde-fou d'action : Empêche les boucles infinies et le surcoût d'API.
        """
        #Vérification du plafond d'itérations 
        if len(self.history) >= self.max_iterations :
            raise GuardrailException(
                f"[GARDE-FOU ACTION] Limite de {self.max_iterations} itérations atteinte."
                "Arrêt d'urgence pour protéger le budget API."
            )

        #Détection de boucle répétitive (même outil+même arguments d'affilée)
        current_signature = (tool_name, json.dumps(tool_args, sort_keys=True))
        if self.history and self.history[-1] == current_signature :
            raise GuardrailException(
                f"[GARDE-FOU ACTION] Boucle infinie détectée."
                f"L'outil '{tool_name}' a été appelé deux fois de suite avec les mêmes paramètres."
            )
        self.history.append(current_signature)

    def validate_output(self, response_text:str, source_data_exists:bool) -> str:
        """
        Garde-fou de sortie : Contrôle d'ancrage (Anti-hallucination).
        """
        if not source_data_exists and "€" in response_text :
            raise GuardrailException(
                "[GARDE-FOU SORTIE] Détection d'hallucination :"
                "L'agent a généré un prix alors qu'aucune donnée n'a été trouvée en BDD."
            )
        return response_text
        
