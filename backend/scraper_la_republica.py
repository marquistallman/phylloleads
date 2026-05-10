from bs4 import BeautifulSoup
import re
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.edge.options import Options as EdgeOptions
try:
    import psycopg2
    from psycopg2.extras import execute_values
except Exception:
    psycopg2 = None
    execute_values = None
import sqlite3
import time
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
import os

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EmpresasLaRepublicaScraper:
    """
    Scraper para empresas.larepublica.co
    Busca empresas por nicho y extrae información: nombre, RUES, ciudad, tamaño
    """
    
    BASE_URL = "https://empresas.larepublica.co"
    SEARCH_URL = f"{BASE_URL}/buscar"
    
    def __init__(
        self,
        db_host: str = "localhost",
        db_port: int = 5432,
        db_name: str = "appdb",
        db_user: str = "postgres",
        db_password: str = "postgres",
        headless: bool = True
    ):
        """
        Inicializa el scraper con parámetros de conexión a base de datos
        
        Args:
            db_host: Host de PostgreSQL
            db_port: Puerto de PostgreSQL
            db_name: Nombre de la base de datos
            db_user: Usuario de PostgreSQL
            db_password: Contraseña de PostgreSQL
            headless: Si True, Selenium corre sin interfaz gráfica
        """
        self.db_host = db_host
        self.db_port = db_port
        self.db_name = db_name
        self.db_user = db_user
        self.db_password = db_password
        self.headless = headless
        self.driver = None
        # Debug HTML saving
        self.debug_save_html = False
        self.debug_dir = Path('backend/debug')
        self._debug_saved_files = []
    
    
    def _close_driver(self):
        """Cierra el driver de Selenium"""
        if self.driver:
            self.driver.quit()
            logger.info("Driver cerrado")

    def _init_driver(self):
        """Inicializa el driver de Selenium (Firefox primero, luego Chrome/Edge)"""
        # Intentar Firefox
        try:
            firefox_options = FirefoxOptions()
            if self.headless:
                firefox_options.add_argument("--headless")
            firefox_options.add_argument("--no-sandbox")
            firefox_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            self.driver = webdriver.Firefox(options=firefox_options)
            logger.info("Driver de Firefox inicializado")
            return
        except Exception as e:
            logger.debug(f"Firefox no disponible: {e}")

        # Intentar Chrome
        try:
            chrome_options = ChromeOptions()
            if self.headless:
                chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            self.driver = webdriver.Chrome(options=chrome_options)
            logger.info("Driver de Chrome inicializado")
            return
        except Exception as e:
            logger.debug(f"Chrome no disponible: {e}")

        # Intentar Edge
        try:
            edge_options = EdgeOptions()
            if self.headless:
                edge_options.add_argument("--headless")
            edge_options.add_argument("--no-sandbox")
            edge_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            self.driver = webdriver.Edge(options=edge_options)
            logger.info("Driver de Edge inicializado")
            return
        except Exception as e:
            logger.error(f"No se pudo inicializar ningún navegador: {e}")
            raise Exception("No hay navegador disponible (Firefox, Chrome o Edge)")
    
    def search_niche(self, niche: str, pages: int = 1, max_load_more: int = 0) -> List[Dict[str, Any]]:
        """
        Busca empresas por nicho y extrae los links de resultados
        """
        if not self.driver:
            self._init_driver()

        # Soporte para 'load more' (botón) en lugar de paginación tradicional
        all_companies = []
        seen_urls = set()
        initial_pages = 1 if max_load_more > 0 else pages

        try:
            for page in range(1, initial_pages + 1):
                logger.info(f"Scrapeando página {page} para nicho: {niche}")
                # Construir URL con búsqueda (sitio usa /buscar?term=...)
                url = f"{self.SEARCH_URL}?term={niche}&page={page}"
                logger.debug(f"Cargando URL de búsqueda: {url}")
                # Cargar página
                self.driver.get(url)
                
                # Esperar brevemente a que cargue algo de contenido, pero no romper si timeout
                try:
                    WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.TAG_NAME, "a"))
                    )
                except Exception:
                    logger.debug("No se detectó el elemento esperado antes del timeout; proceder a parsear HTML")

                # Dar tiempo adicional para scroll y carga dinámica
                time.sleep(2)

                # Parsear HTML
                soup = BeautifulSoup(self.driver.page_source, 'html.parser')

                # Guardar HTML para debug si está activado
                if self.debug_save_html:
                    try:
                        self.debug_dir.mkdir(parents=True, exist_ok=True)
                        fname = f"{niche}_page{page}_{int(time.time())}.html"
                        fpath = self.debug_dir / fname
                        with open(fpath, 'w', encoding='utf-8') as fh:
                            fh.write(soup.prettify())
                        self._debug_saved_files.append(str(fpath))
                        logger.info(f"Guardado HTML debug: {fpath}")
                    except Exception as e:
                        logger.warning(f"No se pudo guardar HTML de debug: {e}")

                # Intentar extracción por selector conocido
                result_items = soup.find_all('a', class_='result-item') or []

                # Fallback robusto: buscar anchors cuyo href coincida con patrón típico de empresa
                if not result_items:
                    anchors = soup.find_all('a', href=True)
                    candidates = []
                    # patrón: /colombia/.../nombre-empresa-<digitos> (NIT al final)
                    pattern = re.compile(r'^/colombia/.+-\d{5,}$')
                    for a in anchors:
                        href = a.get('href', '')
                        if pattern.search(href):
                            candidates.append(a)
                    result_items = candidates

                # Fallback adicional: anchors que contienen un <h3 class="company-name"> o cualquier <h3>
                if not result_items:
                    anchors_h3 = []
                    for a in soup.find_all('a', href=True):
                        # Priorizar h3 con clase company-name
                        if a.find('h3', class_='company-name'):
                            anchors_h3.append(a)
                            continue
                        # Si contiene cualquier h3 con texto, considerarlo candidato
                        h3 = a.find('h3')
                        if h3 and h3.get_text(strip=True):
                            anchors_h3.append(a)
                    if anchors_h3:
                        result_items = anchors_h3

                # Fallback adicional: buscar contenedores tipo result/card/article que incluyan un anchor
                if not result_items:
                    container_candidates = []
                    try:
                        containers = soup.find_all(['div', 'article', 'section'], class_=re.compile('result|item|card|listing', re.I))
                        for c in containers:
                            a = c.find('a', href=True)
                            if a:
                                container_candidates.append(a)
                    except Exception:
                        container_candidates = []
                    if container_candidates:
                        result_items = container_candidates

                # Último recurso: anchors que apunten a /colombia/ (sin requerir NIT numérico)
                if not result_items:
                    anchors_general = []
                    for a in soup.find_all('a', href=True):
                        href = a.get('href', '')
                        if href.startswith('/colombia/'):
                            anchors_general.append(a)
                    result_items = anchors_general

                logger.info(f"Encontradas {len(result_items)} empresas en página {page}")

                for item in result_items:
                    try:
                        href = item.get('href', '')
                        full_url = f"{self.BASE_URL}{href}" if href.startswith('/') else href
                        if full_url in seen_urls:
                            continue
                        company_data = self._parse_company_item(item)
                        if company_data:
                            all_companies.append(company_data)
                            seen_urls.add(company_data.get('url'))
                    except Exception as e:
                        logger.error(f"Error parseando empresa: {e}")
                        continue

                # Si se indicó que hay botón "mostrar más" intentar clics
                if max_load_more > 0:
                    clicked = 0
                    for i in range(max_load_more):
                        try:
                            # Buscar botones comunes que cargan más resultados
                            xpath_variants = [
                                "//button[contains(normalize-space(.), 'Ver más resultados') ]",
                                "//button[contains(normalize-space(.), 'Mostrar más') ]",
                                "//button[contains(normalize-space(.), 'Cargar más') ]",
                                "//button[contains(@class, 'load-more') or contains(@class, 'btn-more')]"
                            ]
                            btn = None
                            for xp in xpath_variants:
                                try:
                                    btn = WebDriverWait(self.driver, 3).until(
                                        EC.element_to_be_clickable((By.XPATH, xp))
                                    )
                                    if btn:
                                        break
                                except Exception:
                                    btn = None
                            if not btn:
                                logger.info("No se encontró botón 'mostrar más' adicional")
                                break

                            # Click y esperar que cargue nuevos resultados
                            try:
                                btn.click()
                            except Exception:
                                # Fallback: usar JavaScript click
                                try:
                                    self.driver.execute_script("arguments[0].click();", btn)
                                except Exception as e:
                                    logger.debug(f"No se pudo clickear botón: {e}")
                                    break

                            time.sleep(2)
                            # Reparsear HTML y extraer nuevos anchors
                            soup = BeautifulSoup(self.driver.page_source, 'html.parser')

                            anchors = soup.find_all('a', href=True)
                            new_candidates = []
                            for a in anchors:
                                href = a.get('href', '')
                                full_url = f"{self.BASE_URL}{href}" if href.startswith('/') else href
                                if full_url not in seen_urls:
                                    # reuse earlier selection logic to pick candidate anchors
                                    if a.find('h3', class_='company-name') or href.startswith('/colombia/'):
                                        new_candidates.append(a)

                            logger.info(f"Encontradas {len(new_candidates)} nuevas empresas tras click {i+1}")
                            for item in new_candidates:
                                try:
                                    company_data = self._parse_company_item(item)
                                    if company_data and company_data.get('url') not in seen_urls:
                                        all_companies.append(company_data)
                                        seen_urls.add(company_data.get('url'))
                                except Exception as e:
                                    logger.debug(f"Error parseando empresa post-click: {e}")

                            clicked += 1
                        except Exception as e:
                            logger.debug(f"Error en bucle de 'load more': {e}")
                            break

                    logger.info(f"Clicks de 'mostrar más' realizados: {clicked}")
                
                # Respetar el servidor
                time.sleep(1)
        
        except Exception as e:
            logger.error(f"Error en búsqueda: {e}")
        finally:
            # Cerrar driver
            self._close_driver()
            # Borrar archivos debug guardados si corresponde
            if self.debug_save_html and self._debug_saved_files:
                for fp in self._debug_saved_files:
                    try:
                        if os.path.exists(fp):
                            os.remove(fp)
                            logger.info(f"Archivo debug eliminado: {fp}")
                    except Exception as e:
                        logger.debug(f"No se pudo eliminar archivo debug {fp}: {e}")

        logger.info(f"Total de empresas extraídas: {len(all_companies)}")
        return all_companies
    
    def _parse_company_item(self, item) -> Optional[Dict[str, Any]]:
        """
        Parsea un elemento de resultado de empresa
        
        Args:
            item: Elemento BeautifulSoup del resultado
            
        Returns:
            Dict con datos de la empresa o None si hay error
        """
        try:
            # Extraer nombre
            name_tag = item.find('h3', class_='company-name')
            name = name_tag.get_text(strip=True) if name_tag else "N/A"
            
            # Extraer href para obtener el link
            href = item.get('href', '')
            full_url = f"{self.BASE_URL}{href}" if href.startswith('/') else href
            
            # Extraer NIT del href (última parte del URL)
            # Formato típico: /colombia/bolivar/cartagena/nombre-empresa-nit
            nit = self._extract_nit_from_url(href)
            
            # Extraer información adicional (puede estar en span o divs dentro del item)
            # La estructura puede variar, así que intentamos extraer múltiples campos
            
            # Información de RUES (número de identificación)
            rues_text = ""
            for span in item.find_all('span'):
                text = span.get_text(strip=True)
                if any(char.isdigit() for char in text) and len(text) > 5:
                    # Probable número de RUES/RUT
                    rues_text = text
                    break
            
            # Extraer ciudad/región del href o de otros campos
            # El href generalmente tiene formato: /colombia/bolivar/cartagena/...
            city = self._extract_city_from_url(href)
            
            # Extraer información de activa/inactiva y tamaño
            # Esto usualmente está en el texto del item o en atributos
            status_text = item.get_text(strip=True)
            is_active = "inactiva" not in status_text.lower()
            
            company_data = {
                "name": name,
                "url": full_url,
                "nit": nit,
                "rues": rues_text,
                "city": city,
                "is_active": is_active,
                "status": "Activa" if is_active else "Inactiva",
                "company_size": self._estimate_company_size(status_text),
                "search_niche": "",
                "scraped_at": datetime.now().isoformat(),
                "raw_html": str(item)
            }
            
            return company_data
        
        except Exception as e:
            logger.error(f"Error en _parse_company_item: {e}")
            return None
    
    def _extract_nit_from_url(self, url: str) -> str:
        """
        Extrae el NIT del URL
        Formato típico: /colombia/bolivar/cartagena/nombre-empresa-nit
        El NIT es la última parte después del último guion
        """
        try:
            # Obtener la última parte del URL
            last_part = url.split('/')[-1]
            # El NIT está al final después del último guion
            if '-' in last_part:
                nit = last_part.split('-')[-1]
                # Verificar que sea un número válido
                if nit.isdigit() and len(nit) >= 8:
                    return nit
            return "N/A"
        except:
            return "N/A"
    
    def _extract_city_from_url(self, url: str) -> str:
        """
        Extrae la ciudad del URL
        Formato típico: /colombia/bolivar/cartagena/nombre-empresa-nit
        """
        try:
            parts = url.split('/')
            # Formato esperado: ['', 'colombia', 'departamento', 'ciudad', 'nombre-nit']
            if len(parts) >= 4:
                return parts[3]  # Índice 3 es la ciudad
            return "N/A"
        except:
            return "N/A"
    
    def _estimate_company_size(self, text: str) -> str:
        """
        Intenta estimar el tamaño de la empresa basado en el texto
        Palabras clave: micro, pequeña, mediana, grande
        """
        text_lower = text.lower()
        
        if "grande" in text_lower or "corporación" in text_lower:
            return "Grande"
        elif "mediana" in text_lower or "empresa mediana" in text_lower:
            return "Mediana"
        elif "pequeña" in text_lower or "pyme" in text_lower:
            return "Pequeña"
        elif "micro" in text_lower or "autónomo" in text_lower:
            return "Micro"
        else:
            return "No especificado"
    
    def get_db_connection(self):
        """Obtiene conexión a la base de datos.

        Intenta PostgreSQL si `psycopg2` está disponible, si no, usa SQLite
        y la variable de entorno `APP_DB_PATH`.
        """
        # Intentar PostgreSQL si psycopg2 está disponible
        if psycopg2 is not None:
            try:
                conn = psycopg2.connect(
                    host=self.db_host,
                    port=self.db_port,
                    database=self.db_name,
                    user=self.db_user,
                    password=self.db_password,
                )
                return conn
            except Exception as e:
                logger.warning(f"No se pudo conectar a PostgreSQL ({e}), usando SQLite...")

        # Fallback a SQLite
        try:
            db_path = os.getenv("APP_DB_PATH", "appdb.sqlite")
            conn = sqlite3.connect(db_path)
            return conn
        except Exception as e:
            logger.error(f"Error conectando a SQLite: {e}")
            return None
    
    def create_tables(self):
        """Crea las tablas necesarias en la base de datos"""
        conn = self.get_db_connection()
        if not conn:
            logger.error("No se pudo conectar a la base de datos")
            return False
        
        try:
            cur = conn.cursor()

            # Detectar tipo de conexión para DDL compatible
            is_sqlite = isinstance(conn, sqlite3.Connection)

            if is_sqlite:
                # SQLite-compatible DDL
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS companies (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        url TEXT,
                        rues TEXT,
                        city TEXT,
                        is_active INTEGER DEFAULT 1,
                        status TEXT,
                        company_size TEXT,
                        search_niche TEXT,
                        scraped_at TEXT,
                        created_at TEXT DEFAULT (datetime('now')),
                        updated_at TEXT DEFAULT (datetime('now')),
                        UNIQUE(url)
                    );
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS search_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        niche TEXT NOT NULL,
                        total_companies INTEGER,
                        pages_scraped INTEGER,
                        started_at TEXT,
                        completed_at TEXT,
                        status TEXT
                    );
                """)
            else:
                # PostgreSQL-compatible DDL
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS companies (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(500) NOT NULL,
                        url VARCHAR(1000),
                        rues VARCHAR(100),
                        city VARCHAR(200),
                        is_active BOOLEAN DEFAULT true,
                        status VARCHAR(50),
                        company_size VARCHAR(50),
                        search_niche VARCHAR(200),
                        scraped_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(url)
                    );
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS search_logs (
                        id SERIAL PRIMARY KEY,
                        niche VARCHAR(200) NOT NULL,
                        total_companies INT,
                        pages_scraped INT,
                        started_at TIMESTAMP,
                        completed_at TIMESTAMP,
                        status VARCHAR(50)
                    );
                """)

            conn.commit()
            cur.close()
            logger.info("Tablas creadas/verificadas exitosamente")
            return True
        
        except Exception as e:
            logger.error(f"Error creando tablas: {e}")
            return False
        
        finally:
            conn.close()
    
    def save_companies(self, companies: List[Dict[str, Any]], niche: str) -> bool:
        """
        Guarda las empresas en la base de datos
        
        Args:
            companies: Lista de diccionarios con datos de empresas
            niche: Nicho buscado
            
        Returns:
            True si fue exitoso, False en caso contrario
        """
        if not companies:
            logger.warning("No hay empresas para guardar")
            return False
        
        conn = self.get_db_connection()
        if not conn:
            return False

        # Si psycopg2 está disponible y execute_values también, usar inserción masiva en Postgres
        if psycopg2 is not None and execute_values is not None:
            try:
                cur = conn.cursor()
                values = []
                for company in companies:
                    company["search_niche"] = niche
                    values.append((
                        company.get("name"),
                        company.get("url"),
                        company.get("rues"),
                        company.get("city"),
                        company.get("is_active"),
                        company.get("status"),
                        company.get("company_size"),
                        company.get("search_niche"),
                        company.get("scraped_at"),
                    ))

                query = """
                    INSERT INTO companies 
                    (name, url, rues, city, is_active, status, company_size, search_niche, scraped_at)
                    VALUES %s
                    ON CONFLICT (url) 
                    DO UPDATE SET 
                        name = EXCLUDED.name,
                        is_active = EXCLUDED.is_active,
                        status = EXCLUDED.status,
                        company_size = EXCLUDED.company_size,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING id;
                """

                execute_values(cur, query, values)
                conn.commit()
                affected_rows = cur.rowcount
                cur.close()
                logger.info(f"Guardadas/actualizadas {affected_rows} empresas (Postgres)")
                return True
            except Exception as e:
                logger.error(f"Error guardando empresas en Postgres: {e}")
                try:
                    conn.close()
                except:
                    pass
                return False

        # Fallback: SQLite (insertar una por una)
        try:
            cur = conn.cursor()
            for company in companies:
                company["search_niche"] = niche
                try:
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO companies
                        (name, url, rues, city, is_active, status, company_size, search_niche, scraped_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            company.get("name"),
                            company.get("url"),
                            company.get("rues"),
                            company.get("city"),
                            int(bool(company.get("is_active"))),
                            company.get("status"),
                            company.get("company_size"),
                            company.get("search_niche"),
                            company.get("scraped_at"),
                        ),
                    )
                    # Si ya existía, intentar actualizar
                    cur.execute(
                        """
                        UPDATE companies
                        SET name = ?, is_active = ?, status = ?, company_size = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE url = ?
                        """,
                        (
                            company.get("name"),
                            int(bool(company.get("is_active"))),
                            company.get("status"),
                            company.get("company_size"),
                            company.get("url"),
                        ),
                    )
                except Exception as e:
                    logger.warning(f"Error insertando/actualizando empresa {company.get('name')}: {e}")
                    continue

            conn.commit()
            cur.close()
            logger.info(f"Guardadas/actualizadas {len(companies)} empresas (SQLite)")
            try:
                conn.close()
            except:
                pass
            return True

        except Exception as e:
            logger.error(f"Error guardando empresas en SQLite: {e}")
            try:
                conn.close()
            except:
                pass
            return False
    
    def get_companies_by_niche(self, niche: str) -> List[Dict[str, Any]]:
        """
        Obtiene empresas guardadas por nicho
        
        Args:
            niche: Nicho a buscar
            
        Returns:
            Lista de diccionarios con datos de empresas
        """
        conn = self.get_db_connection()
        if not conn:
            return []
        
        try:
            cur = conn.cursor()
            is_sqlite = isinstance(conn, sqlite3.Connection)
            if is_sqlite:
                cur.execute("""
                    SELECT id, name, url, rues, city, is_active, status, company_size, scraped_at
                    FROM companies
                    WHERE search_niche = ?
                    ORDER BY scraped_at DESC
                    LIMIT 1000;
                """, (niche,))
            else:
                cur.execute("""
                    SELECT id, name, url, rues, city, is_active, status, company_size, scraped_at
                    FROM companies
                    WHERE search_niche = %s
                    ORDER BY scraped_at DESC
                    LIMIT 1000;
                """, (niche,))
            
            columns = [desc[0] for desc in cur.description]
            results = [dict(zip(columns, row)) for row in cur.fetchall()]
            cur.close()
            
            return results
        
        except Exception as e:
            logger.error(f"Error obteniendo empresas: {e}")
            return []
        
        finally:
            conn.close()
    
    def scrape_and_save(self, niche: str, pages: int = 1, max_load_more: int = 0) -> Dict[str, Any]:
        """
        Pipeline completo: scrape, parse y guarda en base de datos
        
        Args:
            niche: Término de búsqueda
            pages: Número de páginas a scrapear
            
        Returns:
            Dict con resultado de la operación
        """
        logger.info(f"Iniciando scrape para nicho: {niche}")
        
        # Crear tablas si no existen
        self.create_tables()
        
        # Buscar empresas (soporta botón 'mostrar más' con max_load_more)
        companies = self.search_niche(niche, pages, max_load_more=max_load_more)
        
        if not companies:
            logger.warning(f"No se encontraron empresas para {niche}")
            return {
                "success": False,
                "niche": niche,
                "total_companies": 0,
                "message": "No se encontraron resultados"
            }
        
        # Guardar en BD
        saved = self.save_companies(companies, niche)
        
        return {
            "success": saved,
            "niche": niche,
            "total_companies": len(companies),
            "companies": companies,
            "message": f"Scrape completado: {len(companies)} empresas"
        }


# Uso directo del script
if __name__ == "__main__":
    import sys
    
    # Configurar desde variables de entorno o argumentos
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = int(os.getenv("DB_PORT", "5432"))
    db_name = os.getenv("DB_NAME", "appdb")
    db_user = os.getenv("DB_USER", "postgres")
    db_password = os.getenv("DB_PASSWORD", "postgres")
    
    # Crear scraper - intentará PostgreSQL si psycopg2 está disponible
    scraper = EmpresasLaRepublicaScraper(
        db_host=db_host,
        db_port=db_port,
        db_name=db_name,
        db_user=db_user,
        db_password=db_password,
        headless=True
    )
    
    # Ejemplo de uso
    niche = sys.argv[1] if len(sys.argv) > 1 else "veterinarias"
    pages = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    max_load_more = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    result = scraper.scrape_and_save(niche, pages, max_load_more=max_load_more)
    print(f"\n✅ Resultado: {result}")
