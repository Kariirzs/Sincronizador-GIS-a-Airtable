# Pipeline Autónomo de Extracción Espacial GIS y Sincronización ETL

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![PostGIS](https://img.shields.io/badge/PostGIS-Consultas_Espaciales-green?logo=postgresql&logoColor=white)](https://postgis.net/)
[![Apache Superset](https://img.shields.io/badge/Plataforma-Apache_Superset-red?logo=apache-superset&logoColor=white)](https://superset.apache.org/)
[![Airtable API](https://img.shields.io/badge/Destino-Airtable_REST_API-yellow?logo=airtable&logoColor=white)](https://airtable.com/)

Pipeline de extracción, transformación y carga (ETL) empresarial escrito en Python para consultar datos de infraestructura espacial de telecomunicaciones desde **Apache Superset (PostGIS)** y sincronizarlos de forma incremental hacia **Airtable**.

El proyecto implementa el patrón **Sync-on_Change** mediante firmas **MD5**, logrando reducir en más de un 95% el consumo de la API de destino.

---

## Aspectos Técnicos Destacados

* **Autenticación Autónoma de Sesión:** Simula el flujo de inicio de sesión web usando `requests.Session` y parseo dinámico de tokens CSRF con `BeautifulSoup`.
* **Análisis Espacial PostGIS:** Procesa intersecciones geométricas complejas (`ST_Intersection`, `ST_Union`) para prorratear la longitud de fibra óptica sobre límites territoriales.
* **Sincronización Incremental (MD5):** Calcula la huella digital del estado de cada fila (`cache_state.json`), ejecutando únicamente operaciones necesarias (Altas, Bajas o Modificaciones).
* **Claves Primarias Compuestas:** Genera identificadores unívocos (`YYYY-MM-GES-ESTADO-RED-CAP`) para evitar colisiones entre registros con prefijos comunes.
* **Casteo Dinámico de Esquema (`typecast`):** Habilita la actualización automática de campos de selección única (*Single Select*) mediante el parámetro `typecast: true` en la API de Airtable.

---

## Arquitectura del Sistema

```text
┌────────────────────────────────────────────────────────────────────────┐
│                   1. ORIGEN: Plataforma GIS (PostGIS)                  │
│  • Autenticación de sesión HTTP (Cookies firmadas + Token CSRF)        │
│  • Consulta SELECT espacial de solo lectura en Apache Superset         │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   2. PIPELINE: Motor Delta en Python                   │
│  • Generación de Clave Única: YYYY-MM-GES-ESTADO-RED-CAP               │
│  • Cálculo de firma digital Hash MD5 por fila                          │
│  • Comparación Delta contra memoria local previa (cache_state.json)    │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
       ┌───────────────────────────┼───────────────────────────┐
       │                           │                           │
       ▼                           ▼                           ▼
     CREAR                     ACTUALIZAR                   ELIMINAR
(Nuevos registros)         (Firma MD5 modificada)      (Obsoletos en el origen)
       │                           │                           │
       └───────────────────────────┼───────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   3. DESTINO: API REST de Airtable                     │
│  • Procesamiento en lotes de máximo 10 registros por petición          │
│  • Casteo dinámico de esquemas habilitado                              │
│  • Persistencia del mapa de firmas en "cache_state.json"               │
└──────────────────────────────────┴─────────────────────────────────────┘
```

---

## Estructura del Proyecto

```text
├── .env.example        # Plantilla genérica para variables de entorno
├── .gitignore          # Exclusión de credenciales y caché local
├── config.py           # Configuración de URLs y consulta SQL espacial
├── utils.py            # Funciones auxiliares (IDs únicos, Hash MD5, limpieza)
├── processor.py        # Motor de autenticación, extracción y procesamiento Delta
├── main.py             # Punto de entrada principal para el automatismo
├── test_extraction.py  # Script de diagnóstico y validación de consulta
└── requirements.txt    # Librerías de Python requeridas
```

## Instalación y Uso

#### 1. Clonar el repositorio:

```
git clone [https://github.com/tu-usuario/pipeline-sincronizacion-gis-airtable.git](https://github.com/tu-usuario/pipeline-sincronizacion-gis-airtable.git)
cd pipeline-sincronizacion-gis-airtable
```

#### 2. Crear y activar entorno virtual:

```
python -m venv .venv

# En Windows:
.venv\Scripts\activate

# En Linux/Mac:
source .venv/bin/activate
```

#### 3. Instalar dependencias:

```
pip install -r requirements.txt
```

#### 4. Configurar variables de entorno:

Copia `.env.example` como `.env` e ingresa las credenciales:

```
cp .env.example .env
```

#### 5. Ejecutar el Pipeline:

```
python main.py
```

---

## Licencia

Distribuido bajo la licencia MIT. Consulta el archivo `LICENSE` para más información.

_Desarrollado con fines de conectar el análisis espacial PostGIS con tableros operativos en tiempo real de forma 100% autónoma._