from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import os
import logging
import sqlite3
import time
from scraper_la_republica import EmpresasLaRepublicaScraper
from scraper_automatico import AutomaticDataScraper
from datetime import datetime

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Crear app FastAPI
app = FastAPI(
    title="Scraper La República API",
    description="API para scrapear empresas de empresas.larepublica.co",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Modelos Pydantic
class SearchRequest(BaseModel):
    """Modelo para solicitar búsqueda de empresas"""
    niche: str
    pages: int = 1
    description: Optional[str] = None

class CompanyResponse(BaseModel):
    """Modelo para respuesta de empresa"""
    id: Optional[int]
    name: str
    url: str
    rues: str
    city: str
    is_active: bool
    status: str
    company_size: str
    search_niche: str
    scraped_at: Optional[str]

class SearchResponse(BaseModel):
    """Modelo para respuesta de búsqueda"""
    success: bool
    niche: str
    total_companies: int
    message: str
    companies: Optional[List[dict]]

# Inicializar scraper
def get_scraper():
    """Factory para crear instancias del scraper"""
    return EmpresasLaRepublicaScraper(
        db_host=os.getenv("DB_HOST", "localhost"),
        db_port=int(os.getenv("DB_PORT", "5432")),
        db_name=os.getenv("DB_NAME", "appdb"),
        db_user=os.getenv("DB_USER", "postgres"),
        db_password=os.getenv("DB_PASSWORD", "postgres"),
        headless=True
    )


def get_db_connection():
    """Obtiene la conexión a la misma BD que usa el scraper principal."""
    return get_scraper().get_db_connection()

# Health check
@app.get("/health", tags=["Health"])
async def health_check():
    """Verifica que la API esté disponible"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    }

# Endpoints de scraping
@app.post("/api/search", response_model=SearchResponse, tags=["Search"])
async def search_companies(request: SearchRequest):
    """
    Busca empresas por nicho en empresas.larepublica.co
    
    Args:
        niche: Término de búsqueda (ej: "veterinarias", "restaurantes")
        pages: Número de páginas a scrapear (default: 1)
    
    Returns:
        SearchResponse con empresas encontradas
    """
    if not request.niche or len(request.niche.strip()) < 2:
        raise HTTPException(status_code=400, detail="El nicho debe tener al menos 2 caracteres")
    
    if request.pages < 1 or request.pages > 10:
        raise HTTPException(status_code=400, detail="El número de páginas debe estar entre 1 y 10")
    
    try:
        scraper = get_scraper()
        logger.info(f"Iniciando búsqueda para nicho: {request.niche}, páginas: {request.pages}")
        
        result = scraper.scrape_and_save(request.niche, request.pages)
        
        return SearchResponse(
            success=result["success"],
            niche=result["niche"],
            total_companies=result["total_companies"],
            message=result["message"],
            companies=result.get("companies", [])
        )
    
    except Exception as e:
        logger.error(f"Error en búsqueda: {e}")
        raise HTTPException(status_code=500, detail=f"Error durante el scrape: {str(e)}")

@app.get("/api/companies/{niche}", tags=["Companies"])
async def get_companies_by_niche(niche: str, limit: int = 100):
    """
    Obtiene empresas guardadas para un nicho específico
    
    Args:
        niche: Nicho a consultar
        limit: Número máximo de resultados
    
    Returns:
        Lista de empresas
    """
    try:
        scraper = get_scraper()
        companies = scraper.get_companies_by_niche(niche)
        
        # Limitar resultados
        companies = companies[:limit]
        
        return {
            "success": True,
            "niche": niche,
            "total": len(companies),
            "companies": companies
        }
    
    except Exception as e:
        logger.error(f"Error obteniendo empresas: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.post("/api/search-async", tags=["Search"])
async def search_companies_async(request: SearchRequest, background_tasks: BackgroundTasks):
    """
    Inicia una búsqueda asincrónica en background
    Ideal para búsquedas largas que no bloqueen la respuesta
    
    Args:
        niche: Término de búsqueda
        pages: Número de páginas a scrapear
    
    Returns:
        Confirmación del inicio de la búsqueda
    """
    if not request.niche or len(request.niche.strip()) < 2:
        raise HTTPException(status_code=400, detail="El nicho debe tener al menos 2 caracteres")
    
    if request.pages < 1 or request.pages > 10:
        raise HTTPException(status_code=400, detail="El número de páginas debe estar entre 1 y 10")
    
    try:
        scraper = get_scraper()
        
        # Agregar tarea al background
        background_tasks.add_task(scraper.scrape_and_save, request.niche, request.pages)
        
        return {
            "success": True,
            "message": f"Búsqueda de '{request.niche}' iniciada en background",
            "niche": request.niche,
            "status": "processing"
        }
    
    except Exception as e:
        logger.error(f"Error iniciando búsqueda async: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.get("/api/stats", tags=["Statistics"])
async def get_statistics():
    """
    Obtiene estadísticas generales del scraper
    """
    try:
        scraper = get_scraper()
        conn = scraper.get_db_connection()
        
        if not conn:
            raise HTTPException(status_code=500, detail="No se pudo conectar a la base de datos")
        
        cur = conn.cursor()
        
        # Total de empresas
        cur.execute("SELECT COUNT(*) FROM companies;")
        total_companies = cur.fetchone()[0]
        
        # Empresas por nicho
        cur.execute("""
            SELECT search_niche, COUNT(*) as count 
            FROM companies 
            GROUP BY search_niche 
            ORDER BY count DESC;
        """)
        companies_by_niche = [{"niche": row[0], "count": row[1]} for row in cur.fetchall()]
        
        # Empresas activas vs inactivas
        cur.execute("""
            SELECT is_active, COUNT(*) 
            FROM companies 
            GROUP BY is_active;
        """)
        status_stats = {row[0]: row[1] for row in cur.fetchall()}
        
        cur.close()
        conn.close()
        
        return {
            "total_companies": total_companies,
            "companies_by_niche": companies_by_niche,
            "active_companies": status_stats.get(True, 0),
            "inactive_companies": status_stats.get(False, 0)
        }
    
    except Exception as e:
        logger.error(f"Error obteniendo estadísticas: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# ==================== NUEVOS ENDPOINTS: GOOGLE MAPS ENRICHMENT ====================

@app.get("/api/companies-with-details", tags=["Companies"])
async def get_companies_with_details(niche: str = "veterinarias"):
    """
    Obtiene empresas CON detalles de Google Maps
    (Opción 2: Búsqueda Combinada)
    
    Retorna:
    - Nombre, NIT, ciudad
    - Teléfono, website, dirección (del scraper de Google Maps)
    
    Args:
        niche: Nicho a filtrar (default: veterinarias)
    
    Returns:
        Lista de empresas con detalles completos
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        is_sqlite = isinstance(conn, sqlite3.Connection)
        placeholder = "?" if is_sqlite else "%s"
        active_filter = "c.is_active = 1" if is_sqlite else "c.is_active IS TRUE"
        
        # Query: Obtener empresas CON sus detalles
        cursor.execute(f"""
            SELECT 
                c.id,
                c.name,
                c.nit,
                c.city,
                c.is_active,
                c.status,
                c.company_size,
                cd.phone,
                cd.website,
                cd.address,
                cd.scraped_at
            FROM companies c
            LEFT JOIN company_details cd ON c.id = cd.company_id
                        WHERE c.search_niche = {placeholder}
                            AND {active_filter}
                            AND c.name IS NOT NULL
                            AND c.name != 'N/A'
            ORDER BY c.name
                """, (niche,))
        
        companies = []
        for row in cursor.fetchall():
            companies.append({
                "id": row[0],
                "name": row[1],
                "nit": row[2],
                "city": row[3],
                "status": row[5],
                "company_size": row[6],
                "phone": row[7] if row[7] and row[7] != "N/A" else None,
                "website": row[8] if row[8] and row[8] != "N/A" else None,
                "address": row[9] if row[9] and row[9] != "N/A" else None,
                "details_updated_at": row[10]
            })
        
        conn.close()
        
        # Contar con detalles completos
        with_details = sum(1 for c in companies if c["phone"] or c["website"] or c["address"])
        without_details = len(companies) - with_details
        
        return {
            "success": True,
            "niche": niche,
            "total": len(companies),
            "with_details": with_details,
            "without_details": without_details,
            "companies": companies
        }
    
    except Exception as e:
        logger.error(f"Error obteniendo empresas con detalles: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.get("/api/companies/{company_id}/details", tags=["Companies"])
async def get_company_details(company_id: int):
    """
    Obtiene detalles de Google Maps de una empresa específica
    
    Args:
        company_id: ID de la empresa
    
    Returns:
        Detalles completos: teléfono, website, dirección, etc.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                c.id,
                c.name,
                c.nit,
                c.city,
                c.url,
                cd.phone,
                cd.website,
                cd.address,
                cd.latitude,
                cd.longitude,
                cd.scraped_at
            FROM companies c
            LEFT JOIN company_details cd ON c.id = cd.company_id
            WHERE c.id = ?
        """, (company_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            raise HTTPException(status_code=404, detail="Empresa no encontrada")
        
        return {
            "success": True,
            "company": {
                "id": row[0],
                "name": row[1],
                "nit": row[2],
                "city": row[3],
                "url_larepublica": row[4],
                "google_maps": {
                    "phone": row[5] if row[5] and row[5] != "N/A" else None,
                    "website": row[6] if row[6] and row[6] != "N/A" else None,
                    "address": row[7] if row[7] and row[7] != "N/A" else None,
                    "latitude": row[8],
                    "longitude": row[9],
                    "scraped_at": row[10]
                }
            }
        }
    
    except Exception as e:
        logger.error(f"Error obteniendo detalles: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# ==================== SCRAPER AUTOMÁTICO ====================

@app.post("/api/scraper/enrich-automatic", tags=["Scraper"])
async def enrich_companies_automatic(background_tasks: BackgroundTasks, limit: int = 10):
    """
    Ejecuta enriquecimiento automático en background
    Busca datos faltantes en Google Maps, DuckDuckGo, Páginas Amarillas
    
    Ideal para:
    - Completar datos de teléfono, website, dirección
    - Procesamiento automático sin intervención manual
    - Ejecución en background sin bloquear la API
    
    Args:
        limit: Número de empresas a procesar (default: 10)
    
    Returns:
        ID de tarea en background + estadísticas iniciales
    """
    try:
        def run_scraper():
            """Ejecuta el scraper en background"""
            try:
                logger.info(f"Iniciando enriquecimiento automático: {limit} empresas")
                scraper = AutomaticDataScraper()
                result = scraper.process_companies(limit=limit)
                logger.info(f"Enriquecimiento completado: {result}")
            except Exception as e:
                logger.error(f"Error en enriquecimiento automático: {e}")
        
        # Agregar tarea al background
        background_tasks.add_task(run_scraper)
        
        # Obtener estadísticas actuales
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM companies")
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM company_details 
            WHERE phone != 'N/A' AND phone IS NOT NULL
        """)
        with_phone = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM company_details 
            WHERE website != 'N/A' AND website IS NOT NULL
        """)
        with_website = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "success": True,
            "message": f"Enriquecimiento de {limit} empresas iniciado en background",
            "status": "processing",
            "current_stats": {
                "total_companies": total,
                "with_phone": with_phone,
                "with_website": with_website,
                "coverage_phone": f"{(with_phone/total*100):.1f}%" if total > 0 else "0%",
                "coverage_website": f"{(with_website/total*100):.1f}%" if total > 0 else "0%"
            }
        }
    
    except Exception as e:
        logger.error(f"Error iniciando enriquecimiento: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.get("/api/scraper/status", tags=["Scraper"])
async def scraper_status():
    """
    Obtiene estado actual del scraper
    Muestra estadísticas de enriquecimiento
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM companies")
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM company_details 
            WHERE phone != 'N/A' AND phone IS NOT NULL
        """)
        with_phone = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM company_details 
            WHERE website != 'N/A' AND website IS NOT NULL
        """)
        with_website = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM company_details 
            WHERE address != 'N/A' AND address IS NOT NULL
        """)
        with_address = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT search_niche, COUNT(*) as count 
            FROM companies 
            GROUP BY search_niche
        """)
        by_niche = {row[0]: row[1] for row in cursor.fetchall()}
        
        conn.close()
        
        return {
            "success": True,
            "status": "operational",
            "statistics": {
                "total_companies": total,
                "enriched": {
                    "phone": with_phone,
                    "website": with_website,
                    "address": with_address
                },
                "coverage": {
                    "phone": f"{(with_phone/total*100):.1f}%" if total > 0 else "0%",
                    "website": f"{(with_website/total*100):.1f}%" if total > 0 else "0%",
                    "address": f"{(with_address/total*100):.1f}%" if total > 0 else "0%"
                },
                "companies_by_niche": by_niche
            }
        }
    
    except Exception as e:
        logger.error(f"Error obteniendo estado: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# Inicialización
@app.on_event("startup")
async def startup_event():
    """Evento al iniciar la aplicación"""
    logger.info("🚀 Aplicación iniciada")
    scraper = get_scraper()
    scraper.create_tables()
    logger.info("✅ Tablas de base de datos verificadas/creadas")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
