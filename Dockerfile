# 1. Image de base officielle Python ultra-légère (Debian Slim)
FROM python:3.11-slim

# 2. Variables d'environnement système pour Python
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

# 3. Répertoire de travail dans le conteneur
WORKDIR /app

# 4. Copie et installation des dépendances (optimisation du cache Docker par calques)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copie de l'ensemble du code source du projet
COPY . .

# 6. Sécurité : Création d'un utilisateur non-root pour l'exécution
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# 7. Exposition du port (GCP Cloud Run utilise la variable PORT, 8080 par défaut)
EXPOSE 8080

# 8. Commande de lancement du serveur d'application Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]