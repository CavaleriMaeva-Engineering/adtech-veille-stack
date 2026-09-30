# 1. Image de base officielle Python ultra-légère
FROM python:3.11-slim

# 2. Définition du répertoire de travail dans le conteneur
WORKDIR /app

# 3. Copie du fichier de dépendances
COPY requirements.txt .

# 4. Installation des paquets Python
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copie de l'ensemble du code de l'application
COPY . .

# 6. Exposition du port (Cloud Run utilise généralement la variable PORT)
EXPOSE 8001

# 7. Commande de lancement de l'API avec Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]