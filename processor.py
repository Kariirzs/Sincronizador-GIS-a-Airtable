"""
Módulo del Motor Procesador: Autenticación, Extracción y Sincronización.

Este módulo se encarga de:
1. Autenticar dinámicamente la sesión de usuario en la plataforma GIS capturando tokens CSRF.
2. Ejecutar la consulta analítica PostGIS y extraer los datos en modo solo lectura.
3. Consultar la estructura de registros existentes en la tabla destino de Airtable.
4. Sincronizar de forma incremental aplicando comparaciones de firmas MD5 (Sync-on-Change)
    para realizar únicamente operaciones necesarias (Altas, Bajas y Cambios) en Airtable.
"""

import json
import os
import requests
import time
from bs4 import BeautifulSoup
from config import (
    AIRTABLE_HEADERS, AIRTABLE_URL, GIS_BASE_URL, GIS_PASSWORD,
    GIS_USERNAME, LOGIN_URL, SQL_QUERY, SUPERSET_URL
)
from utils import build_custom_id, calculate_row_hash, generate_client_id

# Archivo de persistencia local para almacenar la memoria de firmas MD5 entre ejecuciones
CACHE_FILE = "cache_state.json"


def get_authenticated_session() -> tuple[requests.Session, str]:
    """ Iniciar sesión automáticamente en la plataforma GIS y retornar la sesión HTTP activa.

    Navegar a la página de login, inspeccionar el HTML para extraer el token CSRF inicial, enviar las credenciales del
    usuario y conservar las cookies de sesión resultantes.

    :return: Tupla con la sesión HTTP autenticada y el token CSRF obtenido.
    :raises Exception: Si ocurre un fallo en el acceso web o las credenciales son rechazadas.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
    })

    print("Autenticando en la plataforma GIS...")

    # Realizar petición GET inicial para obtener el token CSRF del formulario
    res_login_page = session.get(LOGIN_URL, timeout=15)
    if res_login_page.status_code != 200:
        raise Exception(f"Error al acceder a la página de inicio de sesión: {res_login_page.status_code}")

    # Parsear el contenido HTML para extraer el token oculto en el formulario
    soup = BeautifulSoup(res_login_page.text, "html.parser")
    csrf_input = soup.find("input", {"id": "csrf_token"}) or soup.find("input", {"name": "csrf_token"})
    csrf_token = csrf_input["value"] if csrf_input else ""

    # Enviar datos de autenticación vía POST
    login_data = {
        "username": GIS_USERNAME,
        "password": GIS_PASSWORD,
        "csrf_token": csrf_token
    }

    post_login = session.post(LOGIN_URL, data=login_data, timeout=15)
    if post_login.status_code not in [200, 302]:
        raise Exception("Error de autenticación. Verifique las credenciales en el archivo de configuración.")

    print("Autenticación completada con éxito.")
    return session, csrf_token


def extract_from_weezie() -> list:
    """ Ejecutar la consulta espacial y retornar la lista de datos crudos.

    Invocación del endpoint REST de Superset adjuntando las cabeceras de autorización y el payload estructurado para
    procesar la consulta en el motor de base de datos PostGIS.

    :return: Lista de diccionarios con el resultado de la consulta analítica.
    :raises Exception: Si la respuesta HTTP devuelve un código de error.
    """
    session, csrf_token = get_authenticated_session()
    client_id = generate_client_id()

    payload = {
        "client_id": client_id,
        "database_id": 1,
        "json": True,
        "runAsync": False,
        "schema": "public",
        "sql": SQL_QUERY,
        "sql_editor_id": "158",
        "tab": "Crecimiento de Red Mensual (Análisis Espacial)",
        "tmp_table_name": "",
        "select_as_cta": False,
        "ctas_method": "TABLE",
        "queryLimit": 10000,
        "expand_data": True
    }

    # Asignar la cookie de seguridad CSRF resultante de la sesión autenticada
    csrf_cookie = session.cookies.get("csrf_token") or session.cookies.get("X-Csrftoken") or csrf_token

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "referer": f"{GIS_BASE_URL}/superset/sqllab",
        "x-csrftoken": csrf_cookie
    }

    print(f"Extrayendo reporte de crecimiento espacial (Client ID: {client_id})...")
    response = session.post(SUPERSET_URL, headers=headers, json=payload, timeout=600)

    if response.status_code == 200:
        data = response.json().get("data", [])
        print(f"Extracción exitosa: {len(data)} registros obtenidos.")
        return data
    else:
        raise Exception(f"Error durante la extracción ({response.status_code}): {response.text}")


def fetch_current_airtable_records() -> dict:
    """ Obtener el listado de identificadores guardados en la tabla de Airtable.

    Recorrer paginadamente la API de Airtable para construir una relación entre el identificador personalizado de negocio
    y el ID de registro interno de Airtable (rec...)

    :return: Diccionario con la estructura { custom_id: record_id_airtable }.
    :raises Exception: Si ocurre una falla
    """
    print("Consultando registros actuales en Airtable...")
    existing = {}
    offset = None

    # Iterar iterativamente mediante el cursor offset hasta agotar los registros
    while True:
        params = {"pageSize": 100, "fields[]": ["ID"]}
        if offset:
            params["offset"] = offset

        res = requests.get(AIRTABLE_URL, headers=AIRTABLE_HEADERS, params=params)
        if res.status_code != 200:
            raise Exception(f"Error al consultar la API de Airtable: {res.text}")

        data = res.json()
        for rec in data.get("records", []):
            custom_id = rec.get("fields", {}).get("ID")
            if custom_id:
                existing[custom_id] = rec["id"]

        offset = data.get("offset")
        if not offset:
            break

    print(f"Se encontraron {len(existing)} registros en la tabla destino.")
    return existing


def sync_to_airtable_with_hash(raw_data: list):
    """ Sincronizar incrementalmente los datos en Airtable aplicando la técnica Sync-on-Change con MD5.

    1. Cargar el estado previo guardado en la memoria local (cache_state.json).
    2. Comparar el hash MD5 de cada fila procesada contra la memoria registrada.
    3. Clasificar los registros en lotes de Inserción, Actualización o Eliminación.
    4. Enviar peticiones a Airtable en bloques de 10 habilitando typecast para auto-crear selecciones.
    5. Actualizar el archivo de estado local con los nuevos hashes procesados.

    :param raw_data: Lista de registros extraídos de la fuente de origen.
    """
    # Cargar el diccionario de firmas desde el caché local si el archivo existe
    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    airtable_existing = fetch_current_airtable_records()

    to_create = []
    to_update = []
    current_ids_set = set()
    new_cache = {}

    # Evaluar línea por línea los registros extraídos
    for row in raw_data:
        custom_id = build_custom_id(row)
        current_ids_set.add(custom_id)

        fields = {
            "ID": custom_id,
            "Mes": row.get("mes"),
            "Año": row.get("anio"),
            "Gestión": row.get("gestion"),
            "Estado": row.get("estado"),
            "Tipo de Red": row.get("tipo_de_red"),
            "Capacidad": row.get("capacidad"),
            "Km Mensuales": row.get("km_mensuales"),
            "Acumulado Historico": row.get("acumulado_historico")
        }

        # Calcular la firma digital de la fila actual
        row_hash = calculate_row_hash(fields)
        new_cache[custom_id] = row_hash

        # Clasificar la acción requerida según la existencia e integridad del registro
        if custom_id not in airtable_existing:
            to_create.append({"fields": fields})
        elif cache.get(custom_id) != row_hash:
            rec_id = airtable_existing[custom_id]
            to_update.append({"id": rec_id, "fields": fields})

    # Identificar registros que fueron borrados de la fuente de origen
    to_delete = [rec_id for cid, rec_id in airtable_existing.items() if cid not in current_ids_set]

    # Prevenir recuentos negativos en las métricas durante ejecuciones iniciales
    unchanged_count = len(current_ids_set) - len(to_create) - len(to_update)
    if unchanged_count < 0:
        unchanged_count = 0

    print(f"\nRESUMEN DEL PROCESAMIENTO:")
    print(f"Nuevos a crear: {len(to_create)}")
    print(f"Modificados a actualizar: {len(to_update)}")
    print(f"Obsoletos a eliminar: {len(to_delete)}")
    print(f"Sin cambios (Omitidos): {unchanged_count}")

    # Enviar inserciones en lotes de 10 habilitando typecast para auto-crear etiquetas
    for i in range(0, len(to_create), 10):
        batch = to_create[i:i + 10]
        payload = {"records": batch, "typecast": True}
        res = requests.post(AIRTABLE_URL, headers=AIRTABLE_HEADERS, json=payload)
        if res.status_code != 200:
            raise Exception(f"Error al crear registros en Airtable: {res.text}")
        time.sleep(0.2)

    # Enviar modificaciones en lotes de 10
    for i in range(0, len(to_update), 10):
        batch = to_update[i:i + 10]
        payload = {"records": batch, "typecast": True}
        res = requests.patch(AIRTABLE_URL, headers=AIRTABLE_HEADERS, json=payload)
        if res.status_code != 200:
            raise Exception(f"Error al actualizar registros en Airtable: {res.text}")
        time.sleep(0.2)

    # Enviar solicitudes de eliminación en lotes de 10
    for i in range(0, len(to_delete), 10):
        batch = to_delete[i:i + 10]
        res = requests.delete(AIRTABLE_URL, headers=AIRTABLE_HEADERS, params={"records[]": batch})
        if res.status_code != 200:
            raise Exception(f"Error al eliminar registros obsoletos en Airtable: {res.text}")
        time.sleep(0.2)

    # Persistir el nuevo estado de firmas MD5 en el disco local
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(new_cache, f, indent=2)

    print("\n¡Sincronización completada con éxito!")