"""
Scraper Mejorado - Búsqueda con Selenium en múltiples fuentes colombianas
Busca automáticamente en: Páginas Amarillas, DuckDuckGo, Google
"""

import sqlite3
import logging
import time
import re
import os
from typing import Dict, Any, Optional, List
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from bs4 import BeautifulSoup
import requests

# Intentar importar psycopg2 para PostgreSQL
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except Exception:
    psycopg2 = None
    RealDictCursor = None

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AutomaticDataScraper:
    """Scraper automático que busca datos en múltiples fuentes"""
    
    def __init__(self, db_path: str = "appdb.sqlite", db_type: str = "sqlite",
                 db_host: str = "localhost", db_port: int = 5432,
                 db_name: str = "appdb", db_user: str = "postgres", 
                 db_password: str = "postgres"):
        self.db_path = db_path
        self.db_type = db_type
        self.db_host = db_host
        self.db_port = db_port
        self.db_name = db_name
        self.db_user = db_user
        self.db_password = db_password
        self.conn = None
        self.driver = None
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def get_browser(self):
        """Obtiene el driver del navegador disponible"""
        try:
            # En Docker, Firefox está disponible
            # Primero intentar Firefox (funciona en Docker)
            try:
                options = webdriver.FirefoxOptions()
                options.add_argument('--headless')
                options.add_argument('--no-sandbox')
                driver = webdriver.Firefox(options=options)
                logger.info("Firefox iniciado")
                return driver
            except:
                pass
            
            # Intentar Edge (local)
            try:
                options = webdriver.EdgeOptions()
                options.add_argument('--headless')
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-blink-features=AutomationControlled')
                driver = webdriver.Edge(options=options)
                logger.info("Edge iniciado")
                return driver
            except:
                pass
            
            # Intentar Chrome (local)
            try:
                options = ChromeOptions()
                options.add_argument('--headless')
                options.add_argument('--no-sandbox')
                driver = webdriver.Chrome(options=options)
                logger.info("Chrome iniciado")
                return driver
            except:
                pass
        
        except Exception as e:
            logger.warning(f"No se pudo iniciar navegador: {e}")
        
        return None
    
    def connect_db(self) -> bool:
        try:
            # Intentar PostgreSQL si psycopg2 está disponible
            if psycopg2 is not None and self.db_type == "postgres":
                try:
                    self.conn = psycopg2.connect(
                        host=self.db_host,
                        port=self.db_port,
                        database=self.db_name,
                        user=self.db_user,
                        password=self.db_password
                    )
                    logger.info("Conectado a PostgreSQL")
                    return True
                except Exception as e:
                    logger.warning(f"No se pudo conectar a PostgreSQL ({e}), usando SQLite...")
            
            # Fallback a SQLite
            db_path = os.getenv("APP_DB_PATH", self.db_path)
            self.conn = sqlite3.connect(db_path)
            self.conn.row_factory = sqlite3.Row
            logger.info("Conectado a SQLite")
            return True
        except Exception as e:
            logger.error(f"Error conectando a BD: {e}")
            return False
    
    def close_db(self):
        if self.conn:
            self.conn.close()
    
    def close_browser(self):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
    
    def extract_phone_from_text(self, text: str) -> Optional[str]:
        """Extrae teléfono del texto usando múltiples patrones robustos"""
        patterns = [
            r'\+57\s*[1-9]\s*[\d\s\-\(\)]{8,}',  # Números colombianos con +57
            r'\(?\d{1,3}\)?\s*[\d\s\-\(\)]{8,12}',  # Formato (1) 234-5678
            r'\d{3}[\s\-]?\d{3,4}[\s\-]?\d{4}',  # XXX-XXXX o XXX XXX XXXX
            r'\+\d{1,3}\s*\d{8,}',  # Cualquier número con +
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                phone = match.group(0).strip()
                digits = re.sub(r'\D', '', phone)
                if len(digits) >= 7:
                    return phone
        return None
    
    def extract_website_from_text(self, text: str) -> Optional[str]:
        """Extrae website del texto usando múltiples patrones"""
        patterns = [
            r'https?://[^\s\)<>]+',  # URLs completas
            r'www\.[^\s\)<>]+',  # URLs www
            r'[a-zA-Z0-9.-]+\.(com|co|net|org|gov|com\.co|edu|io)[^\s\)<>]*',  # Dominios
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                url = match.group(0).strip()
                if len(url) < 200 and not any(x in url.lower() for x in ['google', 'duckduckgo', 'facebook']):
                    return url
        return None
    
    def search_duckduckgo(self, empresa_nombre: str, ciudad: str) -> Optional[Dict]:
        """Busca en DuckDuckGo con fallback a regex"""
        if not self.driver:
            return None
        
        try:
            logger.info(f"   Buscando en DuckDuckGo: {empresa_nombre}")
            
            query = f"{empresa_nombre} {ciudad} telefono contacto"
            url = f"https://duckduckgo.com/?q={query}&ia=web"
            
            self.driver.set_page_load_timeout(15)
            self.driver.get(url)
            time.sleep(3)
            
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            page_text = soup.get_text()
            
            results = {'phone': None, 'website': None}
            snippets = soup.find_all('span', {'data-result': 'snippet'})
            
            for snippet in snippets[:3]:
                text = snippet.get_text(strip=True)
                if not results['phone']:
                    phone = self.extract_phone_from_text(text)
                    if phone:
                        results['phone'] = phone
                        logger.info(f"      -> Teléfono: {results['phone']}")
                if not results['website']:
                    website = self.extract_website_from_text(text)
                    if website:
                        results['website'] = website
                        logger.info(f"      -> Website: {results['website']}")
            
            if not results['phone']:
                phone = self.extract_phone_from_text(page_text)
                if phone:
                    results['phone'] = phone
                    logger.info(f"      -> Teléfono (regex): {results['phone']}")
            
            return results if any(results.values()) else None
        
        except Exception as e:
            logger.warning(f"   Error DuckDuckGo: {str(e)[:50]}")
            return None
    
    
    def search_google_web(self, empresa_nombre: str, ciudad: str) -> Optional[Dict]:
        """Búsqueda robusta en Google usando requests (sin Selenium)"""
        try:
            logger.info(f"   Buscando en Google Web: {empresa_nombre}")
            
            query = f"{empresa_nombre} {ciudad} telefono contacto site:.co"
            url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code != 200:
                return None
            
            soup = BeautifulSoup(response.text, 'html.parser')
            text = soup.get_text()
            
            results = {'phone': None, 'website': None}
            
            phone = self.extract_phone_from_text(text)
            if phone:
                results['phone'] = phone
                logger.info(f"      -> Teléfono: {phone}")
            
            website = self.extract_website_from_text(text)
            if website:
                results['website'] = website
                logger.info(f"      -> Website: {website}")
            
            return results if any(results.values()) else None
        
        except Exception as e:
            logger.warning(f"   Error Google Web: {str(e)[:50]}")
            return None
    
    def search_local_directory(self, empresa_nombre: str, ciudad: str) -> Optional[Dict]:
        """Busca en directorios locales como Páginas Amarillas"""
        if not self.driver:
            return None
        
        try:
            logger.info(f"   Buscando en directorios: {empresa_nombre}")
            
            search_url = f"https://www.paginasamarillas.com.co/search?q={empresa_nombre}"
            
            self.driver.set_page_load_timeout(15)
            self.driver.get(search_url)
            
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_all_elements_located((By.CLASS_NAME, "listing"))
                )
            except:
                pass
            
            time.sleep(2)
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            page_text = soup.get_text()
            
            results = {'phone': None, 'website': None, 'address': None}
            
            # Buscar teléfonos en enlaces tel:
            phone_links = soup.find_all('a', href=re.compile(r'^tel:'))
            if phone_links:
                phone = phone_links[0].get('href', '').replace('tel:', '').strip()
                if phone:
                    results['phone'] = phone
                    logger.info(f"      -> Teléfono: {phone}")
            
            # Si no encontró por selector, buscar en todo el texto
            if not results['phone']:
                phone = self.extract_phone_from_text(page_text)
                if phone:
                    results['phone'] = phone
                    logger.info(f"      -> Teléfono (regex): {phone}")
            
            # Buscar dirección
            address_elem = soup.find('span', class_='address')
            if address_elem:
                address = address_elem.get_text(strip=True)
                if address:
                    results['address'] = address
                    logger.info(f"      -> Dirección: {address[:40]}")
            
            return results if any(results.values()) else None
        
        except Exception as e:
            logger.warning(f"   Error directorios: {str(e)[:50]}")
            return None
    
    def search_google_maps(self, empresa_nombre: str, ciudad: str) -> Optional[Dict]:
        """Busca en Google Maps con fallback robusta a regex"""
        if not self.driver:
            return None
        
        try:
            logger.info(f"   Buscando en Google Maps: {empresa_nombre}")
            
            search_query = f"{empresa_nombre} {ciudad}"
            url = f"https://www.google.com/maps/search/{search_query.replace(' ', '+')}"
            
            self.driver.set_page_load_timeout(15)
            self.driver.get(url)
            
            time.sleep(4)
            
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            page_text = soup.get_text()
            
            results = {'phone': None, 'website': None, 'address': None}
            
            # Buscar teléfono: primero por selector, luego fallback a regex
            phone = None
            phone_elem = soup.find('a', href=re.compile(r'^tel:'))
            if phone_elem:
                phone = phone_elem.get('href', '').replace('tel:', '').strip()
            
            if not phone:
                phone = self.extract_phone_from_text(page_text)
            
            if phone:
                results['phone'] = phone
                logger.info(f"      -> Teléfono: {results['phone']}")
            
            # Buscar dirección: primero por selectores de Maps, luego por texto
            address = None
            address_selectors = [
                'button[data-item-id="address"]',
                'div[data-item-id="address"]',
                'a[data-item-id="address"]',
                'button[aria-label*="Address"]',
                'div[aria-label*="Address"]',
                'button[aria-label*="Dirección"]',
                'div[aria-label*="Dirección"]',
            ]
            for selector in address_selectors:
                address_elem = soup.select_one(selector)
                if address_elem:
                    address = address_elem.get_text(" ", strip=True) or address_elem.get('aria-label', '').strip()
                    if address:
                        break
            
            if not address:
                for line in page_text.split('\n'):
                    line = line.strip()
                    if any(word in line.lower() for word in ['calle', 'carrera', 'avenida', 'av.', 'cra.', 'cll.', 'cl.', 'diag', 'transversal', '#']):
                        if 10 < len(line) < 100:
                            address = line
                            break
            
            if address:
                results['address'] = address
                logger.info(f"      -> Dirección: {address[:40]}")
            
            # Buscar website: primero por selector, luego fallback a regex
            website = None
            website_links = soup.find_all('a', {'data-attrid': 'website'})
            if website_links:
                website = website_links[0].get('href', '')
            
            if not website:
                website = self.extract_website_from_text(page_text)
            
            if website:
                results['website'] = website
                logger.info(f"      -> Website: {website[:40]}")
            
            return results if any(results.values()) else None
        
        except Exception as e:
            logger.warning(f"   Error Google Maps: {str(e)[:50]}")
            return None

    def _extract_address_from_text(self, text: str) -> Optional[str]:
        """Intenta identificar una dirección colombiana desde texto libre."""
        if not text:
            return None

        address_keywords = ['calle', 'carrera', 'avenida', 'av.', 'cra.', 'cl.', 'cll.', 'diagonal', 'diag.', 'transversal', 'km ', '#']
        for raw_line in text.split('\n'):
            line = raw_line.strip()
            if 10 <= len(line) <= 120 and any(keyword in line.lower() for keyword in address_keywords):
                return line
        return None
    
    def scrape_company(self, company_id: int, company_name: str, city: str) -> Optional[Dict[str, Any]]:
        """Extrae datos de una empresa buscando en múltiples fuentes"""
        
        print(f"\n[Scraping] {company_name} ({city})")
        
        results = {
            'phone': None,
            'website': None,
            'address': None,
            'sources': [],
            'status': 'partial'
        }
        
        try:
            # Estrategia: buscar en orden de confiabilidad
            sources = [
                ('google_maps', self.search_google_maps),
                ('google_web', self.search_google_web),
                ('duckduckgo', self.search_duckduckgo),
                ('paginas_amarillas', self.search_local_directory),
            ]
            
            for source_name, search_func in sources:
                try:
                    data = search_func(company_name, city)
                    if data:
                        for key, value in data.items():
                            if value and not results[key]:
                                results[key] = value
                        results['sources'].append(source_name)
                    time.sleep(2)
                except:
                    pass
                
                # Si ya tenemos teléfono, no buscar más
                if results['phone']:
                    break
        
        except Exception as e:
            logger.error(f"Error scraping {company_name}: {e}")
        
        # Determinar estado
        if results['phone'] or results['website'] or results['address']:
            results['status'] = 'completed' if results['phone'] else 'partial'
        
        logger.info(f"   -> Estado: {results['status']} | Fuentes: {', '.join(results['sources'])}")
        
        return results
    
    def get_pending_companies(self, limit: int = 50) -> List:
        """Obtiene empresas sin detalles"""
        try:
            # Crear cursor: usar RealDictCursor en psycopg2 para obtener diccionarios
            if psycopg2 is not None and isinstance(self.conn, psycopg2.extensions.connection) and RealDictCursor is not None:
                cursor = self.conn.cursor(cursor_factory=RealDictCursor)
            else:
                cursor = self.conn.cursor()

            # Query para PostgreSQL y SQLite (usar placeholders adecuados)
            if psycopg2 is not None and isinstance(self.conn, psycopg2.extensions.connection):
                query = """
                    SELECT c.id, c.name, c.city, c.nit
                    FROM companies c
                    LEFT JOIN company_details cd ON c.id = cd.company_id
                    WHERE c.is_active = true
                    AND (cd.id IS NULL 
                         OR cd.phone = 'N/A' 
                         OR cd.phone IS NULL)
                    ORDER BY c.name
                    LIMIT %s
                """
                cursor.execute(query, (limit,))
            else:
                query = """
                    SELECT c.id, c.name, c.city, c.nit
                    FROM companies c
                    LEFT JOIN company_details cd ON c.id = cd.company_id
                    WHERE c.is_active = 1
                    AND (cd.id IS NULL 
                         OR cd.phone = 'N/A' 
                         OR cd.phone IS NULL)
                    ORDER BY c.name
                    LIMIT ?
                """
                cursor.execute(query, (limit,))
            
            results = cursor.fetchall()
            logger.info(f"Encontradas {len(results)} empresas para procesar")
            return results
        
        except Exception as e:
            logger.error(f"Error: {e}")
            return []
    
    def save_details(self, company_id: int, details: Dict[str, Any]) -> bool:
        """Guarda detalles en BD (PostgreSQL o SQLite)"""
        try:
            cursor = self.conn.cursor()
            
            if not any([details.get('phone'), details.get('website'), details.get('address')]):
                logger.warning("   No hay datos para guardar")
                return False
            
            # Usar INSERT ON CONFLICT para PostgreSQL, INSERT OR REPLACE para SQLite
            if psycopg2 and isinstance(self.conn, psycopg2.extensions.connection):
                # PostgreSQL
                cursor.execute("""
                    INSERT INTO company_details 
                    (company_id, phone, website, address, scraped_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (company_id) 
                    DO UPDATE SET 
                        phone = EXCLUDED.phone,
                        website = EXCLUDED.website,
                        address = EXCLUDED.address,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    company_id,
                    details.get('phone') or 'N/A',
                    details.get('website') or 'N/A',
                    details.get('address') or 'N/A',
                    datetime.now().isoformat()
                ))
            else:
                # SQLite
                cursor.execute("""
                    INSERT OR REPLACE INTO company_details 
                    (company_id, phone, website, address, scraped_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    company_id,
                    details.get('phone') or 'N/A',
                    details.get('website') or 'N/A',
                    details.get('address') or 'N/A',
                    datetime.now().isoformat()
                ))
            
            self.conn.commit()
            logger.info("   ✓ Datos guardados en BD")
            return True
        
        except Exception as e:
            logger.error(f"   Error guardando: {e}")
            return False
    
    def process_companies(self, limit: int = 10) -> Dict[str, Any]:
        """Procesa todas las empresas"""
        
        if not self.connect_db():
            return {'success': False, 'error': 'No se pudo conectar a BD'}
        
        # Iniciar navegador
        self.driver = self.get_browser()
        if not self.driver:
            logger.warning("Continuando sin navegador (requests only)")
        
        companies = self.get_pending_companies(limit)
        
        if not companies:
            self.close_db()
            self.close_browser()
            return {
                'success': True,
                'total': 0,
                'processed': 0,
                'message': 'Todas las empresas tienen detalles'
            }
        
        logger.info("\n" + "="*80)
        logger.info(f"SCRAPER AUTOMÁTICO - Procesando {len(companies)} empresas")
        logger.info("="*80 + "\n")
        
        successful = 0
        
        try:
            for i, company in enumerate(companies, 1):
                try:
                    print(f"\n[{i}/{len(companies)}] {company['name']}")
                    print(f"      NIT: {company['nit']} | Ciudad: {company['city']}")
                    
                    details = self.scrape_company(
                        company['id'],
                        company['name'],
                        company['city']
                    )
                    
                    if details and self.save_details(company['id'], details):
                        successful += 1
                
                except Exception as e:
                    logger.error(f"Error procesando: {e}")
                
                time.sleep(2)
        
        finally:
            self.close_db()
            self.close_browser()
        
        logger.info("\n" + "="*80)
        logger.info(f"COMPLETADO: {successful} de {len(companies)} empresas enriquecidas")
        logger.info("="*80)
        
        return {
            'success': True,
            'total': len(companies),
            'processed': successful,
            'message': f'{successful} de {len(companies)} empresas enriquecidas'
        }


def main():
    print("\n" + "="*80)
    print("SCRAPER AUTOMÁTICO MEJORADO")
    print("Búsqueda multi-fuente: Google Maps + DuckDuckGo + Páginas Amarillas")
    print("="*80)
    
    # Configurar BD desde variables de entorno
    db_type = "postgres" if psycopg2 is not None else "sqlite"
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = int(os.getenv("DB_PORT", "5432"))
    db_name = os.getenv("DB_NAME", "appdb")
    db_user = os.getenv("DB_USER", "postgres")
    db_password = os.getenv("DB_PASSWORD", "postgres")
    db_path = os.getenv("APP_DB_PATH", "appdb.sqlite")
    
    scraper = AutomaticDataScraper(
        db_path=db_path,
        db_type=db_type,
        db_host=db_host,
        db_port=db_port,
        db_name=db_name,
        db_user=db_user,
        db_password=db_password
    )
    result = scraper.process_companies(limit=10)
    
    print("\n" + "="*80)
    print("RESULTADO FINAL")
    print("="*80)
    print(f"Total procesadas: {result['total']}")
    print(f"Exitosas: {result['processed']}")
    print(f"Mensaje: {result['message']}")
    print()


if __name__ == "__main__":
    main()
