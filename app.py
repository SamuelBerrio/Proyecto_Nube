from flask import Flask, render_template, request, redirect, url_for, send_from_directory, session, flash, jsonify
import os
import shutil
import json
from zipfile import ZipFile
from functools import wraps
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'clave_secreta_segura'

BASE_DIR = "./vms"
os.makedirs(BASE_DIR, exist_ok=True)

USUARIOS = {"admin": "admin123", "usuario": "password"}

# Decorador para verificar si el usuario está autenticado
def login_requerido(f):
    @wraps(f)
    def decorador(*args, **kwargs):
        if 'usuario' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorador

# Ruta para iniciar sesión
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        contraseña = request.form['contraseña']
        if usuario in USUARIOS and USUARIOS[usuario] == contraseña:
            session['usuario'] = usuario
            return redirect(url_for('index'))
        flash("Credenciales incorrectas", "danger")
        return redirect(url_for('login'))
    return render_template('login.html', datetime=datetime)

@app.route('/logout')
@login_requerido
def logout():
    session.pop('usuario', None)
    return redirect(url_for('login'))

# Página principal
@app.route('/')
@login_requerido
def index():
    vms = os.listdir(BASE_DIR)
    vm_info_list = []
    for vm in vms:
        ruta_vm = os.path.join(BASE_DIR, vm)
        config_path = os.path.join(ruta_vm, "config.json")
        if os.path.exists(config_path):
            with open(config_path, "r") as config_file:
                config = json.load(config_file)
                vm_info = {
                    "nombre": vm,
                    "almacenamiento_maximo": config.get("almacenamiento_maximo", 0),
                    "almacenamiento_expandido": config.get("almacenamiento_expandido", 0),
                    "espacio_usado": config.get("espacio_usado", 0),
                    "fecha_creacion": config.get("fecha_creacion", "Desconocida"),
                    "elastica": config.get("elastica", False)
                }
                vm_info_list.append(vm_info)
    return render_template('index.html', vms=vm_info_list, datetime=datetime)


# Crear una nueva VM con características adicionales
@app.route('/crear_vm', methods=['POST'])
@login_requerido
def crear_vm():
    nombre_vm = request.form['nombre_vm'].strip()
    if not nombre_vm:
        flash("El nombre de la VM no puede estar vacío", "danger")
        return redirect(url_for('index'))

    try:
        almacenamiento_maximo = int(request.form['almacenamiento_maximo']) * 1024 * 1024  # Convertir MB a bytes
    except ValueError:
        flash("El almacenamiento máximo debe ser un número entero", "danger")
        return redirect(url_for('index'))

    elastica = 'elastica' in request.form  # Verificar si la VM es elástica

    ruta_vm = os.path.join(BASE_DIR, nombre_vm)
    if not os.path.exists(ruta_vm):
        os.makedirs(ruta_vm)
        config = {
            "nombre": nombre_vm,
            "almacenamiento_maximo": almacenamiento_maximo,
            "almacenamiento_expandido": 0,
            "espacio_usado": 0,
            "fecha_creacion": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "elastica": elastica
        }
        with open(os.path.join(ruta_vm, "config.json"), "w") as config_file:
            json.dump(config, config_file)
        flash(f"VM '{nombre_vm}' creada exitosamente", "success")
    else:
        flash("Ya existe una VM con ese nombre", "danger")
    return redirect(url_for('index'))

# Eliminar una VM
@app.route('/eliminar_vm/<nombre_vm>', methods=['POST'])
@login_requerido
def eliminar_vm(nombre_vm):
    ruta_vm = os.path.join(BASE_DIR, nombre_vm)
    if os.path.exists(ruta_vm) and os.path.isdir(ruta_vm):
        shutil.rmtree(ruta_vm)
        flash(f"VM '{nombre_vm}' eliminada exitosamente", "success")
    else:
        flash("La VM no existe", "danger")
    return redirect(url_for('index'))

# Ver detalles de una VM
@app.route('/vm/<nombre_vm>')
@login_requerido
def ver_vm(nombre_vm):
    ruta_vm = os.path.join(BASE_DIR, nombre_vm)
    config_path = os.path.join(ruta_vm, "config.json")
    if not os.path.exists(config_path):
        flash("La VM no existe", "danger")
        return redirect(url_for('index'))
    with open(config_path, "r") as config_file:
        config = json.load(config_file)

    archivos = [f for f in os.listdir(ruta_vm) if os.path.isfile(os.path.join(ruta_vm, f)) and f != "config.json"]
    archivos_info = []
    for archivo in archivos:
        archivo_path = os.path.join(ruta_vm, archivo)
        archivos_info.append({
            "nombre": archivo,
            "size": os.path.getsize(archivo_path)
        })

    # Obtener lista de otras VMs
    vms = os.listdir(BASE_DIR)
    otras_vms = [vm for vm in vms if vm != nombre_vm and os.path.isdir(os.path.join(BASE_DIR, vm))]

    return render_template('vm.html', nombre_vm=nombre_vm, archivos=archivos_info, config=config, otras_vms=otras_vms)

