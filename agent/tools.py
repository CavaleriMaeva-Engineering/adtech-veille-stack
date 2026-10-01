#ce fichier contient la boîte à outils que notre agent autonome pourra utiliser pour interroger la bdd et envoyer des notifs

import sqlite3
import os #permet d'intéragir avec le syst d'exploitation
import requests #bibli HTTP qui permet d'envoyer des requêtes vers le web (ici vers l'APi de slack)
from typing import Dict, Any, List

#config du chemin vers la bdd
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "adtech_alerts.db")

#fonction qui permet à l'agent de calculer des stats financières sur un concurrent spécifique 
def get_competitor_stats(competitor_name: str) -> Dict[str, Any]:
    #cette description est essentielle pour l'agent car il l'utilise pour comprendre quand et pourquoi il doi appeler cette fonction
    """
    Interroge la bdd pour obtenir le nombre d'alertes, le prix moyen, min et max pour un concurrent donné.
    """
    conn = sqlite3.connect(DB_PATH) #ouvre la connexion vers la bdd sqlite
    cursor = conn.cursor() #curseur = outil qui permet d'exécuter des requêtes SQL

    #requête sql d'agrégation :
    query = """
    SELECT COUNT(*), AVG(price_detcted), MIN(price_detected), MAX(price_detected)
    FROM competitor_alerts
    WHERE LOWER(competitor_name) LIKE LOWER(?)
    """
    #LOWER(...) LIKE LOWER (?) rend la recherche insensible à la casse
    # placeholder ? (%S en PostgreSQL) évite les injections SQL
    
    cursor.execute(query, (f"%{competitor_name}%",))
    #% permet de faire une recherche partielle (ex Amazon trouvera Amazon FR)
    row = cursor.fetchone() #récupère la première ligne de résultat
    conn.close()

    if row and row[0] > 0 :
        return {
            "competitor": competitor_name,
            "total_alerts": row[0],
            "avg_price": round(row[1], 2),
            "min_price": round(row[2], 2),
            "max_price": round(row[3], 2)
        }
    return {"message": f"Aucune alerte trouvée en bdd pour le concurrent '{competitor_name}'."}

#fonction qui permet à l'agent de consulter un historique récent des annonces
def get_recent_alerts(limit: int = 5) -> List[Dict[str, Any]]:
    """
    Récupère les N dernières alertes de veille enregistrées en base.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    query = """
    SELECT id, competitor_name, ad_title, price_detected, source
    FROM competitor_alerts
    ORDER BY id DESC
    LIMIT ?
    """
    cursor.execute(query, (limit,))
    rows = cursor.fetchall() #récupère toutes les lignes de la requête contrairement à fetchone
    conn.close()

    alerts = []
    for r in rows:
        alerts.append({
            "id": r[0],
            "competitor_name": r[1],
            "ad_title": r[2],
            "price_detected": r[3],
            "source": r[4]
        })
    return alerts

#fonction qui donne à l'agent la capcité d'interagir avec l'extérieur en postant des alertes sur slack
def send_slack_report(report_text: str) -> Dict[str, str]:
    """
    Envoie un rapport synthétique ou une alerte sur le canal Slack de l'équipe.
    """
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return {"status": "error", "message": "Variable SLACK_WEBHOOK_URL non configurée."}

    #payload prépare l'objet JSON au format attendu par slack
    payload = {"text": f"🤖 *Rapport Agent IA AdTech* :\n{report_text}"}
    response = requests.post(webhook_url, json=payload) 

    if response.status_code == 200:
        return {"status": "success", "message": "Rapport envoyé sur Slack avec succès."}
    return {"status": "error", "message": f"Échec d'envoi Slack (code HTTP {response.status_code})."}