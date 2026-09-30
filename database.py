import psycopg2
from psycopg2.extras import RealDictCursor 

#config de la connexion postegreSQL (local ou DO)
DB_CONFIG = {
    "host": "localhost",
    "database": "postgres",
    "user": "postgres",
    "password": "password",
    "port": 5432
}

#fonction d'ouverture de connexion
def get_db_connection():
    """ouvre et renvoie une connexion à la bdd"""
    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    return conn
    
def init_db():
    """crée la table 'competitor_alerts' si elle n'existe pas encore"""
    create_table_query = """
    CREATE TABLE IF NOT EXISTS competito_alerts (
        id SERIAL PRIMARY KEY,
        competitor_name VARCHAR(100) NOT NULL,
        ad_title VARCHAR(255) NOT NULL,
        ad_url TEXT NOT NULL,
        price_detected FLOAT NOT NULL,
        source VARCHAR(50) DEFAULT 'apify_scraper',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    try : 
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(create_table_query)
        conn.commit()
        cursor.close()
        conn.close()
        print("Table 'competitor_alerts' initilaisée avec succès dans PostegreSQL")
    except Exception as e :
        print(f"Connexion Postres échouée : {e}")