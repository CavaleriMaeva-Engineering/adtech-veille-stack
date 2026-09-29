from fastapi import FastAPI
from pydantic import BaseModel, Field, HttpUrl
from datetime import datetime

#instanciation de l'app FastAPI 
app = FastAPI(title="AdTech Competitor Intelligence API")

#définition du contrat de données (schéma pydantic)
class CompetitorAlert(BaseModel):
    competitor_name: str = Field(..., description="Nom du concurrent")
    ad_title: HttpUrl = Field(..., description="Titre de la publicité ou du produit")
    price_detected: float = Field(..., gt=0, description="Prix détecté (doit être >0)")
    source: str = Field(default="apify_scraper", description="Origine de la donnée")

#route de santé (healthcheck)
@app.get("/health") #si un client envoie une requête HTTP Get sur .../health on déclence la fonction
def health_check():
    return {"status": "ok", "timestamp":datetime.utcnow()}

#route post pour recevoir l'alerte
@app.post("/api/v1/alerts")
def receive_alert(alert: CompetitorAlert) :
    #pydantic a déjà validé le json entrant ici
    print(f"Alerte reçue pour {alert.competitor_name} - Prix: {alert.price_detected}€")
    return {
        "message":"Alerte de veille enregistrée avec succès",
        "data_received":alert.dict()
    }

