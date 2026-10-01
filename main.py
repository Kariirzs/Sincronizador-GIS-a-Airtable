"""
Punto de Entrada Principal del Pipeline

Este módulo coordina el flujo secuencial completo del programa:
1. Iniciar el proceso de extracción de datos en la plataforma GIS.
2. Ejecutar la sincronización hacia Airtable mediante comparaciones de hashes MD5.
3. Manejar excepciones globales e informar el resultado final de la ejecución.
"""

import sys
from processor import extract_from_weezie, sync_to_airtable_with_hash


def run_pipeline():
    """ Ejecutar la secuencia principal del pipeline ETL.

    Llamar a los módulos de extracción y procesamiento dentro de un bloque seguro para capturar cualquier falla crítica
    y retornar los códigos de salida adecuados.
    """
    print("PIPELINE AUTOMÁTICO DE SINCRONIZACIÓN ESPACIAL GIS")
    try:
        # Extraer los datos espaciales desde la plataforma GIS en modo lectura
        data = extract_from_weezie()
        if not data:
            print("No se obtuvieron datos de la consulta. Proceso finalizado.")
            return

        # Sincronizar el resultado obtenido hacia Airtable usando hashing MD5
        sync_to_airtable_with_hash(data)

        print("\n¡PROCESO FINALIZADO CON ÉXITO TOTAL!")

    except Exception as e:
        print(f"\nERROR CRÍTICO: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run_pipeline()