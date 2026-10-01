"""
Módulo de Diagnóstico y Pruebas Individuales de Extracción.

Este módulo se encarga de:
1. Verificar aisladamente el inicio de sesión automático en la plataforma GIS.
2. Validar que la consulta SQL espacial funcione y retorne datos sin alterar Airtable.
3. Mostrar en la consola de comandos la cantidad de filas y una muestra del primer registro.
"""

import json
import requests
from bs4 import BeautifulSoup
from config import (
    GIS_BASE_URL, GIS_PASSWORD, GIS_USERNAME,
    LOGIN_URL, SQL_QUERY, SUPERSET_URL
)
from utils import generate_client_id


def test_weezie_connection():
    """ Probar el inicio de sesión automático y la extracción de datos de prueba.

    Verificar la conectividad con el servidor web, autenticar al usuario e imprimir los resultados de la extracción
    directamente en la consola para diagnosticar la consulta.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
    })

    print("Probando inicio de sesión automático...")

    try:
        # Obtener el formulario web de login para extraer el token CSRF inicial
        res_login_page = session.get(LOGIN_URL, timeout=15)
        if res_login_page.status_code != 200:
            print(f"Error al acceder a la página de login: {res_login_page.status_code}")
            return

        soup = BeautifulSoup(res_login_page.text, "html.parser")
        csrf_input = soup.find("input", {"id": "csrf_token"}) or soup.find("input", {"name": "csrf_token"})
        csrf_token = csrf_input["value"] if csrf_input else ""

        # Enviar credenciales vía POST
        login_data = {
            "username": GIS_USERNAME,
            "password": GIS_PASSWORD,
            "csrf_token": csrf_token
        }

        post_login = session.post(LOGIN_URL, data=login_data, timeout=15)

        if post_login.status_code not in [200, 302]:
            print(f"Autenticación fallida con código de respuesta: {post_login.status_code}")
            return

        print("Sesión establecida correctamente.\n")

    except Exception as e:
        print(f"Error durante el inicio de sesión: {e}")
        return

    # Construir el payload de consulta para Superset
    client_id = generate_client_id()
    payload = {
        "client_id": client_id,
        "database_id": 1,
        "json": True,
        "runAsync": False,
        "schema": "public",
        "sql": SQL_QUERY,
        "sql_editor_id": "158",
        "tab": "Prueba de Crecimiento Mensual",
        "tmp_table_name": "",
        "select_as_cta": False,
        "ctas_method": "TABLE",
        "queryLimit": 10000,
        "expand_data": True
    }

    csrf_cookie = session.cookies.get("csrf_token") or session.cookies.get("X-Csrftoken") or csrf_token

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "referer": f"{GIS_BASE_URL}/superset/sqllab",
        "x-csrftoken": csrf_cookie
    }

    print(f"Enviando consulta espacial de prueba (Client ID: {client_id})...")

    try:
        response = session.post(SUPERSET_URL, headers=headers, json=payload, timeout=600)

        if response.status_code == 200:
            respuesta_json = response.json()
            datos_extraidos = respuesta_json.get("data", [])

            print("\nConsulta finalizada con éxito.")
            print(f"Se extrajeron {len(datos_extraidos)} registros históricos.")

            if len(datos_extraidos) > 0:
                print("\nMuestra del primer registro obtenido:")
                print(json.dumps(datos_extraidos[0], indent=4, ensure_ascii=False))
            else:
                print("\nLa consulta devolvió HTTP 200 pero el conjunto de datos vino vacío.")
        else:
            print(f"\nError {response.status_code}: {response.text}")

    except requests.exceptions.Timeout:
        print("\nLa solicitud excedió el tiempo límite de respuesta (10 minutos).")
    except Exception as e:
        print(f"\nOcurrió un error inesperado: {e}")


if __name__ == "__main__":
    test_weezie_connection()