"""
Demo: Consultar empresas CON detalles de Google Maps desde BD
"""

import sqlite3
import json
import os
from datetime import datetime

try:
    import psycopg2
except Exception:
    psycopg2 = None


def get_db_connection():
    """Abre la misma BD que usa el flujo principal, preferentemente PostgreSQL."""
    if psycopg2 is not None:
        try:
            return psycopg2.connect(
                host=os.getenv("DB_HOST", "localhost"),
                port=int(os.getenv("DB_PORT", "5432")),
                database=os.getenv("DB_NAME", "appdb"),
                user=os.getenv("DB_USER", "postgres"),
                password=os.getenv("DB_PASSWORD", "postgres"),
            )
        except Exception:
            pass

    db_path = os.getenv("APP_DB_PATH", "appdb.sqlite")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def mostrar_empresas_con_detalles():
    """Muestra empresas con detalles de Google Maps"""
    
    print("\n" + "="*100)
    print("OPCION 2: EMPRESAS CON DETALLES DE GOOGLE MAPS (BUSQUEDA COMBINADA)")
    print("="*100 + "\n")
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        is_sqlite = isinstance(conn, sqlite3.Connection)
        active_filter = "c.is_active = 1" if is_sqlite else "c.is_active IS TRUE"
        
        # Query: Obtener empresas CON sus detalles
        cursor.execute(f"""
            SELECT 
                c.id,
                c.name,
                c.nit,
                c.city,
                c.status,
                c.company_size,
                cd.phone,
                cd.website,
                cd.address,
                cd.scraped_at
            FROM companies c
            LEFT JOIN company_details cd ON c.id = cd.company_id
                        WHERE {active_filter}
                            AND c.name IS NOT NULL
                            AND c.name != 'N/A'
            ORDER BY c.name
                """)
        
        rows = cursor.fetchall()

        if is_sqlite:
            companies = [dict(row) for row in rows]
        else:
            columns = [desc[0] for desc in cursor.description]
            companies = [dict(zip(columns, row)) for row in rows]
        
        if not companies:
            print("No hay empresas en la BD")
            return
        
        # Mostrar en tabla
        print("TABLA DE EMPRESAS CON DETALLES")
        print("-"*100)
        print("{:<45} {:<15} {:<25} {:<15}".format(
            "NOMBRE", "CIUDAD", "TELEFONO", "WEBSITE"
        ))
        print("-"*100)
        
        for company in companies:
            nombre = (company.get('name') or 'N/A')[:44]
            ciudad = (company.get('city') or 'N/A')[:14]
            telefono = (company.get('phone') or "N/A")[:14]
            website_value = company.get('website')
            website = (website_value or "N/A")[:24] if website_value else "N/A"
            
            print("{:<45} {:<15} {:<25} {:<15}".format(
                nombre, ciudad, telefono, website
            ))
        
        # Estadisticas
        print("\n" + "="*100)
        print("ESTADISTICAS")
        print("="*100 + "\n")
        
        total = len(companies)
        con_telefono = sum(1 for c in companies if c.get('phone') and c.get('phone') != 'N/A')
        con_website = sum(1 for c in companies if c.get('website') and c.get('website') != 'N/A')
        con_direccion = sum(1 for c in companies if c.get('address') and c.get('address') != 'N/A')
        
        print("Total de empresas: {}".format(total))
        print("\nDatos disponibles:")
        print("  - Con teléfono: {} ({:.1f}%)".format(con_telefono, (con_telefono/total)*100))
        print("  - Con website: {} ({:.1f}%)".format(con_website, (con_website/total)*100))
        print("  - Con dirección: {} ({:.1f}%)".format(con_direccion, (con_direccion/total)*100))
        
        # Detalle por empresa
        print("\n" + "="*100)
        print("DETALLE POR EMPRESA")
        print("="*100 + "\n")
        
        for i, company in enumerate(companies, 1):
            print("[{}] {}".format(i, company.get('name') or 'N/A'))
            print("    NIT: {} | Ciudad: {} | Estado: {}".format(
                company.get('nit'), company.get('city'), company.get('status')
            ))
            print("    Teléfono: {}".format(company.get('phone') or "N/A"))
            print("    Website: {}".format(company.get('website') or "N/A"))
            print("    Dirección: {}".format((company.get('address') or "N/A")[:60]))
            
            if company.get('scraped_at'):
                print("    Actualizado: {}".format(str(company.get('scraped_at'))[:19]))
            print()
        
        # Exportar JSON
        print("="*100)
        print("EXPORTAR COMO JSON")
        print("="*100 + "\n")
        
        data_export = []
        for company in companies:
            data_export.append({
                "id": company.get('id'),
                "nombre": company.get('name'),
                "nit": company.get('nit'),
                "ciudad": company.get('city'),
                "estado": company.get('status'),
                "tamaño": company.get('company_size'),
                "contacto": {
                    "telefono": company.get('phone') if company.get('phone') and company.get('phone') != 'N/A' else None,
                    "website": company.get('website') if company.get('website') and company.get('website') != 'N/A' else None,
                    "direccion": company.get('address') if company.get('address') and company.get('address') != 'N/A' else None
                },
                "actualizado": company.get('scraped_at')
            })
        
        # Guardar JSON
        with open('empresas_con_detalles.json', 'w', encoding='utf-8') as f:
            json.dump(data_export, f, ensure_ascii=False, indent=2)
        
        print("Archivo guardado: empresas_con_detalles.json")
        print("Puedes usar este JSON en tu frontend")
        
        # Mostrar API endpoints disponibles
        print("\n" + "="*100)
        print("PROXIMOS PASOS: USAR LA API")
        print("="*100 + "\n")
        
        print("1. Inicia la API:")
        print("   python -m uvicorn main:app --reload")
        
        print("\n2. Accede a los endpoints:")
        print("   - GET http://localhost:8000/api/companies-with-details?niche=veterinarias")
        print("     -> Devuelve todas las empresas CON detalles de Google Maps")
        
        print("\n   - GET http://localhost:8000/api/companies/1/details")
        print("     -> Devuelve detalles específicos de empresa ID 1")
        
        print("\n3. Documentación interactiva:")
        print("   - http://localhost:8000/docs")
        print("   - Prueba los endpoints directamente desde el navegador")
        
        print("\n" + "="*100)
        print("DATOS LISTOS PARA USAR EN FRONTEND")
        print("="*100 + "\n")
        
        conn.close()
        
    except Exception as e:
        print("ERROR: {}".format(e))
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    mostrar_empresas_con_detalles()
