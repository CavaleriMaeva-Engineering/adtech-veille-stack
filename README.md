# AdTech Competitive Intelligence Pipeline & Cloud System Design

> **Système automatisé de veille concurrentielle et d'alerte prix en temps réel.**  
> *Projet développé dans le cadre de la préparation à l'entretien technique AI & Cloud Data Engineering chez **fifty-five**.*

---

## Aperçu du Projet

Ce projet met en œuvre un pipeline de traitement d'événements de bout en bout pour la veille AdTech / E-commerce. Le système détecte les variations de prix et annonces des concurrents, valide la conformité des données transmises, persiste les alertes en base de données relationnelle et notifie instantanément les équipes via Slack.

Le projet est structuré en deux volets :
1. **Projet A (Stack Locale - Code du Dépôt)** : Implémentation fonctionnelle locale avec FastAPI, Pydantic (`CompetitorAlert`), SQLite/PostgreSQL (`adtech_alerts.db`), n8n (Docker) et Webhooks Slack.
2. **Projet B (System Design GCP - Architecture Cible)** : Spécifications d'une architecture d'entreprise résiliente et serverless sur Google Cloud Platform (Cloud Run, Pub/Sub, Cloud SQL, BigQuery) pour la défense en entretien d'architecture.

---

## Architecture Système

### 1. Prototype Local (Projet A - Implémentation dans ce Dépôt)
```text
[ Webhook / Scraper ] 
       │
       ▼
[ n8n Workflow (Docker) ] ──(HTTP POST)──► [ FastAPI + Pydantic ]
                                                  │
                                       ┌──────────┴──────────┐
                                       ▼                     ▼
                                [ SQLite / Postgres ]   [ Slack Alert ]
                                     (OLTP)               (Webhook)
```

### 2. Target Enterprise GCP (Projet B - System Design Cible)
```text
[ Scraper / Event ]
       │
       ▼
[ GCP Pub/Sub ] ──(Push/Buffer)──► [ GCP Cloud Run (FastAPI) ]
(Message Broker)                           │
                                  ┌────────┴────────┐
                                  ▼                 ▼
                            [ GCP Cloud SQL ]   [ BigQuery ] ──► [ Slack ]
                             (OLTP Storage)    (OLAP Analytics)
```

---

## Stack Technique

| Composant | Stack Locale (Code Repo) | Stack Cible (GCP Prod) | Rôle |
| :--- | :--- | :--- | :--- |
| **Orchestration / Ingestion** | n8n (Docker) | GCP Pub/Sub + Cloud Functions | Ingestion événementielle et découplage |
| **Backend & Validation** | FastAPI + Pydantic v2 | GCP Cloud Run | Contrôle strict des contrats JSON & API REST |
| **Conteneurisation** | Docker (`Dockerfile`) | GCP Artifact Registry + Cloud Run | Isolation et déploiement serverless |
| **Base Transactionnelle** | SQLite (`adtech_alerts.db`) / PostgreSQL | GCP Cloud SQL | Stockage OLTP temps réel des alertes |
| **Entrepôt Analytique** | - | GCP BigQuery | Analyse statistique OLAP long terme |
| **Notification** | Slack Incoming Webhook | Slack Incoming Webhook | Alerting temps réel |

---

## Structure du Répertoire

```text
.
├── main.py            # API FastAPI (routes /health, /api/v1/alerts + contrat Pydantic)
├── database.py        # Gestion de la connexion SQL et initialisation BDD (init_db)
├── adtech_alerts.db   # Base de données SQLite locale générée automatiquement
├── Dockerfile         # Configuration de conteneurisation Cloud-ready pour FastAPI
├── requirements.txt   # Dépendances Python isolées
├── .env.example       # Modèle des variables d'environnement
├── .gitignore         # Exclusion des fichiers temporaires, venv, .env, DB
└── README.md          # Documentation du projet
```

---

## Modèle de Données & Contrat Pydantic

L'API garantit le principe de **Fail-Fast** : tout payload non conforme est rejeté avec un code **HTTP 422 Unprocessable Content** en < 1ms.

```python
from pydantic import BaseModel, Field, HttpUrl

class CompetitorAlert(BaseModel):
    competitor_name: str = Field(..., description="Nom du concurrent")
    ad_title: str = Field(..., description="Titre de la publicité ou du produit")
    ad_url: HttpUrl = Field(..., description="URL de l'annonce")
    price_detected: float = Field(..., gt=0, description="Prix détecté (doit être >0)")
    source: str = Field(default="apify_scraper", description="Origine de la donnée")
```

---

## Guide d'Installation & Lancement Local

### 1. Prérequis
* Python 3.11+
* Docker Desktop
* Un espace de travail Slack (pour les notifications)

### 2. Configuration de l'environnement Python
```bash
# Cloner le projet
git clone https://github.com/votre-compte/adtech-veille-stack.git
cd adtech-veille-stack

# Créer et activer l'environnement virtuel
python3 -m venv venv
source venv/bin/activate  # Sur macOS/Linux

# Installer les dépendances
pip install -r requirements.txt
```

### 3. Variables d'environnement
Créer un fichier `.env` basé sur `.env.example` :
```env
PORT=8001
DATABASE_URL=sqlite:///./adtech_alerts.db
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

### 4. Lancement de l'API
```bash
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```
* Documentation Swagger UI : `http://localhost:8001/docs`
* Route de Santé : `http://localhost:8001/health`

### 5. Exécution via Docker
```bash
# Builder l'image Docker
docker build -t adtech-api:latest .

# Lancer le conteneur
docker run -d -p 8001:8001 --env-file .env adtech-api:latest
```

---

## System Design & Transposition GCP (Projet B)

Dans une architecture d'entreprise, cette stack locale est transposée sur Google Cloud Platform :

1. **Découplage Asynchrone (Pub/Sub)** : Remplace l'appel direct HTTP pour servir de **tampon (buffer)**. Si l'API subit une maintenance, Pub/Sub conserve les événements sans aucune perte de données.
2. **Calcul Serverless (Cloud Run)** : Héberge le conteneur Docker FastAPI avec un auto-scaling automatique de 0 à $N$ instances (facturation à l'exécution réelle).
3. **Séparation OLTP / OLAP** :
   * **Cloud SQL (PostgreSQL)** : Base transactionnelle pour l'écriture temps réel des alertes par l'API.
   * **BigQuery** : Entrepôt de données analytique orienté colonnes pour l'analyse historique des tendances de prix.
4. **Gestion des Secrets (Secret Manager)** : Injection sécurisée des clés d'API et URLs Webhooks au démarrage des conteneurs Cloud Run sans stocker aucun secret dans le code.

---

## Auteur & Contexte
* **Développeuse** : Maéva
* **Contexte** : Préparation à un stage AI & Data Engineering 