# Subir un archivo a una VM respetando el límite de almacenamiento (mediante AJAX)
@app.route('/subir_archivo_ajax/<nombre_vm>', methods=['POST'])
@login_requerido
def subir_archivo_ajax(nombre_vm):
    ruta_vm = os.path.join(BASE_DIR, nombre_vm)
    if not os.path.exists(ruta_vm):
        return jsonify({'status': 'error', 'message': 'La VM no existe'}), 404

    archivo = request.files.get('archivo')
    if not archivo or archivo.filename == '':
        return jsonify({'status': 'error', 'message': 'No se ha seleccionado ningún archivo'}), 400

    archivo_path = os.path.join(ruta_vm, archivo.filename)
    archivo_size = os.fstat(archivo.stream.fileno()).st_size

    config_path = os.path.join(ruta_vm, "config.json")
    with open(config_path, "r") as config_file:
        config = json.load(config_file)

    espacio_disponible = config["almacenamiento_maximo"] - config["espacio_usado"]
    if archivo_size > espacio_disponible:
        if config.get("elastica", False):
            # Ampliar automáticamente el espacio de la VM
            incremento = max(archivo_size - espacio_disponible, 50 * 1024 * 1024)  # Aumentar al menos 50 MB o lo necesario
            config["almacenamiento_maximo"] += incremento
            config["almacenamiento_expandido"] += incremento
            mensaje = f"El espacio de la VM '{nombre_vm}' se ha ampliado automáticamente en {incremento // (1024 * 1024)} MB"
        else:
            return jsonify({'status': 'error', 'message': f"No hay suficiente espacio en la VM '{nombre_vm}'. Espacio disponible: {espacio_disponible // (1024 * 1024)} MB"}), 400

    archivo.save(archivo_path)

    config["espacio_usado"] += archivo_size
    with open(config_path, "w") as config_file:
        json.dump(config, config_file)

    return jsonify({'status': 'success', 'message': f"Archivo '{archivo.filename}' subido exitosamente", 'filename': archivo.filename, 'size': archivo_size})

# Función para sincronizar archivos entre todas las VMs
def sincronizar_archivo(origen_vm, archivo, archivo_size):
    ruta_origen = os.path.join(BASE_DIR, origen_vm, archivo)
    for vm in os.listdir(BASE_DIR):
        if vm != origen_vm:
            ruta_destino_vm = os.path.join(BASE_DIR, vm)
            ruta_destino = os.path.join(ruta_destino_vm, archivo)
            if os.path.exists(ruta_destino_vm):
                config_path = os.path.join(ruta_destino_vm, "config.json")
                with open(config_path, "r") as config_file:
                    config = json.load(config_file)

                espacio_disponible = config["almacenamiento_maximo"] - config["espacio_usado"]
                if archivo_size > espacio_disponible:
                    if config.get("elastica", False):
                        # Ampliar automáticamente el espacio de la VM
                        incremento = max(archivo_size - espacio_disponible, 50 * 1024 * 1024)
                        config["almacenamiento_maximo"] += incremento
                        config["almacenamiento_expandido"] += incremento
                        # No enviamos mensajes flash aquí porque estamos en una solicitud AJAX
                    else:
                        # No podemos sincronizar con esta VM por falta de espacio
                        continue

                shutil.copy(ruta_origen, ruta_destino)
                config["espacio_usado"] += archivo_size
                with open(config_path, "w") as config_file:
                    json.dump(config, config_file)

