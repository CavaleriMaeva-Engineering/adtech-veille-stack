from fastapi import FastAPI
from pydantic import BaseModel, Field, HttpUrl
from datetime import datetime
from database import get_db_connection, init_db

#instanciation de l'app FastAPI 
app = FastAPI(title="AdTech Competitor Intelligence API")

#au démarrage de l'API on s'assure que la table existe en bdd
@app.on_event("startup")
def startup_event():
    init_db()

#définition du contrat de données (schéma pydantic)
class CompetitorAlert(BaseModel):
    competitor_name: str = Field(..., description="Nom du concurrent")
    ad_title: HttpUrl = Field(..., description="Titre de la publicité ou du produit")
    ad_url: HttpUrl = Field(..., description="URL de l'annonce")
    price_detected: float = Field(..., gt=0, description="Prix détecté (doit être >0)")
    source: str = Field(default="apify_scraper", description="Origine de la donnée")

#route de santé (healthcheck)
@app.get("/health") #si un client envoie une requête HTTP Get sur .../health on déclence la fonction
def health_check():
    return {"status": "ok", "timestamp":datetime.utcnow()}

#route post : réception de l'alerte + validation + insertion en base postegreSQL
@app.post("/api/v1/alerts")
def receive_alert(alert: CompetitorAlert) :
    #pydantic a déjà validé le json entrant ici
    insert_query="""
    INSERT INTO competitor_alerts(competitor_name, ad_title, ad_url, price_detected, source)
    VALUES (%s, %s, %s, %s, %s) 
    RETURNING id, created_at;
    """
    try : 
        #ouvre la connexion à postgres et instancie le curseur
        conn = get_db_connection
        cursor = conn.cursor()
        #exécute la requête en passant les param sous forme de tuple pour que psycopg2 les sécurise
        cursor.execute(insert_query, (
            alert.competitor_name,
            alert.ad_title,
            str(alert.ad_url),
            alert.price_detected,
            alert.source
        ))
        result = cursor.fetchone() #récupère la ligne renvoyée par le RETURNING id...
        conn.commit() #valide définitivement l'insertion en bdd
        #ferme les ressources réseau 
        cursor.close()
        conn.close()

        #renvoie la réponse du succès au client
        return {
            "status": "success",
            "message": "alerte de veille enregistrée en base PostgreSQL",
            "inserted_id": result["id"],
            "created_at": result["created_at"]
        }
    #si la bdd inaccessible ou que la requête échoue on renvoie une erreur 500
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"erreur de bdd : {str(e)}")
