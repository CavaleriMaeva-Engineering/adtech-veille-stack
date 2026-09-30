import sqlite3

#fonction d'ouverture de connexion
def get_db_connection():
    conn = sqlite3.connect("adtech_alerts.db")
    conn.row_factory = sqlite3.Row  #permet d'accéder aux colonnes par leur nom
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
        print("Table 'competitor_alerts' initilaisée avec succès")
    except Exception as e :
        print(f"Connexion Postres échouée : {e}")