# Sincronizar archivos entre todas las VMs (mediante una solicitud normal)
@app.route('/sincronizar_vms', methods=['GET', 'POST'])
@login_requerido
def sincronizar_vms():
    mensajes = []
    try:
        vms = os.listdir(BASE_DIR)
        for vm in vms:
            ruta_vm = os.path.join(BASE_DIR, vm)
            if not os.path.isdir(ruta_vm):
                continue
            archivos_vm = [f for f in os.listdir(ruta_vm) if f != "config.json"]
            for archivo in archivos_vm:
                ruta_origen = os.path.join(ruta_vm, archivo)
                archivo_size = os.path.getsize(ruta_origen)
                for otra_vm in vms:
                    if otra_vm != vm:
                        ruta_otra_vm = os.path.join(BASE_DIR, otra_vm)
                        ruta_destino = os.path.join(ruta_otra_vm, archivo)
                        if os.path.exists(ruta_otra_vm) and not os.path.exists(ruta_destino):
                            config_path = os.path.join(ruta_otra_vm, "config.json")
                            with open(config_path, "r") as config_file:
                                config = json.load(config_file)

                            espacio_disponible = config["almacenamiento_maximo"] - config["espacio_usado"]
                            if archivo_size > espacio_disponible:
                                if config.get("elastica", False):
                                    incremento = max(archivo_size - espacio_disponible, 50 * 1024 * 1024)
                                    config["almacenamiento_maximo"] += incremento
                                    config["almacenamiento_expandido"] += incremento
                                    mensajes.append(f"El espacio de la VM '{otra_vm}' se ha ampliado automáticamente en {incremento // (1024 * 1024)} MB")
                                else:
                                    mensajes.append(f"No se pudo sincronizar '{archivo}' con la VM '{otra_vm}' por falta de espacio")
                                    continue

                            shutil.copy(ruta_origen, ruta_destino)
                            config["espacio_usado"] += archivo_size
                            with open(config_path, "w") as config_file:
                                json.dump(config, config_file)
        flash("Sincronización completada", "success")
        for mensaje in mensajes:
            flash(mensaje, "info")
        return redirect(url_for('index'))
    except Exception as e:
        print(f"Error durante la sincronización: {e}")
        flash("Ocurrió un error durante la sincronización", "danger")
        return redirect(url_for('index'))
    
# Sincronizar archivos entre todas las VMs (mediante AJAX)
@app.route('/sincronizar_vms_ajax', methods=['POST'])
@login_requerido
def sincronizar_vms_ajax():
    mensajes = []
    try:
        vms = os.listdir(BASE_DIR)
        for vm in vms:
            ruta_vm = os.path.join(BASE_DIR, vm)
            if not os.path.isdir(ruta_vm):
                continue
            archivos_vm = [f for f in os.listdir(ruta_vm) if f != "config.json"]
            for archivo in archivos_vm:
                ruta_origen = os.path.join(ruta_vm, archivo)
                archivo_size = os.path.getsize(ruta_origen)
                for otra_vm in vms:
                    if otra_vm != vm:
                        ruta_otra_vm = os.path.join(BASE_DIR, otra_vm)
                        ruta_destino = os.path.join(ruta_otra_vm, archivo)
                        if os.path.exists(ruta_otra_vm) and not os.path.exists(ruta_destino):
                            config_path = os.path.join(ruta_otra_vm, "config.json")
                            with open(config_path, "r") as config_file:
                                config = json.load(config_file)

                            espacio_disponible = config["almacenamiento_maximo"] - config["espacio_usado"]
                            if archivo_size > espacio_disponible:
                                if config.get("elastica", False):
                                    incremento = max(archivo_size - espacio_disponible, 50 * 1024 * 1024)
                                    config["almacenamiento_maximo"] += incremento
                                    config["almacenamiento_expandido"] += incremento
                                    mensajes.append(f"El espacio de la VM '{otra_vm}' se ha ampliado automáticamente en {incremento // (1024 * 1024)} MB")
                                else:
                                    mensajes.append(f"No se pudo sincronizar '{archivo}' con la VM '{otra_vm}' por falta de espacio")
                                    continue

                            shutil.copy(ruta_origen, ruta_destino)
                            config["espacio_usado"] += archivo_size
                            with open(config_path, "w") as config_file:
                                json.dump(config, config_file)
        # Retornar una respuesta JSON exitosa
        return jsonify({'status': 'success', 'messages': mensajes})
    except Exception as e:
        print(f"Error durante la sincronización: {e}")
        # Retornar una respuesta JSON de error
        return jsonify({'status': 'error', 'message': 'Ocurrió un error durante la sincronización'}), 500

