"""
Módulo de Configuración Global y Definición de Constantes del Sistema.

Este módulo se encarga de:
1. Cargar las variables de entorno desde el archivo local de configuración (.env).
2. Definir los puntos de enlace (endpoints) HTTP para la plataforma de mapas y BI de Superset.
3. Configurar las credenciales y URLs de destino para la API de Airtable.
4. Almacenar la consulta SQL espacial (PostGIS) para el cálculo de crecimiento de red.
"""

import os
from dotenv import load_dotenv

# Cargar las variables de entorno definidas en el archivo .env para evitar exponer credenciales
load_dotenv()

# CONFIGURACIÓN DE CONEXIÓN A LA PLATAFORMA GIS (APACHE SUPERSET)
# Configurar la URL base de la plataforma GIS y construir los endpoints de autenticación y consulta SQL
GIS_BASE_URL = os.getenv("GIS_BASE_URL", "https://bi.example-gis-platform.com")
GIS_USERNAME = os.getenv("GIS_USERNAME")
GIS_PASSWORD = os.getenv("GIS_PASSWORD")

# Definir el endpoint REST de Superset encargado de ejecutar consultas SQL de forma sincrónica
SUPERSET_URL = f"{GIS_BASE_URL}/superset/sql_json/"

# Definir la dirección web del formulario de inicio de sesión de la plataforma
LOGIN_URL = f"{GIS_BASE_URL}/login/"

# CONFIGURACIÓN DE CONEXIÓN A LA API DE AIRTABLE
# Utilizar identificadores inmutables de Base (app...) y Tabla (tbl...) para prevenir fallos por cambios de interfaz
AIRTABLE_TOKEN = os.getenv("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
AIRTABLE_TABLE_ID = os.getenv("AIRTABLE_TABLE_ID")

# Construir la URL del recurso REST en Airtable para la gestión de registros
AIRTABLE_URL = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_ID}"

# Configurar las cabeceras HTTP necesarias para autorizar las solicitudes mediante Bearer Token
AIRTABLE_HEADERS = {
    "Authorization": f"Bearer {AIRTABLE_TOKEN}",
    "Content-Type": "application/json"
}

# CONSULTA SQL DE ANÁLISIS ESPACIAL (POSTGIS)
# Ejecutar una consulta analítica sobre PostgreSQL/PostGIS para:
#   A) Unir las geometrías de cableado con los límites territoriales de las regiones administrativas.
#   B) Calcular la intersección geométrica y prorratear los kilómetros según el porcentaje de cruce territorial.
#   C) Generar una serie temporal mensual continua desde la fecha inicial hasta la actualidad.
#   D) Calcular el acumulado histórico de kilómetros por Estado, Gestión, Tipo de Red y Capacidad.
SQL_QUERY = """
WITH regions AS (
  SELECT region AS state_name, ST_Union(geom::geometry) AS geom_union
  FROM administrative_regions GROUP BY region
),
cables AS (
  SELECT c.cb_id, o.or_nom AS management_unit, DATE_TRUNC('month', c.cb_created_at)::DATE AS month_date,
    CASE 
      WHEN c.cb_tier_level = 3 THEN 'TRONCAL'
      WHEN c.cb_tier_level = 2 THEN 'DISTRIBUCION'
      WHEN c.cb_tier_level = 1 THEN 'DROP'
      ELSE 'OTRO'
    END AS network_type,
    COALESCE(c.cb_capacity, 0) AS capacity, c.cb_total_length, c.cb_geometry::geometry AS geom 
  FROM network_cables c 
  LEFT JOIN organizations o ON c.cb_owner = o.or_id 
  WHERE c.cb_parent_id IS NULL AND c.cb_deleted_at IS NULL AND c.cb_total_length > 0
),
intersections AS (
  SELECT c.cb_id, r.state_name,
    ST_Length(ST_Intersection(c.geom, r.geom_union)::geography) / NULLIF(ST_Length(c.geom::geography), 0) AS ratio 
  FROM cables c 
  JOIN regions r ON c.geom && r.geom_union AND ST_Intersects(c.geom, r.geom_union)
),
ranked_intersections AS (
  SELECT cb_id, state_name, ratio,
    ROW_NUMBER() OVER(PARTITION BY cb_id ORDER BY ratio DESC, state_name ASC) AS rank_order
  FROM intersections
),
stats AS (
  SELECT cb_id, SUM(ratio) AS total_ratio, MAX(CASE WHEN rank_order = 1 THEN state_name END) AS primary_state
  FROM ranked_intersections GROUP BY cb_id
),
prorated_cables AS (
  SELECT c.month_date, c.management_unit, c.network_type, c.capacity, COALESCE(i.state_name, 'OUT_OF_BOUNDS') AS state_name,
    CASE 
      WHEN i.state_name IS NULL THEN 1.0
      WHEN i.state_name = s.primary_state THEN i.ratio + (1.0 - s.total_ratio)
      ELSE i.ratio 
    END AS final_ratio,
    (c.cb_total_length / 1000.0) AS total_km
  FROM cables c 
  LEFT JOIN intersections i ON c.cb_id = i.cb_id 
  LEFT JOIN stats s ON c.cb_id = s.cb_id
),
raw_data AS (
  SELECT month_date, management_unit, state_name, network_type, capacity, SUM(total_km * final_ratio) AS period_km
  FROM prorated_cables
  WHERE final_ratio > 0.0001 OR state_name = 'OUT_OF_BOUNDS'
  GROUP BY 1, 2, 3, 4, 5
),
timeline AS (
  SELECT generate_series((SELECT MIN(month_date) FROM raw_data), DATE_TRUNC('month', CURRENT_DATE)::DATE, '1 month'::interval)::DATE AS time_series_month
),
real_combinations AS (
  SELECT DISTINCT management_unit, state_name, network_type, capacity FROM raw_data
),
full_matrix AS (
  SELECT t.time_series_month, rc.state_name, rc.management_unit, rc.network_type, rc.capacity,
    COALESCE(d.period_km, 0)::NUMERIC(10,3) AS monthly_km
  FROM timeline t
  CROSS JOIN real_combinations rc 
  LEFT JOIN raw_data d ON d.month_date = t.time_series_month AND d.state_name = rc.state_name AND d.management_unit = rc.management_unit AND d.network_type = rc.network_type AND d.capacity = rc.capacity
),
final_calculation AS (
  SELECT time_series_month, EXTRACT(MONTH FROM time_series_month)::INTEGER AS month_val, EXTRACT(YEAR FROM time_series_month)::INTEGER AS year_val,
    management_unit, state_name, network_type, capacity, monthly_km,
    SUM(monthly_km) OVER (PARTITION BY state_name, management_unit, network_type, capacity ORDER BY time_series_month ASC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)::NUMERIC(10,3) AS historical_accumulated
  FROM full_matrix
)
SELECT month_val AS mes, year_val AS anio, management_unit AS gestion, state_name AS estado, network_type AS tipo_de_red, capacity AS capacidad, monthly_km AS km_mensuales, historical_accumulated AS acumulado_historico
FROM final_calculation WHERE historical_accumulated > 0
ORDER BY anio DESC, mes DESC, estado ASC, tipo_de_red ASC, capacidad ASC;
"""