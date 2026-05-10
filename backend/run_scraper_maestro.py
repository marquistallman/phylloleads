"""
SCRAPER MAESTRO - Automatiza todo el flujo
1. Extrae empresas de La República
2. Busca enriquecimiento automático
3. Genera reporte
"""

import subprocess
import sys
import sqlite3
import argparse
import os
from pathlib import Path
from datetime import datetime

try:
    import psycopg2
except Exception:
    psycopg2 = None


def cleanup_legacy_records(db_path=None):
    """Elimina registros heredados sin nombre útil para que no mezclen corridas viejas con nuevas."""
    conn = None
    try:
        if psycopg2 is not None:
            try:
                conn = psycopg2.connect(
                    host=os.getenv("DB_HOST", "localhost"),
                    port=int(os.getenv("DB_PORT", "5432")),
                    database=os.getenv("DB_NAME", "appdb"),
                    user=os.getenv("DB_USER", "postgres"),
                    password=os.getenv("DB_PASSWORD", "postgres"),
                )
            except Exception:
                conn = None

        if conn is None:
            if db_path is None:
                db_path = os.getenv("APP_DB_PATH", "appdb.sqlite")
            conn = sqlite3.connect(str(db_path))

        cursor = conn.cursor()
        if psycopg2 is not None and not isinstance(conn, sqlite3.Connection):
            cursor.execute("""
                DELETE FROM company_details cd
                USING companies c
                WHERE cd.company_id = c.id
                  AND (c.name IS NULL OR c.name = 'N/A' OR c.name = '');
            """)
            cursor.execute("""
                DELETE FROM companies
                WHERE name IS NULL OR name = 'N/A' OR name = '';
            """)
        else:
            cursor.execute("""
                DELETE FROM company_details
                WHERE company_id IN (
                    SELECT id FROM companies
                    WHERE name IS NULL OR name = 'N/A' OR name = ''
                );
            """)
            cursor.execute("""
                DELETE FROM companies
                WHERE name IS NULL OR name = 'N/A' OR name = '';
            """)

        conn.commit()
        cursor.close()
    except Exception as e:
        print(f"Aviso: no se pudo limpiar legado previo: {e}")
    finally:
        if conn:
            conn.close()


def print_section(title):
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def run_command(script_name, description, env=None, timeout=300):
    """Ejecuta un script y retorna si fue exitoso"""
    print_section(description)

    try:
        result = subprocess.run(
            [sys.executable, script_name],
            cwd=Path(__file__).parent,
            capture_output=False,
            env=env,
            timeout=timeout,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"❌ {script_name} tardó demasiado")
        return False
    except Exception as e:
        print(f"❌ Error ejecutando {script_name}: {e}")
        return False