@app.route('/sincronizar_vm_individual_ajax/<nombre_vm>', methods=['POST'])
@login_requerido
def sincronizar_vm_individual_ajax(nombre_vm):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'No se enviaron datos'}), 400
        archivos_seleccionados = data.get('archivos', [])
        vms_destino = data.get('vms', [])

        if not archivos_seleccionados or not vms_destino:
            return jsonify({'status': 'error', 'message': 'No se seleccionaron archivos o VMs de destino'}), 400

        ruta_vm_origen = os.path.join(BASE_DIR, nombre_vm)
        mensajes = []

        for vm_destino in vms_destino:
            ruta_vm_destino = os.path.join(BASE_DIR, vm_destino)
            if not os.path.exists(ruta_vm_destino):
                mensajes.append(f"La VM '{vm_destino}' no existe.")
                continue

            config_path = os.path.join(ruta_vm_destino, "config.json")
            with open(config_path, "r") as config_file:
                config = json.load(config_file)

            espacio_disponible = config["almacenamiento_maximo"] - config["espacio_usado"]
            total_size = 0
            archivos_a_copiar = []

            for archivo in archivos_seleccionados:
                ruta_origen = os.path.join(ruta_vm_origen, archivo)
                ruta_destino = os.path.join(ruta_vm_destino, archivo)
                if not os.path.exists(ruta_origen):
                    mensajes.append(f"El archivo '{archivo}' no existe en la VM '{nombre_vm}'.")
                    continue
                if os.path.exists(ruta_destino):
                    mensajes.append(f"El archivo '{archivo}' ya existe en la VM '{vm_destino}'.")
                    continue
                archivo_size = os.path.getsize(ruta_origen)
                total_size += archivo_size
                archivos_a_copiar.append((ruta_origen, ruta_destino, archivo_size))

            if total_size > espacio_disponible:
                if config.get("elastica", False):
                    incremento = max(total_size - espacio_disponible, 50 * 1024 * 1024)
                    config["almacenamiento_maximo"] += incremento
                    config["almacenamiento_expandido"] += incremento
                    mensajes.append(f"El espacio de la VM '{vm_destino}' se ha ampliado automáticamente en {incremento // (1024 * 1024)} MB")
                else:
                    mensajes.append(f"No se pudo sincronizar con la VM '{vm_destino}' por falta de espacio")
                    continue

            for ruta_origen, ruta_destino, archivo_size in archivos_a_copiar:
                shutil.copy(ruta_origen, ruta_destino)
                config["espacio_usado"] += archivo_size

            with open(config_path, "w") as config_file:
                json.dump(config, config_file)

        return jsonify({'status': 'success', 'messages': mensajes})
    except Exception as e:
        print(f"Error durante la sincronización: {e}")
        return jsonify({'status': 'error', 'message': 'Ocurrió un error durante la sincronización'}), 500

# Descargar un archivo de una VM
@app.route('/descargar_archivo/<nombre_vm>/<nombre_archivo>')
@login_requerido
def descargar_archivo(nombre_vm, nombre_archivo):
    ruta_vm = os.path.join(BASE_DIR, nombre_vm)
    archivo_path = os.path.join(ruta_vm, nombre_archivo)
    if not os.path.exists(archivo_path):
        flash("El archivo no existe", "danger")
        return redirect(url_for('ver_vm', nombre_vm=nombre_vm))
    return send_from_directory(ruta_vm, nombre_archivo, as_attachment=True)

# Eliminar un archivo y liberar espacio
@app.route('/eliminar_archivo/<nombre_vm>/<nombre_archivo>', methods=['POST'])
@login_requerido
def eliminar_archivo(nombre_vm, nombre_archivo):
    ruta_vm = os.path.join(BASE_DIR, nombre_vm)
    archivo_path = os.path.join(ruta_vm, nombre_archivo)
    if os.path.exists(archivo_path):
        archivo_size = os.path.getsize(archivo_path)
        os.remove(archivo_path)
        config_path = os.path.join(ruta_vm, "config.json")
        with open(config_path, "r") as config_file:
            config = json.load(config_file)
        config["espacio_usado"] -= archivo_size
        with open(config_path, "w") as config_file:
            json.dump(config, config_file)
        flash(f"Archivo '{nombre_archivo}' eliminado de la VM '{nombre_vm}'", "success")
    else:
        flash("El archivo no existe", "danger")
    return redirect(url_for('ver_vm', nombre_vm=nombre_vm))

# Descargar respaldo como ZIP
@app.route('/respaldo_vm/<nombre_vm>')
@login_requerido
def respaldo_vm(nombre_vm):
    ruta_vm = os.path.join(BASE_DIR, nombre_vm)
    if not os.path.exists(ruta_vm):
        flash("La VM no existe", "danger")
        return redirect(url_for('index'))

    zip_filename = f"{nombre_vm}.zip"
    zip_path = os.path.join(BASE_DIR, zip_filename)
    with ZipFile(zip_path, 'w') as zipf:
        for archivo in os.listdir(ruta_vm):
            if archivo != "config.json":
                zipf.write(os.path.join(ruta_vm, archivo), os.path.join(nombre_vm, archivo))
    return send_from_directory(BASE_DIR, zip_filename, as_attachment=True)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