def get_db_stats(db_path=None):
    """Obtiene estadísticas de BD; `db_path` puede venir por arg o por env APP_DB_PATH."""
    try:
        conn = None
        if psycopg2 is not None:
            try:
                conn = psycopg2.connect(
                    host=os.getenv("DB_HOST", "localhost"),
                    port=int(os.getenv("DB_PORT", "5432")),
                    database=os.getenv("DB_NAME", "appdb"),
                    user=os.getenv("DB_USER", "postgres"),
                    password=os.getenv("DB_PASSWORD", "postgres"),
                )
            except Exception:
                conn = None

        if conn is None:
            if db_path is None:
                db_path = os.getenv("APP_DB_PATH", "appdb.sqlite")
            conn = sqlite3.connect(str(db_path))

        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM companies WHERE name IS NOT NULL AND name != 'N/A'")
        total_companies = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT COUNT(*) FROM company_details cd
            JOIN companies c ON c.id = cd.company_id
            WHERE c.name IS NOT NULL AND c.name != 'N/A'
              AND cd.phone != 'N/A' AND cd.phone != ''
        """
        )
        with_phone = cursor.fetchone()[0]

        cursor.execute(
            """
                        SELECT COUNT(*) FROM company_details cd
                        JOIN companies c ON c.id = cd.company_id
                        WHERE c.name IS NOT NULL AND c.name != 'N/A'
                            AND cd.website != 'N/A' AND cd.website != ''
        """
        )
        with_website = cursor.fetchone()[0]

        cursor.execute(
            """
                        SELECT COUNT(*) FROM company_details cd
                        JOIN companies c ON c.id = cd.company_id
                        WHERE c.name IS NOT NULL AND c.name != 'N/A'
                            AND cd.address != 'N/A' AND cd.address != ''
        """
        )
        with_address = cursor.fetchone()[0]

        conn.close()

        return {
            'total': total_companies,
            'with_phone': with_phone,
            'with_website': with_website,
            'with_address': with_address,
            'phone_percent': (with_phone / total_companies * 100) if total_companies > 0 else 0,
            'website_percent': (with_website / total_companies * 100) if total_companies > 0 else 0,
            'address_percent': (with_address / total_companies * 100) if total_companies > 0 else 0,
        }
    except Exception as e:
        print(f"Error obteniendo estadísticas: {e}")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default="appdb.sqlite", help="Ruta a la BD (archivo sqlite)")
    parser.add_argument("--timeout", type=int, default=300, help="Timeout por script en segundos")
    parser.add_argument("--niches", default="veterinaria", help="Lista de nichos separados por comas")
    parser.add_argument("--max-load-more", type=int, default=3, help="Número de clicks 'mostrar más' por nicho")
    args = parser.parse_args()

    # Resolve DB path to absolute
    db_path = Path(args.db_path)
    if not db_path.is_absolute():
        db_path = (Path(__file__).parent / db_path).resolve()

    # Propagar por env para scripts hijos
    child_env = os.environ.copy()
    child_env["APP_DB_PATH"] = str(db_path)
    child_env.setdefault("DB_HOST", os.getenv("DB_HOST", "localhost"))
    child_env.setdefault("DB_PORT", os.getenv("DB_PORT", "5432"))
    child_env.setdefault("DB_NAME", os.getenv("DB_NAME", "appdb"))
    child_env.setdefault("DB_USER", os.getenv("DB_USER", "postgres"))
    child_env.setdefault("DB_PASSWORD", os.getenv("DB_PASSWORD", "postgres"))

    # Limpiar residuos de corridas previas antes de empezar
    cleanup_legacy_records(db_path)

    print("\n" + "█" * 80)
    print("█" + " " * 78 + "█")
    print("█" + "  PHYLLOLEADS - SCRAPER MAESTRO AUTOMATIZADO".center(78) + "█")
    print("█" + "  Extrae datos de La República + Enriquecimiento automático".center(78) + "█")
    print("█" + " " * 78 + "█")
    print("█" * 80)

    inicio = datetime.now()
    pasos_completados = []

    # PASO 1: Extraer de La República para cada nicho
    niches = [n.strip() for n in args.niches.split(',') if n.strip()]
    for niche in niches:
        desc = f"PASO 1: Extrayendo empresas de La República (nicho: {niche})"
        # Llamar al script con args: niche, pages=1, max_load_more
        cmd = [sys.executable, 'scraper_la_republica.py', niche, '1', str(args.max_load_more)]
        print_section(desc)
        try:
            r = subprocess.run(cmd, cwd=Path(__file__).parent, env=child_env, timeout=args.timeout)
            if r.returncode == 0:
                pasos_completados.append(f'✓ La República ({niche})')
            else:
                pasos_completados.append(f'✗ La República ({niche})')
        except Exception as e:
            print(f"❌ Error ejecutando scraper_la_republica para {niche}: {e}")
            pasos_completados.append(f'✗ La República ({niche})')

    # PASO 2: Scraper automático
    if run_command(
        'scraper_automatico.py',
        'PASO 2: Enriquecimiento automático (Google Maps + DuckDuckGo + Páginas Amarillas)',
        env=child_env,
        timeout=args.timeout,
    ):
        pasos_completados.append('✓ Enriquecimiento automático')
    else:
        pasos_completados.append('✗ Enriquecimiento automático')

    # PASO 3: Mostrar datos
    if run_command(
        'ver_empresas_con_detalles.py',
        'PASO 3: Mostrando datos finales',
        env=child_env,
        timeout=args.timeout,
    ):
        pasos_completados.append('✓ Datos mostrados')
    else:
        pasos_completados.append('✗ Datos mostrados')

    # ESTADÍSTICAS FINALES
    print_section("ESTADÍSTICAS FINALES")

    stats = get_db_stats(db_path)
    if stats:
        print(f"Total empresas en BD: {stats['total']}")
        print(f"  • Con teléfono: {stats['with_phone']} ({stats['phone_percent']:.1f}%)")
        print(f"  • Con website: {stats['with_website']} ({stats['website_percent']:.1f}%)")
        print(f"  • Con dirección: {stats['with_address']} ({stats['address_percent']:.1f}%)")

    # RESUMEN
    print_section("RESUMEN DE EJECUCIÓN")
    for paso in pasos_completados:
        print(f"  {paso}")

    duracion = (datetime.now() - inicio).total_seconds()
    print(f"\nTiempo total: {duracion:.1f} segundos")

    print("\n" + "=" * 80)
    print("✅ FLUJO COMPLETADO")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
